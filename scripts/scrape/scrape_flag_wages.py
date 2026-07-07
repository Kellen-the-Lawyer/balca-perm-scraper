#!/usr/bin/env python3
"""
scrape_flag_wages.py — FLAG.DOL.GOV ALC prevailing wages → current_oews_wages
Run: nohup python3 scripts/scrape/scrape_flag_wages.py > /tmp/flag_wages.log 2>&1 &
"""

import http.cookiejar, json, sys, time, urllib.error, urllib.parse, urllib.request
import psycopg2, psycopg2.extras

BASE      = "https://flag.dol.gov"
YEAR      = 2027
AREA_TYPE = "county_town"
DELAY     = 0.15      # seconds between wage API calls
DB_DSN    = "postgresql://perm@127.0.0.1:5433/perm_decisions"
BATCH_SZ  = 500
MAX_RETRY = 5         # retries on transient errors

ALL_STATES = [
    "ALABAMA","ALASKA","AMERICAN SAMOA","ARIZONA","ARKANSAS","CALIFORNIA",
    "COLORADO","CONNECTICUT","DELAWARE","DISTRICT OF COLUMBIA","FLORIDA",
    "GEORGIA","GUAM","HAWAII","IDAHO","ILLINOIS","INDIANA","IOWA",
    "KANSAS","KENTUCKY","LOUISIANA","MAINE","MARYLAND","MASSACHUSETTS",
    "MICHIGAN","MINNESOTA","MISSISSIPPI","MISSOURI","MONTANA","NEBRASKA",
    "NEVADA","NEW HAMPSHIRE","NEW JERSEY","NEW MEXICO","NEW YORK",
    "NORTH CAROLINA","NORTH DAKOTA","OHIO","OKLAHOMA","OREGON",
    "PENNSYLVANIA","PUERTO RICO","RHODE ISLAND","SOUTH CAROLINA",
    "SOUTH DAKOTA","TENNESSEE","TEXAS","UTAH","VERMONT","VIRGIN ISLANDS",
    "VIRGINIA","WASHINGTON","WEST VIRGINIA","WISCONSIN","WYOMING",
]

HEADERS = {
    "Content-Type": "application/json",
    "Origin":       BASE,
    "Referer":      f"{BASE}/wage-data/wage-search",
    "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept":       "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def make_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        req = urllib.request.Request(
            f"{BASE}/wage-data/wage-search",
            headers={"User-Agent": HEADERS["User-Agent"],
                     "Accept": "text/html,application/xhtml+xml",
                     "Accept-Language": "en-US,en;q=0.9"})
        opener.open(req, timeout=15)
    except Exception:
        pass
    return opener


def _request(opener, url: str, payload: dict | None = None,
             method: str | None = None) -> dict:
    """POST if payload given, else GET. Retries with backoff on 429/5xx."""
    for attempt in range(MAX_RETRY):
        try:
            if payload is not None:
                req = urllib.request.Request(
                    url, data=json.dumps(payload).encode(),
                    headers=HEADERS, method=method or "POST")
            else:
                req = urllib.request.Request(url, headers=HEADERS,
                                              method=method or "GET")
            with opener.open(req, timeout=25) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                raise   # no data — caller handles
            if e.code in (429, 500, 502, 503, 504, 403):
                wait = 2 ** attempt * 3
                print(f"  HTTP {e.code}, retry {attempt+1}/{MAX_RETRY} "
                      f"in {wait}s", flush=True)
                # Refresh opener on 403 to get fresh session
                if e.code == 403:
                    opener.__init__(
                        urllib.request.HTTPCookieProcessor(
                            http.cookiejar.CookieJar()))
                    try:
                        req0 = urllib.request.Request(
                            f"{BASE}/wage-data/wage-search",
                            headers={"User-Agent": HEADERS["User-Agent"],
                                     "Accept": "text/html"})
                        opener.open(req0, timeout=15)
                    except Exception:
                        pass
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt == MAX_RETRY - 1:
                raise
            wait = 2 ** attempt * 2
            print(f"  error {e}, retry {attempt+1}/{MAX_RETRY} in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"All {MAX_RETRY} retries exhausted for {url}")


def fetch_all_socs(opener) -> list[dict]:
    url = f"{BASE}/foreign-labor/soc/docs/suggest?api-version=2020-06-30"
    socs: dict[str, dict] = {}
    prefixes = ["11","13","15","17","19","21","23","25","27",
                "29","31","33","35","37","39","41","43","45",
                "47","49","51","53"]
    for prefix in prefixes:
        payload = {"search": prefix, "top": 100, "select": "*",
                   "suggesterName": "socSuggester",
                   "searchFields": "title, code", "orderby": "code, title"}
        resp = _request(opener, url, payload)
        for h in resp.get("value", []):
            code = h.get("code", "")
            if code and h.get("isAlc"):
                socs[code] = h
    return sorted(socs.values(), key=lambda x: x["code"])


def fetch_county_options(opener, state: str) -> list[dict]:
    encoded = urllib.parse.quote(state)
    url = f"{BASE}/flag/api/getAreaOptions?state={encoded}&year={YEAR}"
    return _request(opener, url).get("countyOptions", [])


def fetch_wage(opener, soc_code: str, area_code: int) -> dict | None:
    payload = {"collectionType": "alc", "year": str(YEAR), "socCode": soc_code,
               "area": area_code, "areaType": AREA_TYPE, "rdFlag": "BOTH"}
    try:
        return _request(opener, f"{BASE}/recaptcha/wageSearch", payload)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None
        raise


def flatten_rates(resp: dict, soc: dict, state: str,
                  area_code: int, area_label: str) -> list[tuple]:
    base = (YEAR, state, area_code, area_label,
            soc["code"], soc.get("title"), "alc")
    rows = []
    if "rates" in resp:
        for level, v in resp["rates"].items():
            rows.append((*base, None, level, v.get("hour"), v.get("year")))
    for rd_cat in ("R&D", "Non-R&D"):
        if rd_cat in resp:
            for level, v in resp[rd_cat].items():
                rows.append((*base, rd_cat, level, v.get("hour"), v.get("year")))
    return rows


INSERT_SQL = """
INSERT INTO current_oews_wages
  (wage_year, state, area_code, area_label, soc_code, soc_title,
   collection_type, rd_category, wage_level, hourly, yearly)
VALUES %s
ON CONFLICT DO NOTHING
"""


def main():
    opener = make_opener()

    print("Fetching SOC catalogue...", flush=True)
    socs = fetch_all_socs(opener)
    print(f"  {len(socs)} ALC SOCs", flush=True)

    conn = psycopg2.connect(DB_DSN)
    cur  = conn.cursor()
    pending: list[tuple] = []
    total_rows = total_calls = total_errors = 0

    def flush(force=False):
        nonlocal total_rows, pending
        if pending and (force or len(pending) >= BATCH_SZ):
            psycopg2.extras.execute_values(cur, INSERT_SQL, pending,
                                           page_size=BATCH_SZ)
            conn.commit()
            total_rows += len(pending)
            pending = []

    for state in ALL_STATES:
        print(f"\n[{state}]", flush=True)
        opener = make_opener()   # fresh session per state
        time.sleep(1)            # brief pause between states

        try:
            county_opts = fetch_county_options(opener, state)
        except Exception as e:
            print(f"  area fetch error: {e}", flush=True)
            continue
        if not county_opts:
            print(f"  no counties, skipping", flush=True)
            continue

        area_by_code: dict[int, str] = {}
        for opt in county_opts:
            if opt["value"] not in area_by_code:
                area_by_code[opt["value"]] = opt["label"]

        print(f"  {len(county_opts)} counties, {len(area_by_code)} unique areas",
              flush=True)

        for i, soc in enumerate(socs):
            area_cache: dict[int, list[tuple]] = {}

            for area_code, area_label in area_by_code.items():
                resp = fetch_wage(opener, soc["code"], area_code)
                total_calls += 1
                time.sleep(DELAY)

                if resp is None:
                    area_cache[area_code] = []
                    total_errors += 1
                    continue

                rows = flatten_rates(resp, soc, state, area_code, area_label)
                area_cache[area_code] = rows
                pending.extend(rows)
                flush()

            # Fan out: counties sharing an area code get the same wages
            for opt in county_opts:
                ac, label = opt["value"], opt["label"]
                cached = area_cache.get(ac, [])
                if cached and cached[0][3] != label:
                    for row in cached:
                        pending.append((*row[:3], label, *row[4:]))
                    flush()

            flush(force=True)

            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(socs)} SOCs | {total_rows} rows | "
                      f"{total_calls} calls | {total_errors} no-data", flush=True)

        print(f"  [{state}] done — {total_rows} total rows so far", flush=True)

    flush(force=True)
    cur.close()
    conn.close()
    print(f"\nDone. {total_rows} rows | {total_calls} API calls | "
          f"{total_errors} no-data", flush=True)


if __name__ == "__main__":
    main()
