"""
Stage 1 of the Trip World build pipeline.

Reads raw ${STD_2018_PATH}, applies
metro_mapping_clean.json to the venue_city QID (producing region_id),
then enforces:

  (a) POI popularity:  drop POIs with < 2 visits in the *consolidated* stream
  (b) Region density:  drop regions with < 100 distinct POIs after (a)

Output: _intermediate/checkins_consolidated.parquet
        Columns: trail_id, user_id, venue_id, venue_category, venue_schema,
                 venue_city_qid, venue_country_qid, ts, region_id
        (Same schema as the precursor build/checkins_filtered.parquet so
         downstream stages can reuse the same query patterns.)
"""
import duckdb, json, os, time
from pathlib import Path

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
RAW = os.environ["STD_2018_PATH"]
MAP = ROOT / "metro_mapping_clean.json"
OUT = ROOT / "_intermediate" / "checkins_consolidated.parquet"
OUT.parent.mkdir(parents=True, exist_ok=True)

t0 = time.time()
def step(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

# Load metro map
mm = json.load(MAP.open())["metro_map"]
step(f"loaded metro_map ({len(mm):,} entries, {sum(1 for k,v in mm.items() if k!=v):,} non-identity)")

# Materialise as a small parquet (DuckDB joins efficiently against parquet)
import pyarrow as pa, pyarrow.parquet as pq
import os
mm_tbl = pa.Table.from_pylist([{"raw": k, "metro": v} for k, v in mm.items()])
mm_path = ROOT / "_intermediate" / "metro_map.parquet"
pq.write_table(mm_tbl, mm_path, compression="zstd")
step(f"wrote {mm_path}")

con = duckdb.connect()
con.execute("PRAGMA threads=32")
con.execute("SET memory_limit='48GB'")
con.execute("SET preserve_insertion_order=false")
con.execute(f"SET temp_directory='{os.environ.get('DUCKDB_TMP_DIR', '/tmp/duckdb_trip_world')}'")

# ---------------- Step A: load raw stream + apply metro_map -------------------
step("loading raw std_2018.csv into DuckDB and applying metro_map ...")
con.execute(f"""
CREATE TABLE raw AS
SELECT
  trail_id, user_id, venue_id, venue_category, venue_schema,
  venue_city  AS venue_city_qid,
  venue_country AS venue_country_qid,
  TRY_CAST(timestamp AS TIMESTAMPTZ) AS ts
FROM read_csv_auto('{RAW}', sample_size=-1)
""")
n_raw = con.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
n_users = con.execute("SELECT COUNT(DISTINCT user_id) FROM raw").fetchone()[0]
n_pois  = con.execute("SELECT COUNT(DISTINCT venue_id) FROM raw").fetchone()[0]
n_cities= con.execute("SELECT COUNT(DISTINCT venue_city_qid) FROM raw").fetchone()[0]
step(f"  raw: {n_raw:,} rows, {n_users:,} users, {n_pois:,} POIs, {n_cities:,} venue_city QIDs")

# Strip "wd:" prefix to match metro_map keys, then left-join.
con.execute(f"""
CREATE TABLE consolidated AS
SELECT
  raw.trail_id, raw.user_id, raw.venue_id, raw.venue_category, raw.venue_schema,
  raw.venue_city_qid, raw.venue_country_qid, raw.ts,
  COALESCE(mm.metro, REPLACE(raw.venue_city_qid, 'wd:', '')) AS region_id
FROM raw
LEFT JOIN read_parquet('{mm_path}') mm
  ON mm.raw = REPLACE(raw.venue_city_qid, 'wd:', '')
""")
n_dist_regions = con.execute("SELECT COUNT(DISTINCT region_id) FROM consolidated").fetchone()[0]
step(f"  consolidated: {n_dist_regions:,} distinct region_id values")

# ---------------- Step B: POI popularity filter -------------------------------
step("applying POI popularity filter (visits per POI >= 2) ...")
con.execute("""
CREATE TABLE poi_popular AS
SELECT venue_id FROM consolidated
GROUP BY venue_id HAVING COUNT(*) >= 2
""")
n_pop_pois = con.execute("SELECT COUNT(*) FROM poi_popular").fetchone()[0]
step(f"  popular POIs: {n_pop_pois:,} (kept) of {n_pois:,}")

con.execute("""
CREATE TABLE filtered_pop AS
SELECT c.* FROM consolidated c JOIN poi_popular p USING (venue_id)
""")
n_pop_rows = con.execute("SELECT COUNT(*) FROM filtered_pop").fetchone()[0]
step(f"  rows after popularity filter: {n_pop_rows:,}")

# ---------------- Step C: region density filter -------------------------------
step("applying region density filter (>= 100 distinct POIs per region) ...")
con.execute("""
CREATE TABLE region_dense AS
SELECT region_id FROM (
  SELECT region_id, COUNT(DISTINCT venue_id) AS n_pois
  FROM filtered_pop GROUP BY region_id
) WHERE n_pois >= 100
""")
n_dense_regions = con.execute("SELECT COUNT(*) FROM region_dense").fetchone()[0]
step(f"  dense regions: {n_dense_regions:,} (kept)")

con.execute(f"""
COPY (
  SELECT f.* FROM filtered_pop f JOIN region_dense d USING (region_id)
) TO '{OUT}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 50000)
""")
n_final = con.execute(f"SELECT COUNT(*) FROM read_parquet('{OUT}')").fetchone()[0]
n_final_users = con.execute(f"SELECT COUNT(DISTINCT user_id) FROM read_parquet('{OUT}')").fetchone()[0]
n_final_pois  = con.execute(f"SELECT COUNT(DISTINCT venue_id) FROM read_parquet('{OUT}')").fetchone()[0]
n_final_reg   = con.execute(f"SELECT COUNT(DISTINCT region_id) FROM read_parquet('{OUT}')").fetchone()[0]
sz = OUT.stat().st_size / 1e6

print()
print("=== Stage 1 output ===")
print(f"  file:           {OUT}  ({sz:.1f} MB)")
print(f"  rows:           {n_final:,}")
print(f"  users:          {n_final_users:,}")
print(f"  POIs:           {n_final_pois:,}")
print(f"  dense regions:  {n_final_reg:,}")
print(f"  total elapsed:  {time.time()-t0:.1f}s")
