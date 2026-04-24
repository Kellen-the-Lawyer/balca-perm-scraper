#!/usr/bin/env python3
"""
Download and ingest AAO/INS precedent decisions from:
https://www.justice.gov/archives/eoir/dhs-aao-ins-decisions

Runs in two phases:
1. Parse the full page HTML (with a browser-style UA) to extract all PDF links
2. Download each PDF, extract text with pdfplumber, insert into DB
"""
import asyncio, logging, os, re, time, io
import httpx
import pdfplumber
import asyncpg
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

SOURCE_URL = "https://www.justice.gov/archives/eoir/dhs-aao-ins-decisions"
SAVE_DIR   = "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/AAO Precedents"
DB_URL     = "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"
BASE       = "https://www.justice.gov"

os.makedirs(SAVE_DIR, exist_ok=True)

# ── Use a browser User-Agent so the DOJ server returns full HTML ───────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ── Schema ────────────────────────────────────────────────────────────────────
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS precedent_decisions (
    id            SERIAL PRIMARY KEY,
    volume        INTEGER,
    citation      TEXT NOT NULL,
    party_name    TEXT NOT NULL,
    year          INTEGER,
    body          TEXT,
    pdf_url       TEXT NOT NULL,
    pdf_path      TEXT,
    full_text     TEXT NOT NULL DEFAULT '',
    search_vector TSVECTOR,
    ingested_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prec_citation ON precedent_decisions(citation);
CREATE INDEX IF NOT EXISTS idx_prec_search ON precedent_decisions USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_prec_volume ON precedent_decisions(volume);

CREATE OR REPLACE FUNCTION update_prec_search() RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.party_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.citation, '')),   'B') ||
    setweight(to_tsvector('english', coalesce(NEW.full_text, '')),  'D');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prec_search ON precedent_decisions;
CREATE TRIGGER trg_prec_search
  BEFORE INSERT OR UPDATE ON precedent_decisions
  FOR EACH ROW EXECUTE FUNCTION update_prec_search();
"""


def parse_index(html: str) -> list[dict]:
    """Parse the DOJ page HTML and extract all precedent decision entries."""
    soup = BeautifulSoup(html, "html.parser")
    decisions = []
    current_volume = None

    # Find all elements in main content area
    main = soup.find("main") or soup.find("div", id="main-content") or soup.body
    if not main:
        return decisions

    for elem in main.find_all(["h2", "p", "li", "div"]):
        text = elem.get_text(" ", strip=True)

        # Volume header
        vm = re.match(r"^Volume\s+(\d+)$", text.strip(), re.IGNORECASE)
        if vm:
            current_volume = int(vm.group(1))
            continue

        # Must contain I&N Dec. to be a decision entry
        if "I&N Dec" not in text and "I&amp;N Dec" not in text:
            continue

        # Find all PDF-like links
        for a in elem.find_all("a", href=True):
            href = a["href"]
            is_pdf_link = (
                href.endswith(".pdf")
                or "/dl?" in href
                or ("/media/" in href and "eoir" in href)
                or "/media/" in href
            )
            if not is_pdf_link:
                continue

            if href.startswith("/"):
                href = BASE + href
            if not href.startswith("http"):
                continue

            # Parse citation: vol I&N Dec. page
            cite_m = re.search(r"(\d+)\s*I&(?:amp;)?N\s*Dec\.?\s*(\d+)", text, re.IGNORECASE)
            if not cite_m:
                continue
            vol_num = int(cite_m.group(1))
            page    = cite_m.group(2)
            citation = f"{vol_num} I&N Dec. {page}"

            # Party name: bold text or everything before the citation
            party = ""
            for bold in elem.find_all(["strong", "b"]):
                t = bold.get_text(strip=True).strip(".,* ")
                if t:
                    party = t
                    break
            if not party:
                before = text[:text.find(cite_m.group(0))].strip().strip(".,* ")
                party = re.sub(r"\s+", " ", before).strip()

            # Year and body
            year_m = re.search(r"\(([^)]+?)\s+(\d{4})\)", text)
            year = int(year_m.group(2)) if year_m else None
            body = year_m.group(1).strip() if year_m else ""

            decisions.append({
                "volume":    current_volume or vol_num,
                "citation":  citation,
                "party_name": party[:200],
                "year":      year,
                "body":      body[:100],
                "pdf_url":   href,
            })
            break  # one PDF per decision line

    # Deduplicate by citation
    seen, unique = set(), []
    for d in decisions:
        if d["citation"] not in seen:
            seen.add(d["citation"])
            unique.append(d)
    return unique


async def download_pdf(client: httpx.AsyncClient, d: dict) -> dict:
    """Download PDF, save to disk, extract text."""
    safe = re.sub(r"[^\w\-]", "_", d["citation"])
    fpath = os.path.join(SAVE_DIR, safe + ".pdf")

    if not os.path.exists(fpath):
        try:
            resp = await client.get(d["pdf_url"], follow_redirects=True, timeout=30)
            resp.raise_for_status()
            with open(fpath, "wb") as f:
                f.write(resp.content)
            await asyncio.sleep(0.4)  # polite pacing
        except Exception as e:
            log.warning(f"  Download failed {d['citation']}: {e}")
            return {**d, "pdf_path": None, "full_text": ""}
    else:
        log.info(f"  Already downloaded: {d['citation']}")

    try:
        with pdfplumber.open(fpath) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        full_text = "\n\n".join(pages)
    except Exception as e:
        log.warning(f"  Text extract failed {d['citation']}: {e}")
        full_text = ""

    return {**d, "pdf_path": fpath, "full_text": full_text}


async def main():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute(CREATE_SQL)
    log.info("Schema ready")

    # Fetch page with browser UA
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        log.info(f"Fetching index: {SOURCE_URL}")
        resp = await client.get(SOURCE_URL, follow_redirects=True)
        resp.raise_for_status()
        log.info(f"  Response size: {len(resp.text):,} bytes")

        decisions = parse_index(resp.text)
        log.info(f"  Found {len(decisions)} decisions")

        if not decisions:
            log.error("No decisions parsed — page may require JavaScript rendering.")
            log.error("Check the response content below:")
            log.error(resp.text[:500])
            await conn.close()
            return

        for i, d in enumerate(decisions):
            log.info(f"[{i+1}/{len(decisions)}] {d['citation']} — {d['party_name']}")
            d = await download_pdf(client, d)

            await conn.execute("""
                INSERT INTO precedent_decisions
                  (volume, citation, party_name, year, body, pdf_url, pdf_path, full_text)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (citation) DO UPDATE SET
                  full_text   = EXCLUDED.full_text,
                  pdf_path    = EXCLUDED.pdf_path,
                  party_name  = EXCLUDED.party_name
            """, d["volume"], d["citation"], d["party_name"],
                 d["year"], d["body"], d["pdf_url"],
                 d["pdf_path"], d["full_text"])

    total = await conn.fetchval("SELECT COUNT(*) FROM precedent_decisions")
    log.info(f"\nDone. {total} precedent decisions in DB.")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Download and ingest AAO/INS precedent decisions.
All entries captured from https://www.justice.gov/archives/eoir/dhs-aao-ins-decisions
(DOJ uses bot-detection so we use the pre-parsed list directly.)
"""
import asyncio, logging, os, re, io
import httpx
import pdfplumber
import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

SAVE_DIR = "/Users/Dad/Library/CloudStorage/OneDrive-KellenPowell,Esq/Resources/AAO Precedents"
DB_URL   = "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions"
B        = "https://www.justice.gov"

os.makedirs(SAVE_DIR, exist_ok=True)

DECISIONS = [
    # ── Volume 29 ─────────────────────────────────────────────────────────────
    (29,"29 I&N Dec. 491","Texperts, Inc.",2026,"AAO",B+"/eoir/media/1430151/dl?inline"),
    # ── Volume 27 ─────────────────────────────────────────────────────────────
    (27,"27 I&N Dec. 617","H-G-G-",2019,"AAO",B+"/media/1026966/dl?inline"),
    # ── Volume 26 ─────────────────────────────────────────────────────────────
    (26,"26 I&N Dec. 884","Dhanasar",2016,"AAO",B+"/media/871246/dl?inline"),
    (26,"26 I&N Dec. 542","Simeio Solutions, LLC",2015,"AAO",B+"/sites/default/files/eoir/pages/attachments/2015/04/16/3832.pdf"),
    (26,"26 I&N Dec. 537","Christo's, Inc.",2015,"AAO",B+"/sites/default/files/eoir/pages/attachments/2015/04/16/3831.pdf"),
    (26,"26 I&N Dec. 532","Leacheng International, Inc.",2015,"AAO",B+"/sites/default/files/eoir/pages/attachments/2015/04/16/3830.pdf"),
    # ── Volume 25 ─────────────────────────────────────────────────────────────
    (25,"25 I&N Dec. 799","Skirball Cultural Center",2012,"AAO",B+"/eoir/vll/intdec/vol25/3752.pdf"),
    (25,"25 I&N Dec. 369","Chawathe",2010,"AAO",B+"/eoir/vll/intdec/vol25/3700.pdf"),
    (25,"25 I&N Dec. 359","Al Wazzan",2010,"AAO",B+"/eoir/vll/intdec/vol25/3699.pdf"),
    # ── Volume 22 ─────────────────────────────────────────────────────────────
    (22,"22 I&N Dec. 215","NY State Dept of Trans",1998,"Comm.",B+"/eoir/vll/intdec/vol22/3363.pdf"),
    (22,"22 I&N Dec. 206","Ho",1998,"Assoc. Comm.",B+"/eoir/vll/intdec/vol22/3362.pdf"),
    (22,"22 I&N Dec. 201","Hsiung",1998,"Assoc. Comm.",B+"/eoir/vll/intdec/vol22/3361.pdf"),
    (22,"22 I&N Dec. 169","Izummi",1998,"Assoc. Comm.",B+"/eoir/vll/intdec/vol22/3360.pdf"),
    (22,"22 I&N Dec. 158","Soffici",1998,"Assoc. Comm.",B+"/eoir/vll/intdec/vol22/3359.pdf"),
    # ── Volume 19 ─────────────────────────────────────────────────────────────
    (19,"19 I&N Dec. 871","O-",1989,"Comm.",B+"/eoir/vll/intdec/vol19/3098.pdf"),
    (19,"19 I&N Dec. 867","A-",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3097.pdf"),
    (19,"19 I&N Dec. 861","M-",1989,"Comm.",B+"/eoir/vll/intdec/vol19/3096.pdf"),
    (19,"19 I&N Dec. 851","S-",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3094.pdf"),
    (19,"19 I&N Dec. 823","P-",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3090.pdf"),
    (19,"19 I&N Dec. 817","Sea, Inc.",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3089.pdf"),
    (19,"19 I&N Dec. 808","C-",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3087.pdf"),
    (19,"19 I&N Dec. 791","Caron International, Inc.",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3085.pdf"),
    (19,"19 I&N Dec. 760","N-",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3080.pdf"),
    (19,"19 I&N Dec. 679","Jalil",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3070.pdf"),
    (19,"19 I&N Dec. 666","Sandoz Crop Protection Corporation",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3067.pdf"),
    (19,"19 I&N Dec. 650","Cornell University",1987,"Comm.",B+"/eoir/vll/intdec/vol19/3062.pdf"),
    (19,"19 I&N Dec. 593","Church of Scientology International",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3052.pdf"),
    (19,"19 I&N Dec. 558","Michael Hertz Associates",1988,"Comm.",B+"/eoir/vll/intdec/vol19/3046.pdf"),
    (19,"19 I&N Dec. 481","Dial Auto Repair Shop, Inc.",1987,"Comm.",B+"/eoir/vll/intdec/vol19/3035.pdf"),
    (19,"19 I&N Dec. 412","Harry Bailen Builders, Inc.",1986,"Comm.",B+"/eoir/vll/intdec/vol19/3019.pdf"),
    (19,"19 I&N Dec. 401","Silver Dragon Chinese Restaurant",1986,"Comm.",B+"/eoir/vll/intdec/vol19/3017.pdf"),
    (19,"19 I&N Dec. 391","Faith Assembly Church",1986,"Comm.",B+"/eoir/vll/intdec/vol19/3014.pdf"),
    (19,"19 I&N Dec. 389","A. Dow Steam Specialities, LTD.",1986,"Comm.",B+"/eoir/vll/intdec/vol19/3013.pdf"),
    (19,"19 I&N Dec. 362","Siemens Medical Systems, Inc.",1986,"Comm.",B+"/eoir/vll/intdec/vol19/3008.pdf"),
    (19,"19 I&N Dec. 255","Barocio",1985,"Comm.",B+"/eoir/vll/intdec/vol19/2992.pdf"),
    (19,"19 I&N Dec. 252","Viado",1985,"Comm.",B+"/eoir/vll/intdec/vol19/2991.pdf"),
    (19,"19 I&N Dec. 248","United Investment Group",1984,"Comm.",B+"/eoir/vll/intdec/vol19/2990.pdf"),
    (19,"19 I&N Dec. 245","Ngai",1984,"Comm.",B+"/eoir/vll/intdec/vol19/2989.pdf"),
    (19,"19 I&N Dec. 241","Cantec Representatives, Inc.",1984,"Comm.",B+"/eoir/vll/intdec/vol19/2988.pdf"),
    (19,"19 I&N Dec. 238","Golden Dragon Chinese Restaurant",1984,"Comm.",B+"/eoir/vll/intdec/vol19/2987.pdf"),
    (19,"19 I&N Dec. 194","Portugues Do Atlantico Information Bureau, Inc.",1984,"Comm.",B+"/eoir/vll/intdec/vol19/2982.pdf"),
    (19,"19 I&N Dec. 124","Allied Fidelity Insurance Company",1984,"Comm.",B+"/eoir/vll/intdec/vol19/2972.pdf"),
    # ── Volume 18 ─────────────────────────────────────────────────────────────
    (18,"18 I&N Dec. 425","Ognibene",1983,"R.C.",B+"/eoir/vll/intdec/vol18/2947.pdf"),
    (18,"18 I&N Dec. 403","Arbelaez-Naranjo",1983,"R.C.",B+"/eoir/vll/intdec/vol18/2942.pdf"),
    (18,"18 I&N Dec. 339","Tanahan",1982,"R.C.",B+"/eoir/vll/intdec/vol18/2928.pdf"),
    (18,"18 I&N Dec. 308","St. Pierre",1982,"R.C.",B+"/eoir/vll/intdec/vol18/2921.pdf"),
    (18,"18 I&N Dec. 295","Kloeti",1982,"R.C.",B+"/eoir/vll/intdec/vol18/2918.pdf"),
    (18,"18 I&N Dec. 285","Ord",1982,"R.C.",B+"/eoir/vll/intdec/vol18/2916.pdf"),
    (18,"18 I&N Dec. 98","Aiyer",1981,"R.C.",B+"/eoir/vll/intdec/vol18/2877.pdf"),
    (18,"18 I&N Dec. 96","Lee",1981,"R.C.",B+"/eoir/vll/intdec/vol18/2876.pdf"),
    (18,"18 I&N Dec. 43","Kubacki",1981,"R.C.",B+"/eoir/vll/intdec/vol18/2863.pdf"),
    (18,"18 I&N Dec. 13","Barsai",1981,"R.C.",B+"/eoir/vll/intdec/vol18/2856.pdf"),
    (18,"18 I&N Dec. 12","Drennan",1981,"R.C.",B+"/eoir/vll/intdec/vol18/2876.pdf"),
    (18,"18 I&N Dec. 9","Rodriguez",1980,"R.C.",B+"/eoir/vll/intdec/vol18/2854.pdf"),
    # ── Volume 17 ─────────────────────────────────────────────────────────────
    (17,"17 I&N Dec. 634","Sheikh",1980,"R.C.",B+"/eoir/vll/intdec/vol17/2850.pdf"),
    (17,"17 I&N Dec. 571","Hedrick",1980,"R.C.",B+"/eoir/vll/intdec/vol17/2836.pdf"),
    (17,"17 I&N Dec. 569","Desai",1980,"R.C.",B+"/eoir/vll/intdec/vol17/2835.pdf"),
    (17,"17 I&N Dec. 534","John",1980,"R.C.",B+"/eoir/vll/intdec/vol17/2828.pdf"),
    (17,"17 I&N Dec. 433","Knudsen",1979,"R.C.",B+"/eoir/vll/intdec/vol17/2807.pdf"),
    (17,"17 I&N Dec. 430","Calka",1979,"R.C.",B+"/eoir/vll/intdec/vol17/2806.pdf"),
    (17,"17 I&N Dec. 428","Balodis",1980,"R.C.",B+"/eoir/vll/intdec/vol17/2805.pdf"),
    (17,"17 I&N Dec. 296","Allan Gee, Inc.",1979,"Acting R.C.",B+"/eoir/vll/intdec/vol17/2772.pdf"),
    (17,"17 I&N Dec. 285","Warrach",1979,"R.C.",B+"/eoir/vll/intdec/vol17/2769.pdf"),
    (17,"17 I&N Dec. 283","Sunoco Energy Development Company",1979,"R.C.",B+"/eoir/vll/intdec/vol17/2768.pdf"),
    (17,"17 I&N Dec. 269","Handley",1978,"R.C.",B+"/eoir/vll/intdec/vol17/2764.pdf"),
    (17,"17 I&N Dec. 266","Medical University of South Carolina",1978,"R.C.",B+"/eoir/vll/intdec/vol17/2763.pdf"),
    (17,"17 I&N Dec. 254","Csonka",1978,"R.C.",B+"/eoir/vll/intdec/vol17/2760.pdf"),
    (17,"17 I&N Dec. 251","Insurance Company of North America",1979,"Acting R.C.",B+"/eoir/vll/intdec/vol17/2768.pdf"),
    (17,"17 I&N Dec. 248","Michelin Tire Corporation",1978,"R.C.",B+"/eoir/vll/intdec/vol17/2758.pdf"),
    (17,"17 I&N Dec. 244","Shah",1977,"R.C.",B+"/eoir/vll/intdec/vol17/2757.pdf"),
    # ── Volume 16 ─────────────────────────────────────────────────────────────
    (16,"16 I&N Dec. 12","Leung",1976,"D.D.",B+"/eoir/vll/intdec/vol16/2530.pdf"),
    (16,"16 I&N Dec. 131","Vindman",1977,"R.C.",B+"/eoir/vll/intdec/vol16/2563.pdf"),
    (16,"16 I&N Dec. 142","Great Wall",1977,"Acting R.C.",B+"/eoir/vll/intdec/vol16/2566.pdf"),
    (16,"16 I&N Dec. 146","Smith",1977,"R.C.",B+"/eoir/vll/intdec/vol16/2567.pdf"),
    (16,"16 I&N Dec. 158","Wing's Tea House",1977,"Acting R.C.",B+"/eoir/vll/intdec/vol16/2570.pdf"),
    # ── Volume 15 ─────────────────────────────────────────────────────────────
    (15,"15 I&N Dec. 5","Del Mar Ben, Inc.",1974,"R.C.",B+"/eoir/vll/intdec/vol15/2303.pdf"),
    (15,"15 I&N Dec. 133","Peerless Insurance Company",1974,"R.C.",B+"/eoir/vll/intdec/vol15/2330.pdf"),
    (15,"15 I&N Dec. 147","Yang",1974,"R.C.",B+"/eoir/vll/intdec/vol15/2335.pdf"),
    (15,"15 I&N Dec. 176","Nguyen",1975,"R.C.",B+"/eoir/vll/intdec/vol15/2344.pdf"),
    (15,"15 I&N Dec. 187","Lee",1975,"R.C.",B+"/eoir/vll/intdec/vol15/2348.pdf"),
    (15,"15 I&N Dec. 304","Blaich",1975,"R.C.",B+"/eoir/vll/intdec/vol15/2384.pdf"),
    (15,"15 I&N Dec. 376","Wang",1975,"R.C.",B+"/eoir/vll/intdec/vol15/2404.pdf"),
    (15,"15 I&N Dec. 398","Patterson",1975,"Acting D.D.",B+"/eoir/vll/intdec/vol15/2411.pdf"),
    (15,"15 I&N Dec. 424","Jahromi",1975,"R.C.",B+"/eoir/vll/intdec/vol15/2420.pdf"),
    (15,"15 I&N Dec. 466","Thomopoulos",1975,"Acting R.C.",B+"/eoir/vll/intdec/vol15/2435.pdf"),
    (15,"15 I&N Dec. 494","Li",1975,"D.D.",B+"/eoir/vll/intdec/vol15/2445.pdf"),
    (15,"15 I&N Dec. 542","Mody",1975,"D.D.",B+"/eoir/vll/intdec/vol15/2460.pdf"),
    (15,"15 I&N Dec. 608","Samarius Industries, Inc.",1976,"R.C.",B+"/eoir/vll/intdec/vol15/2480.pdf"),
    (15,"15 I&N Dec. 681","Chung",1976,"R.C.",B+"/eoir/vll/intdec/vol15/2495.pdf"),
    (15,"15 I&N Dec. 698","Munguia",1976,"R.C.",B+"/eoir/vll/intdec/vol15/2501.pdf"),
    (15,"15 I&N Dec. 727","Gutierrez",1976,"R.C.",B+"/eoir/vll/intdec/vol15/2512.pdf"),
    (15,"15 I&N Dec. 729","Yarden",1976,"R.C.",B+"/eoir/vll/intdec/vol15/2513.pdf"),
    (15,"15 I&N Dec. 786","Lieu",1976,"Acting D.D.",B+"/eoir/vll/intdec/vol15/2523.pdf"),
    # ── Volume 14 ─────────────────────────────────────────────────────────────
    (14,"14 I&N Dec. 1","Souza",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2117.pdf"),
    (14,"14 I&N Dec. 27","Taheri",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2124.pdf"),
    (14,"14 I&N Dec. 45","Katigbak",1971,"R.C.",B+"/eoir/vll/intdec/vol14/2125.pdf"),
    (14,"14 I&N Dec. 55","Mosqueda",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2127.pdf"),
    (14,"14 I&N Dec. 113","Tabcum",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2141.pdf"),
    (14,"14 I&N Dec. 125","Zampetis",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2144.pdf"),
    (14,"14 I&N Dec. 140","Continental Grain Company",1972,"D.D.",B+"/eoir/vll/intdec/vol14/2148.pdf"),
    (14,"14 I&N Dec. 153","Blair",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2152.pdf"),
    (14,"14 I&N Dec. 165","Balbin",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2156.pdf"),
    (14,"14 I&N Dec. 185","H-",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2161.pdf"),
    (14,"14 I&N Dec. 188","Hayes",1972,"D.D.",B+"/eoir/vll/intdec/vol14/2162.pdf"),
    (14,"14 I&N Dec. 190","Treasure Craft of California",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2163.pdf"),
    (14,"14 I&N Dec. 196","Essex Cryogenics Industries, Inc.",1972,"Act. Assoc. Comm'r",B+"/eoir/vll/intdec/vol14/2164.pdf"),
    (14,"14 I&N Dec. 201","St. Joseph's Hospital",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2166.pdf"),
    (14,"14 I&N Dec. 213","University of Oklahoma",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2169.pdf"),
    (14,"14 I&N Dec. 241","Chu",1972,"R.C.",B+"/eoir/vll/intdec/vol14/2175.pdf"),
    (14,"14 I&N Dec. 290","Wu",1973,"R.C.",B+"/eoir/vll/intdec/vol14/2186.pdf"),
    (14,"14 I&N Dec. 344","Hsu",1973,"R.C.",B+"/eoir/vll/intdec/vol14/2199.pdf"),
    (14,"14 I&N Dec. 349","Ko",1973,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol14/2201.pdf"),
    (14,"14 I&N Dec. 354","Vargas",1973,"R.C.",B+"/eoir/vll/intdec/vol14/2202.pdf"),
    (14,"14 I&N Dec. 357","Chim",1973,"R.C.",B+"/eoir/vll/intdec/vol14/2203.pdf"),
    (14,"14 I&N Dec. 361","Acosta",1973,"D.D.",B+"/eoir/vll/intdec/vol14/2204.pdf"),
    (14,"14 I&N Dec. 371","Tin",1973,"R.C.",B+"/eoir/vll/intdec/vol14/2207.pdf"),
    (14,"14 I&N Dec. 375","Rapacon",1973,"R.C.",B+"/eoir/vll/intdec/vol14/2208.pdf"),
    (14,"14 I&N Dec. 384","Ugricic",1973,"D.D.",B+"/eoir/vll/intdec/vol14/2211.pdf"),
    (14,"14 I&N Dec. 387","Castaneda",1973,"R.C.",B+"/eoir/vll/intdec/vol14/2212.pdf"),
    (14,"14 I&N Dec. 390","Souqi",1973,"R.C.",B+"/eoir/vll/intdec/vol14/2213.pdf"),
    (14,"14 I&N Dec. 393","Guiot",1973,"D.D.",B+"/eoir/vll/intdec/vol14/2214.pdf"),
    (14,"14 I&N Dec. 499","Kwan",1973,"R.C.",B+"/eoir/vll/intdec/vol14/2247.pdf"),
    (14,"14 I&N Dec. 507","Rogalski",1973,"D.D.",B+"/eoir/vll/intdec/vol14/2250.pdf"),
    (14,"14 I&N Dec. 559","Kalia",1974,"R.C.",B+"/eoir/vll/intdec/vol14/2257.pdf"),
    (14,"14 I&N Dec. 569","Pozzoli",1974,"R.C.",B+"/eoir/vll/intdec/vol14/2260.pdf"),
    (14,"14 I&N Dec. 583","Hartunian",1974,"R.C.",B+"/eoir/vll/intdec/vol14/2263.pdf"),
    (14,"14 I&N Dec. 603","Patel",1974,"Act. Assoc. Comm'r",B+"/eoir/vll/intdec/vol14/2266.pdf"),
    (14,"14 I&N Dec. 620","Grewal",1974,"R.C.",B+"/eoir/vll/intdec/vol14/2269.pdf"),
    (14,"14 I&N Dec. 677","Gaglioti",1974,"R.C.",B+"/eoir/vll/intdec/vol14/2282.pdf"),
    (14,"14 I&N Dec. 681","Kukla",1974,"R.C.",B+"/eoir/vll/intdec/vol14/2284.pdf"),
    (14,"14 I&N Dec. 710","Valiyee",1974,"Special Inquiry Officer",B+"/eoir/vll/intdec/vol14/2292.pdf"),
    # ── Volume 13 ─────────────────────────────────────────────────────────────
    (13,"13 I&N Dec. 3","Ambe",1968,"D.D.",B+"/eoir/vll/intdec/vol13/1902.pdf"),
    (13,"13 I&N Dec. 8","Gowani",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1904.pdf"),
    (13,"13 I&N Dec. 13","Tagawa",1967,"D.D.",B+"/eoir/vll/intdec/vol13/1906.pdf"),
    (13,"13 I&N Dec. 16","Kim",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1907.pdf"),
    (13,"13 I&N Dec. 23","General Dynamics Corp.",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1909.pdf"),
    (13,"13 I&N Dec. 33","Vicedo",1968,"D.D.",B+"/eoir/vll/intdec/vol13/1912.pdf"),
    (13,"13 I&N Dec. 35","Ling",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1913.pdf"),
    (13,"13 I&N Dec. 61","Cruz",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1920.pdf"),
    (13,"13 I&N Dec. 75","Yau",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1924.pdf"),
    (13,"13 I&N Dec. 79","Baez-Ayala",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1925.pdf"),
    (13,"13 I&N Dec. 103","Bunag",1967,"D.D.",B+"/eoir/vll/intdec/vol13/1930.pdf"),
    (13,"13 I&N Dec. 106","Llagan",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1931.pdf"),
    (13,"13 I&N Dec. 110","Rajagopalamenon",1968,"D.D.",B+"/eoir/vll/intdec/vol13/1932.pdf"),
    (13,"13 I&N Dec. 113","Patel",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1933.pdf"),
    (13,"13 I&N Dec. 116","Diaz-Pou",1969,"D.D.",B+"/eoir/vll/intdec/vol13/1934.pdf"),
    (13,"13 I&N Dec. 118","Huckenbeck",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1935.pdf"),
    (13,"13 I&N Dec. 122","Chu",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1936.pdf"),
    (13,"13 I&N Dec. 125","Masters",1969,"D.D.",B+"/eoir/vll/intdec/vol13/1937.pdf"),
    (13,"13 I&N Dec. 166","Martin-Arencibia",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1946.pdf"),
    (13,"13 I&N Dec. 188","Lai",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1953.pdf"),
    (13,"13 I&N Dec. 203","Yaakov",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1957.pdf"),
    (13,"13 I&N Dec. 206","Coffman",1969,"Dep. Assoc. Com'r",B+"/eoir/vll/intdec/vol13/1958.pdf"),
    (13,"13 I&N Dec. 209","Amin",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1959.pdf"),
    (13,"13 I&N Dec. 249","Savetamal",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1969.pdf"),
    (13,"13 I&N Dec. 273","De Perio",1969,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol13/1975.pdf"),
    (13,"13 I&N Dec. 277","Ibarra",1968,"Act. Reg'l Comm'r",B+"/eoir/vll/intdec/vol13/1976.pdf"),
    (13,"13 I&N Dec. 280","Retodo",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1977.pdf"),
    (13,"13 I&N Dec. 286","Retino",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1979.pdf"),
    (13,"13 I&N Dec. 290","Zang",1969,"Act. D.D.",B+"/eoir/vll/intdec/vol13/1980.pdf"),
    (13,"13 I&N Dec. 314","Prabkahar",1969,"D.D.",B+"/eoir/vll/intdec/vol13/1985.pdf"),
    (13,"13 I&N Dec. 316","Kim",1968,"R.C.",B+"/eoir/vll/intdec/vol13/1986.pdf"),
    (13,"13 I&N Dec. 322","Gross",1969,"R.C.",B+"/eoir/vll/intdec/vol13/1988.pdf"),
    (13,"13 I&N Dec. 334","Penaherrera",1969,"D.D.",B+"/eoir/vll/intdec/vol13/1991.pdf"),
    (13,"13 I&N Dec. 340","De Vera",1969,"D.D.",B+"/eoir/vll/intdec/vol13/1993.pdf"),
    (13,"13 I&N Dec. 379","Lejman",1969,"R.C.",B+"/eoir/vll/intdec/vol13/2003.pdf"),
    (13,"13 I&N Dec. 383","Wong",1969,"R.C.",B+"/eoir/vll/intdec/vol13/2004.pdf"),
    (13,"13 I&N Dec. 393","Agbulos",1969,"D.D.",B+"/eoir/vll/intdec/vol13/2007.pdf"),
    (13,"13 I&N Dec. 406","Reyes",1969,"D.D.",B+"/eoir/vll/intdec/vol13/2009.pdf"),
    (13,"13 I&N Dec. 439","Singh",1969,"BIA",B+"/eoir/vll/intdec/vol13/2017.pdf"),
    (13,"13 I&N Dec. 470","Gupta",1970,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol13/2022.pdf"),
    (13,"13 I&N Dec. 480","Milian",1970,"Act. R.C.",B+"/eoir/vll/intdec/vol13/2023.pdf"),
    (13,"13 I&N Dec. 506","Medina",1970,"R.C.",B+"/eoir/vll/intdec/vol13/2030.pdf"),
    (13,"13 I&N Dec. 540","Harrison",1970,"D.D.",B+"/eoir/vll/intdec/vol13/2038.pdf"),
    (13,"13 I&N Dec. 555","The Stuyvesant Insurance Co.",1970,"Act. R.C.",B+"/eoir/vll/intdec/vol13/2041.pdf"),
    (13,"13 I&N Dec. 563","Don Donaldson's Key Bail Svc.",1970,"Act. R.C.",B+"/eoir/vll/intdec/vol13/2043.pdf"),
    (13,"13 I&N Dec. 581","Panganiban",1970,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol13/2049.pdf"),
    (13,"13 I&N Dec. 601","Bocris",1970,"R.C.",B+"/eoir/vll/intdec/vol13/2053.pdf"),
    (13,"13 I&N Dec. 611","Azevedo",1970,"R.C.",B+"/eoir/vll/intdec/vol13/2056.pdf"),
    (13,"13 I&N Dec. 618","Raulin",1970,"R.C.",B+"/eoir/vll/intdec/vol13/2059.pdf"),
    (13,"13 I&N Dec. 626","Zedkova",1970,"R.C.",B+"/eoir/vll/intdec/vol13/2062.pdf"),
    (13,"13 I&N Dec. 647","Schick",1970,"R.C.",B+"/eoir/vll/intdec/vol13/2068.pdf"),
    (13,"13 I&N Dec. 654","Villancourt",1970,"R.C.",B+"/eoir/vll/intdec/vol13/2070.pdf"),
    (13,"13 I&N Dec. 668","Mapili",1970,"R.C.",B+"/eoir/vll/intdec/vol13/2074.pdf"),
    (13,"13 I&N Dec. 675","The",1971,"R.C.",B+"/eoir/vll/intdec/vol13/2076.pdf"),
    (13,"13 I&N Dec. 705","Manjoukis",1971,"D.D.",B+"/eoir/vll/intdec/vol13/2084.pdf"),
    (13,"13 I&N Dec. 733","Villanueva",1971,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol13/2090.pdf"),
    (13,"13 I&N Dec. 805","Iregbulem",1971,"R.C.",B+"/eoir/vll/intdec/vol13/2108.pdf"),
    (13,"13 I&N Dec. 816","Leblanc",1971,"R.C.",B+"/eoir/vll/intdec/vol13/2110.pdf"),
    (13,"13 I&N Dec. 827","Athanasopoulos",1971,"BIA",B+"/eoir/vll/intdec/vol13/2113.pdf"),
    # ── Volume 12 ─────────────────────────────────────────────────────────────
    (12,"12 I&N Dec. 15","Rabbani",1966,"D.D.",B+"/eoir/vll/intdec/vol12/1679.pdf"),
    (12,"12 I&N Dec. 17","Bienkowski",1966,"D.D.",B+"/eoir/vll/intdec/vol12/1680.pdf"),
    (12,"12 I&N Dec. 20","Saini",1966,"D.D.",B+"/eoir/vll/intdec/vol12/1681.pdf"),
    (12,"12 I&N Dec. 36","Sun",1966,"R.C.",B+"/eoir/vll/intdec/vol12/1685.pdf"),
    (12,"12 I&N Dec. 40","Frisch",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1686.pdf"),
    (12,"12 I&N Dec. 54","Izdebska",1966,"R.C.",B+"/eoir/vll/intdec/vol12/1690.pdf"),
    (12,"12 I&N Dec. 56","Riva",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1691.pdf"),
    (12,"12 I&N Dec. 66","Palanky",1966,"R.C.",B+"/eoir/vll/intdec/vol12/1693.pdf"),
    (12,"12 I&N Dec. 81","Chai",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1698.pdf"),
    (12,"12 I&N Dec. 117","Moy",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1707.pdf"),
    (12,"12 I&N Dec. 124","Lalian",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1709.pdf"),
    (12,"12 I&N Dec. 143","Benguria Y Rodriguez",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1713.pdf"),
    (12,"12 I&N Dec. 146","Che",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1714.pdf"),
    (12,"12 I&N Dec. 148","Ho",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1715.pdf"),
    (12,"12 I&N Dec. 151","Mostafa",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1716.pdf"),
    (12,"12 I&N Dec. 153","Doultsinos",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1717.pdf"),
    (12,"12 I&N Dec. 178","Hung",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1722.pdf"),
    (12,"12 I&N Dec. 201","Adamska",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1727.pdf"),
    (12,"12 I&N Dec. 247","Guerrero",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1738.pdf"),
    (12,"12 I&N Dec. 261","Imondi and Costantini",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1742.pdf"),
    (12,"12 I&N Dec. 291","Menendez",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1748.pdf"),
    (12,"12 I&N Dec. 308","Fleuti",1965,"BIA",B+"/eoir/vll/intdec/vol12/1754.pdf"),
    (12,"12 I&N Dec. 312","Browne",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1755.pdf"),
    (12,"12 I&N Dec. 348","Stout",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1764.pdf"),
    (12,"12 I&N Dec. 355","Marchena",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1767.pdf"),
    (12,"12 I&N Dec. 369","Bellido",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1769.pdf"),
    (12,"12 I&N Dec. 380","Becher",1967,"A.G.",B+"/eoir/vll/intdec/vol12/1771.pdf"),
    (12,"12 I&N Dec. 389","International Transportation Corp.",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1772.pdf"),
    (12,"12 I&N Dec. 392","Shirinian",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1773.pdf"),
    (12,"12 I&N Dec. 396","Sanabria",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1774.pdf"),
    (12,"12 I&N Dec. 399","Anderson",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1775.pdf"),
    (12,"12 I&N Dec. 402","Vittore",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1776.pdf"),
    (12,"12 I&N Dec. 411","Ng",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1780.pdf"),
    (12,"12 I&N Dec. 413","Din",1967,"Act. R.C.",B+"/eoir/vll/intdec/vol12/1781.pdf"),
    (12,"12 I&N Dec. 416","Sakellarides",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1782.pdf"),
    (12,"12 I&N Dec. 418","Gutierrez",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1783.pdf"),
    (12,"12 I&N Dec. 432","Mesa",1967,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol12/1788.pdf"),
    (12,"12 I&N Dec. 446","Unnisa",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1791.pdf"),
    (12,"12 I&N Dec. 449","University of Michigan",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1792.pdf"),
    (12,"12 I&N Dec. 459","Wu",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1795.pdf"),
    (12,"12 I&N Dec. 482","Blanco",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1800.pdf"),
    (12,"12 I&N Dec. 487","Quan",1967,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol12/1802.pdf"),
    (12,"12 I&N Dec. 492","Bozdogan",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1804.pdf"),
    (12,"12 I&N Dec. 495","Fuji",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1805.pdf"),
    (12,"12 I&N Dec. 498","Ahmed",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1806.pdf"),
    (12,"12 I&N Dec. 501","Hung",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1807.pdf"),
    (12,"12 I&N Dec. 503","Pableo",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1808.pdf"),
    (12,"12 I&N Dec. 522","Wellhoffer",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1813.pdf"),
    (12,"12 I&N Dec. 526","Pasarikovski",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1814.pdf"),
    (12,"12 I&N Dec. 535","Sun",1966,"D.D.",B+"/eoir/vll/intdec/vol12/1816.pdf"),
    (12,"12 I&N Dec. 537","Pizarro",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1817.pdf"),
    (12,"12 I&N Dec. 542","Samuel",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1818.pdf"),
    (12,"12 I&N Dec. 549","Rodriguez",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1821.pdf"),
    (12,"12 I&N Dec. 571","Kowarski",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1826.pdf"),
    (12,"12 I&N Dec. 591","Hyatt",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1829.pdf"),
    (12,"12 I&N Dec. 612","Sonegawa",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1835.pdf"),
    (12,"12 I&N Dec. 649","Arjani",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1843.pdf"),
    (12,"12 I&N Dec. 653","Soares",1967,"BIA",B+"/eoir/vll/intdec/vol12/1844.pdf"),
    (12,"12 I&N Dec. 680","Maher",1968,"R.C.",B+"/eoir/vll/intdec/vol12/1849.pdf"),
    (12,"12 I&N Dec. 688","Martinez-Monteagudo",1968,"R.C.",B+"/eoir/vll/intdec/vol12/1851.pdf"),
    (12,"12 I&N Dec. 701","Perez",1968,"D.D.",B+"/eoir/vll/intdec/vol12/1856.pdf"),
    (12,"12 I&N Dec. 731","Romano",1968,"R.C.",B+"/eoir/vll/intdec/vol12/1862.pdf"),
    (12,"12 I&N Dec. 754","Buenaventura",1967,"D.D.",B+"/eoir/vll/intdec/vol12/1869.pdf"),
    (12,"12 I&N Dec. 756","Nassiri",1968,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol12/1870.pdf"),
    (12,"12 I&N Dec. 758","Kim",1967,"R.C.",B+"/eoir/vll/intdec/vol12/1871.pdf"),
    (12,"12 I&N Dec. 762","Wu",1968,"D.D.",B+"/eoir/vll/intdec/vol12/1872.pdf"),
    (12,"12 I&N Dec. 765","Bun",1968,"R.C.",B+"/eoir/vll/intdec/vol12/1873.pdf"),
    (12,"12 I&N Dec. 768","Bronx Municipal Hospital Center",1968,"R.C.",B+"/eoir/vll/intdec/vol12/1874.pdf"),
    (12,"12 I&N Dec. 772","Smith",1968,"D.D.",B+"/eoir/vll/intdec/vol12/1875.pdf"),
    (12,"12 I&N Dec. 785","Ancheta",1968,"R.C.",B+"/eoir/vll/intdec/vol12/1879.pdf"),
    (12,"12 I&N Dec. 788","Piedra",1968,"R.C.",B+"/eoir/vll/intdec/vol12/1880.pdf"),
    (12,"12 I&N Dec. 793","Chong",1968,"D.D.",B+"/eoir/vll/intdec/vol12/1882.pdf"),
    (12,"12 I&N Dec. 795","Continental Casualty Company",1968,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol12/1883.pdf"),
    (12,"12 I&N Dec. 798","Hanna",1968,"D.D.",B+"/eoir/vll/intdec/vol12/1884.pdf"),
    (12,"12 I&N Dec. 800","Sun",1968,"R.C.",B+"/eoir/vll/intdec/vol12/1885.pdf"),
    (12,"12 I&N Dec. 830","Yaldo",1968,"BIA",B+"/eoir/vll/intdec/vol12/1893.pdf"),
    (12,"12 I&N Dec. 838","University of California",1968,"D.D.",B+"/eoir/vll/intdec/vol12/1895.pdf"),
    (12,"12 I&N Dec. 840","Sloan",1968,"A.G.",B+"/eoir/vll/intdec/vol12/1896.pdf"),
    (12,"12 I&N Dec. 864","Kawasaki",1968,"Dep. Assoc. Comm'r",B+"/eoir/vll/intdec/vol12/1899.pdf"),

    # ── Volume 11 (confirmed from DOJ page) ──────────────────────────────────
    (11,"11 I&N Dec. 1",   "Petuolglu",         1964,"D.D.",  B+"/eoir/vll/intdec/vol11/1418.pdf"),
    (11,"11 I&N Dec. 3",   "Toth",               1964,"R.C.",  B+"/eoir/vll/intdec/vol11/1419.pdf"),
    (11,"11 I&N Dec. 9",   "Landolfi",           1965,"R.C.",  B+"/eoir/vll/intdec/vol11/1421.pdf"),
    (11,"11 I&N Dec. 21",  "Vaccarello",         1964,"OIC",   B+"/eoir/vll/intdec/vol11/1424.pdf"),
    (11,"11 I&N Dec. 25",  "Young",              1964,"D.D.",  B+"/eoir/vll/intdec/vol11/1425.pdf"),
    (11,"11 I&N Dec. 32",  "Madalla",            1964,"D.D.",  B+"/eoir/vll/intdec/vol11/1427.pdf"),
    (11,"11 I&N Dec. 51",  "Farley",             1965,"D.D.",  B+"/eoir/vll/intdec/vol11/1432.pdf"),
    (11,"11 I&N Dec. 63",  "Kraus Periodicals Inc.", 1964,"R.C.", B+"/eoir/vll/intdec/vol11/1434.pdf"),
    (11,"11 I&N Dec. 65",  "Rexer",              1965,"R.C.",  B+"/eoir/vll/intdec/vol11/1435.pdf"),
    (11,"11 I&N Dec. 67",  "Ormos",              1965,"D.D.",  B+"/eoir/vll/intdec/vol11/1436.pdf"),
    (11,"11 I&N Dec. 69",  "Kim",                1964,"R.C.",  B+"/eoir/vll/intdec/vol11/1437.pdf"),
    (11,"11 I&N Dec. 71",  "Colletti",           1965,"Asst. Comm'r", B+"/eoir/vll/intdec/vol11/1438.pdf"),
    (11,"11 I&N Dec. 76",  "Psalidas",           1965,"BIA",   B+"/eoir/vll/intdec/vol11/1440.pdf"),
    (11,"11 I&N Dec. 96",  "Lee",                1965,"D.D.",  B+"/eoir/vll/intdec/vol11/1441.pdf"),
    (11,"11 I&N Dec. 99",  "A-",                 1965,"D.D.",  B+"/eoir/vll/intdec/vol11/1442.pdf"),
    (11,"11 I&N Dec. 121", "De Los Santos",      1965,"D.D.",  B+"/eoir/vll/intdec/vol11/1447.pdf"),
    (11,"11 I&N Dec. 123", "Di Pietra",          1965,"D.D.",  B+"/eoir/vll/intdec/vol11/1448.pdf"),
    # NOTE: Volumes 8-10 were on the DOJ page but URLs could not be confirmed.
    # Add them here once verified from the live page or a browser session.
]


# ── Schema ────────────────────────────────────────────────────────────────────
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS precedent_decisions (
    id            SERIAL PRIMARY KEY,
    volume        INTEGER,
    citation      TEXT NOT NULL,
    party_name    TEXT NOT NULL,
    year          INTEGER,
    body          TEXT,
    pdf_url       TEXT NOT NULL,
    pdf_path      TEXT,
    full_text     TEXT NOT NULL DEFAULT '',
    search_vector TSVECTOR,
    ingested_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prec_citation ON precedent_decisions(citation);
CREATE INDEX IF NOT EXISTS idx_prec_search ON precedent_decisions USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_prec_volume ON precedent_decisions(volume);

CREATE OR REPLACE FUNCTION update_prec_search() RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.party_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.citation, '')),   'B') ||
    setweight(to_tsvector('english', coalesce(NEW.full_text, '')),  'D');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prec_search ON precedent_decisions;
CREATE TRIGGER trg_prec_search
  BEFORE INSERT OR UPDATE ON precedent_decisions
  FOR EACH ROW EXECUTE FUNCTION update_prec_search();
"""

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


async def download_and_extract(client: httpx.AsyncClient, entry: tuple) -> dict:
    vol, citation, party, year, body, url = entry
    safe  = re.sub(r"[^\w\-]", "_", citation)
    fpath = os.path.join(SAVE_DIR, safe + ".pdf")

    if not os.path.exists(fpath):
        try:
            resp = await client.get(url, follow_redirects=True, timeout=30)
            resp.raise_for_status()
            with open(fpath, "wb") as f:
                f.write(resp.content)
            await asyncio.sleep(0.3)
        except Exception as e:
            log.warning(f"  Download FAILED {citation}: {e}")
            return dict(volume=vol, citation=citation, party_name=party,
                        year=year, body=body, pdf_url=url,
                        pdf_path=None, full_text="")
    else:
        log.info(f"  Cached: {citation}")

    try:
        with pdfplumber.open(fpath) as pdf:
            text = "\n\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:
        log.warning(f"  Extract FAILED {citation}: {e}")
        text = ""

    return dict(volume=vol, citation=citation, party_name=party,
                year=year, body=body, pdf_url=url,
                pdf_path=fpath, full_text=text)


async def main():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute(CREATE_SQL)
    log.info(f"Schema ready. Processing {len(DECISIONS)} decisions.")

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        for i, entry in enumerate(DECISIONS):
            citation = entry[1]
            log.info(f"[{i+1}/{len(DECISIONS)}] {citation} — {entry[2]}")
            d = await download_and_extract(client, entry)

            await conn.execute("""
                INSERT INTO precedent_decisions
                  (volume, citation, party_name, year, body, pdf_url, pdf_path, full_text)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (citation) DO UPDATE SET
                  full_text  = EXCLUDED.full_text,
                  pdf_path   = EXCLUDED.pdf_path,
                  party_name = EXCLUDED.party_name
            """, d["volume"], d["citation"], d["party_name"],
                 d["year"], d["body"], d["pdf_url"],
                 d["pdf_path"], d["full_text"])

    total = await conn.fetchval("SELECT COUNT(*) FROM precedent_decisions")
    with_text = await conn.fetchval(
        "SELECT COUNT(*) FROM precedent_decisions WHERE full_text != ''")
    log.info(f"\nDone. {total} decisions in DB, {with_text} with text.")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
