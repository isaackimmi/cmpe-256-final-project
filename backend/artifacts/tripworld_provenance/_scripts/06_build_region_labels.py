"""
Stage 6: build $TRIP_WORLD_ROOT/region_labels.parquet

For every region_id that appears as r_h or r_o in the clean travel_behaviors,
emit one row with: region_id, city_name, country_qid, country_name.

The country is the dominant venue_country_qid among check-ins in that region
(matches the precursor logic).
"""
import duckdb, json, pyarrow as pa, pyarrow.parquet as pq, time
from pathlib import Path
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
INC  = ROOT / "_intermediate" / "checkins_consolidated.parquet"
TB   = ROOT / "travel_behaviors.parquet"
MAP  = ROOT / "metro_mapping_clean.json"
OUT  = ROOT / "region_labels.parquet"

t0 = time.time()
def step(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

labels = json.load(MAP.open())["labels"]
step(f"loaded {len(labels):,} labels from metro_mapping_clean.json")

con = duckdb.connect()
con.execute("PRAGMA threads=16")

# All distinct region IDs in benchmark
qids = set(r[0] for r in con.execute(f"""
  SELECT DISTINCT r_h FROM '{TB}'
  UNION
  SELECT DISTINCT r_o FROM '{TB}'
""").fetchall())
step(f"  {len(qids):,} distinct benchmark region IDs")

# Dominant country per region
con.execute(f"""
CREATE TABLE rc AS
SELECT region_id, venue_country_qid AS country_qid, COUNT(*) AS n
FROM '{INC}' GROUP BY 1, 2
""")
con.execute("""
CREATE TABLE rc_top AS
SELECT region_id, country_qid, n
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY region_id ORDER BY n DESC) AS rn
  FROM rc
) WHERE rn = 1
""")
country_map = {r[0]: r[1] for r in con.execute(
    "SELECT region_id, country_qid FROM rc_top").fetchall()}
step(f"  built country map for {len(country_map):,} regions")

rows = []
n_no_city = n_no_ctry = 0
for qid in sorted(qids):
    bare = qid.replace("wd:", "")
    city_name = labels.get(bare)
    if not city_name:
        n_no_city += 1
    cq = country_map.get(qid)
    cq_bare = cq.replace("wd:", "") if cq else None
    cn = labels.get(cq_bare) if cq_bare else None
    if not cn:
        n_no_ctry += 1
    rows.append({
        "region_id": qid,
        "city_name": city_name,
        "country_qid": f"wd:{cq_bare}" if cq_bare else None,
        "country_name": cn,
    })

tbl = pa.Table.from_pylist(rows)
pq.write_table(tbl, OUT, compression="zstd")
sz = OUT.stat().st_size / 1024
print()
print("=== Stage 6 output ===")
print(f"  file:                {OUT}  ({sz:.1f} KB)")
print(f"  rows:                {len(rows):,}")
print(f"  with city_name:      {len(rows) - n_no_city:,}  ({(len(rows)-n_no_city)/len(rows)*100:.1f}%)")
print(f"  with country_name:   {len(rows) - n_no_ctry:,}")
print(f"  total elapsed:       {time.time()-t0:.1f}s")
