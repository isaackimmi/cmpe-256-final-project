"""
Stage 5: build $TRIP_WORLD_ROOT/pois.parquet

For every POI that survives the Trip World build pipeline (i.e. appears in
checkins_consolidated.parquet, which already enforces popularity >= 2 AND
region density >= 100), inherit per-POI metadata (FSQ-OS + Google + review
counts) from a precursor build at $PRECURSOR_BUILD_ROOT/pois.parquet, and
re-map the `locality` column with the Trip World metro map.

The $PRECURSOR_BUILD_ROOT env var should point at a previous output of this
same pipeline whose POI metadata we want to extend; if you are bootstrapping
from scratch you can either skip this stage or supply an empty parquet — POIs
not present in the precursor will simply carry NULLs for the inherited
FSQ-OS / Google / review-count fields.
"""
import duckdb, json, time
from pathlib import Path
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
INC  = ROOT / "_intermediate" / "checkins_consolidated.parquet"
V1_POIS = str(Path(os.environ["PRECURSOR_BUILD_ROOT"]) / "pois.parquet")
MM   = ROOT / "_intermediate" / "metro_map.parquet"
OUT  = ROOT / "pois.parquet"

t0 = time.time()
def step(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

con = duckdb.connect()
con.execute("PRAGMA threads=32")
con.execute("SET memory_limit='32GB'")
con.execute(f"SET temp_directory='{os.environ.get('DUCKDB_TMP_DIR', '/tmp/duckdb_trip_world')}'")

step("collecting per-POI visit counts and locality from clean checkins ...")
con.execute(f"""
CREATE TABLE poi_facts AS
SELECT
  venue_id AS fsq_place_id,
  ANY_VALUE(region_id) AS locality,        -- region_id == metro QID under clean map
  ANY_VALUE(venue_category) AS venue_category,
  ANY_VALUE(venue_schema) AS venue_schema,
  COUNT(*) AS n_checkins,
  COUNT(DISTINCT user_id) AS n_users_visited
FROM '{INC}' GROUP BY 1
""")
n_pois = con.execute("SELECT COUNT(*) FROM poi_facts").fetchone()[0]
step(f"  {n_pois:,} surviving POIs")

step("loading precursor pois.parquet for metadata inheritance ...")
con.execute(f"CREATE TABLE prev AS SELECT * FROM '{V1_POIS}'")

step("writing clean pois.parquet (left join on precursor metadata, locality from clean) ...")
con.execute(f"""
COPY (
  SELECT
    pf.fsq_place_id,
    pf.locality,
    pf.venue_category,
    pf.venue_schema,
    pf.n_checkins::BIGINT AS n_checkins,
    pf.n_users_visited::BIGINT AS n_users_visited,
    p.google_cid, p.google_name, p.google_full_address, p.google_address,
    p.google_website, p.google_rating, p.google_num_reviews, p.google_categories,
    p.google_place_id, p.google_gmaps_url,
    COALESCE(p.google_meta_source, 'none') AS google_meta_source,
    COALESCE(p.has_google_metadata, FALSE) AS has_google_metadata,
    COALESCE(p.n_reviews, 0)::BIGINT AS n_reviews,
    COALESCE(p.n_reviews_with_text, 0)::BIGINT AS n_reviews_with_text,
    p.review_source,
    COALESCE(p.has_reviews, FALSE) AS has_reviews
  FROM poi_facts pf
  LEFT JOIN prev p USING (fsq_place_id)
) TO '{OUT}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 200000)
""")

# Verify
r = con.execute(f"""
SELECT COUNT(*),
       SUM(CASE WHEN has_google_metadata THEN 1 ELSE 0 END),
       SUM(CASE WHEN has_reviews THEN 1 ELSE 0 END),
       SUM(n_reviews), SUM(n_reviews_with_text)
FROM '{OUT}'
""").fetchone()
sz = OUT.stat().st_size / 1e6
print()
print("=== Stage 5 output ===")
print(f"  file:                {OUT}  ({sz:.1f} MB)")
print(f"  POIs:                {r[0]:,}")
print(f"  with Google meta:    {r[1]:,} ({r[1]/r[0]*100:.1f}%)")
print(f"  with reviews:        {r[2]:,} ({r[2]/r[0]*100:.1f}%)")
print(f"  total reviews:       {r[3]:,}")
print(f"  total reviews w/text:{r[4]:,}")
print(f"  total elapsed:       {time.time()-t0:.1f}s")
