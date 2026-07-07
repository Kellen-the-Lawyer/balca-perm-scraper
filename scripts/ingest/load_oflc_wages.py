import csv, psycopg2, psycopg2.extras, sys, os

DB_DSN = "postgresql://perm@127.0.0.1:5433/perm_decisions"
WAGE_YEAR = 2027
DATA_DIR = "/Users/Dad/Downloads/OFLC_Wages_2026-27"

def load_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

print("Loading Geography...", flush=True)
geo_raw = load_csv(f"{DATA_DIR}/Geography.csv")
geo = {}
for r in geo_raw:
    ac = r['Area'].strip()
    if ac not in geo:
        geo[ac] = {'area_name': r['AreaName'].strip(),
                   'state_ab':  r['StateAb'].strip(),
                   'state':     r['State'].strip(),
                   'counties':  []}
    county = r.get('CountyTownName','').strip()
    if county:
        geo[ac]['counties'].append(county)
print(f"  {len(geo)} areas, {sum(len(v['counties']) for v in geo.values())} county mappings", flush=True)

print("Loading SOC titles...", flush=True)
soc_titles = {r['soccode'].strip(): r['Title'].strip()
              for r in load_csv(f"{DATA_DIR}/oes_soc_occs.csv")}
print(f"  {len(soc_titles)} SOC titles", flush=True)

def clean(v):
    v = v.strip()
    return float(v) if v else None

def build_rows(export_path, ctype):
    print(f"Building {ctype.upper()} rows...", flush=True)
    raw = load_csv(export_path)
    print(f"  {len(raw):,} export rows", flush=True)
    rows = []
    missing_geo = set()
    for r in raw:
        ac   = r['Area'].strip()
        soc  = r['SocCode'].strip()
        try:
            glvl = int(r['GeoLvl'].strip())
        except (ValueError, KeyError):
            glvl = None
        label = r.get('Label','').strip() or None
        g = geo.get(ac)
        if not g:
            missing_geo.add(ac)
            area_name = state_ab = state = None
            counties = [None]
        else:
            area_name = g['area_name']
            state_ab  = g['state_ab']
            state     = g['state']
            counties  = g['counties'] or [None]
        title = soc_titles.get(soc)
        lvls  = (clean(r['Level1']), clean(r['Level2']),
                 clean(r['Level3']), clean(r['Level4']),
                 clean(r['Average']))
        for county in counties:
            rows.append((WAGE_YEAR, ac, area_name, state_ab, state, county,
                         soc, title, ctype, glvl, *lvls, label))
    if missing_geo:
        print(f"  WARNING: {len(missing_geo)} area codes not in Geography", flush=True)
    print(f"  {len(rows):,} rows after county fan-out", flush=True)
    return rows

INSERT_SQL = """
INSERT INTO current_oews_wages
  (wage_year, area_code, area_name, state_ab, state, county_name,
   soc_code, soc_title, collection_type, geo_level,
   level_i, level_ii, level_iii, level_iv, level_mean, label)
VALUES %s
"""

conn = psycopg2.connect(DB_DSN)
cur  = conn.cursor()

for path, ctype in [
    (f"{DATA_DIR}/ALC_Export.csv", "alc"),
    (f"{DATA_DIR}/EDC_Export.csv", "edc"),
]:
    rows = build_rows(path, ctype)
    print(f"Inserting {len(rows):,} {ctype.upper()} rows...", flush=True)
    psycopg2.extras.execute_values(cur, INSERT_SQL, rows, page_size=2000)
    conn.commit()
    print(f"  Done.", flush=True)

cur.execute("""
    SELECT collection_type,
           COUNT(*) AS rows,
           COUNT(DISTINCT soc_code) AS socs,
           COUNT(DISTINCT area_code) AS areas,
           COUNT(DISTINCT county_name) FILTER (WHERE county_name IS NOT NULL) AS counties,
           COUNT(DISTINCT state_ab) AS states
    FROM current_oews_wages
    GROUP BY collection_type ORDER BY collection_type
""")
print("\n=== Final counts ===")
for r in cur.fetchall():
    print(f"  {r[0].upper()}: {r[1]:,} rows | {r[2]} SOCs | {r[3]} areas | {r[4]} counties | {r[5]} states")

cur.execute("""
    SELECT soc_code, area_name, county_name, collection_type, level_i, level_ii, level_iii, level_iv
    FROM current_oews_wages
    WHERE soc_code='15-1252' AND area_code='19100'
    ORDER BY collection_type, county_name LIMIT 6
""")
print("\n=== Spot check: 15-1252 Dallas (area 19100) ===")
for r in cur.fetchall():
    print(" ", r)

cur.close(); conn.close()
print("\nAll done.", flush=True)
