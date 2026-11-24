"""
Stage 10 (post-build enrichment): hydrate the NEW POIs (those in the clean
benchmark but absent from precursor metadata) with FSQ-OS December-2024 lat/lon and
the rest of the FSQ metadata fields.

Step A: Identify new-POI universe = pois.parquet - metadata_all.parquet
Step B: SEMI JOIN against the LOCAL FSQ-OS Dec 2024 dump
        (${FSQ_OS_PARQUET_GLOB})
Step C: Append the resolved rows to metadata_all.parquet (rewriting it)
Step D: Dump the unresolved fsq_place_id list to fsq_unresolved.txt for
        downstream FSQ Places API recovery.

After this stage:
  metadata/metadata_all.parquet  carries FSQ rows for the precursor build
                                  plus the locally-resolved newly-added POIs
  fsq_unresolved.txt              lists POIs needing the FSQ API
"""
import duckdb, time
from pathlib import Path
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
POIS = ROOT / "pois.parquet"
META = ROOT / "metadata" / "metadata_all.parquet"
FSQ_OS = os.environ["FSQ_OS_PARQUET_GLOB"]
UNRES = ROOT / "fsq_unresolved.txt"

t0 = time.time()
def step(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

con = duckdb.connect()
con.execute("PRAGMA threads=32")
con.execute("SET memory_limit='48GB'")
con.execute("SET preserve_insertion_order=false")
con.execute(f"SET temp_directory='{os.environ.get('DUCKDB_TMP_DIR', '/tmp/duckdb_trip_world')}'")

# ---- A. find new POIs (in clean but not yet in metadata_all) -----------------
step("identifying new POIs (in clean pois.parquet but not in metadata_all) ...")
con.execute(f"""
CREATE TABLE clean_pois AS
SELECT fsq_place_id, locality, venue_category, venue_schema
FROM '{POIS}'
""")
con.execute(f"""
CREATE TABLE existing_meta_ids AS
SELECT fsq_place_id FROM '{META}'
""")
con.execute("""
CREATE TABLE new_ids AS
SELECT cp.fsq_place_id, cp.locality, cp.venue_category, cp.venue_schema,
       regexp_replace(cp.fsq_place_id, '^foursquare:', '') AS bare_id
FROM clean_pois cp
ANTI JOIN existing_meta_ids e USING (fsq_place_id)
""")
n_new = con.execute("SELECT COUNT(*) FROM new_ids").fetchone()[0]
step(f"  {n_new:,} new POIs to enrich")

if n_new == 0:
    print("Nothing to do.")
    raise SystemExit(0)

# ---- B. resolve from local FSQ-OS Dec 2024 dump ------------------------------
step("looking up new POIs in local FSQ-OS Dec 2024 dump (~6.8 GB, may take ~1 min) ...")
con.execute(f"""
CREATE TABLE resolved_local AS
SELECT
  ('foursquare:' || fsq.fsq_place_id) AS fsq_place_id,
  fsq.name        AS fsq_name,
  fsq.latitude    AS fsq_latitude,
  fsq.longitude   AS fsq_longitude,
  fsq.address     AS fsq_address,
  fsq.locality    AS fsq_locality,
  fsq.region      AS fsq_region,
  fsq.country     AS fsq_country,
  fsq.postcode    AS fsq_postcode,
  CASE WHEN fsq.address IS NOT NULL OR fsq.locality IS NOT NULL
       THEN concat_ws(', ', fsq.address, fsq.locality, fsq.region, fsq.country) END AS fsq_formatted_address,
  fsq.fsq_category_ids,
  fsq.fsq_category_labels,
  fsq.website     AS fsq_website,
  fsq.tel         AS fsq_tel,
  fsq.email       AS fsq_email,
  fsq.facebook_id AS fsq_facebook_id,
  fsq.instagram   AS fsq_instagram,
  fsq.twitter     AS fsq_twitter,
  fsq.date_created   AS fsq_date_created,
  fsq.date_refreshed AS fsq_date_refreshed,
  fsq.date_closed    AS fsq_date_closed,
  'fsq_os_dec_2024' AS fsq_meta_source,
  TRUE              AS has_fsq_metadata
FROM read_parquet('{FSQ_OS}') fsq
SEMI JOIN new_ids n ON n.bare_id = fsq.fsq_place_id
""")
n_resolved = con.execute("SELECT COUNT(*) FROM resolved_local").fetchone()[0]
step(f"  {n_resolved:,} new POIs resolved locally  ({n_resolved/n_new*100:.1f}% coverage)")

# ---- C. write expanded metadata_all.parquet ---------------------------------
# Approach: read existing META + resolved_local + remaining nulls, UNION ALL.
step("writing expanded metadata_all.parquet ...")

# Bench-side fields for new POIs (carry through locality/category/schema as benchmark_*).
con.execute("""
CREATE TABLE new_bench AS
SELECT fsq_place_id,
       NULL AS benchmark_name,
       locality AS benchmark_locality,
       venue_category AS benchmark_venue_category,
       venue_schema AS benchmark_venue_schema
FROM new_ids
""")

# A row for every new POI: bench fields + (resolved or null) FSQ + null Google fields.
META_TMP = ROOT / "metadata" / "metadata_all_v2.parquet"
con.execute(f"""
COPY (
  -- existing rows
  SELECT * FROM '{META}'
  UNION ALL BY NAME
  -- new rows: left-join resolved_local, fill nulls for missing
  SELECT
    nb.fsq_place_id,
    nb.benchmark_name,
    nb.benchmark_locality,
    nb.benchmark_venue_category,
    nb.benchmark_venue_schema,
    rl.fsq_name, rl.fsq_latitude, rl.fsq_longitude,
    rl.fsq_address, rl.fsq_locality, rl.fsq_region, rl.fsq_country,
    rl.fsq_postcode, rl.fsq_formatted_address,
    rl.fsq_category_ids, rl.fsq_category_labels,
    rl.fsq_website, rl.fsq_tel, rl.fsq_email,
    rl.fsq_facebook_id, rl.fsq_instagram, rl.fsq_twitter,
    rl.fsq_date_created, rl.fsq_date_refreshed, rl.fsq_date_closed,
    COALESCE(rl.fsq_meta_source, 'unresolved')  AS fsq_meta_source,
    COALESCE(rl.has_fsq_metadata, FALSE)        AS has_fsq_metadata,
    NULL AS google_cid, NULL AS google_name,
    NULL AS google_full_address, NULL AS google_address,
    NULL AS google_website, NULL AS google_rating, NULL AS google_num_reviews,
    NULL AS google_categories, NULL AS google_place_id, NULL AS google_gmaps_url,
    'none' AS google_meta_source,
    FALSE AS has_google_metadata
  FROM new_bench nb
  LEFT JOIN resolved_local rl USING (fsq_place_id)
) TO '{META_TMP}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 200000)
""")

# Atomic swap
META.unlink()
META_TMP.rename(META)
n_meta_total = con.execute(f"SELECT COUNT(*) FROM '{META}'").fetchone()[0]
n_meta_with_fsq = con.execute(f"SELECT SUM(CASE WHEN has_fsq_metadata THEN 1 ELSE 0 END) FROM '{META}'").fetchone()[0]
n_meta_with_coords = con.execute(f"SELECT SUM(CASE WHEN fsq_latitude IS NOT NULL THEN 1 ELSE 0 END) FROM '{META}'").fetchone()[0]
sz = META.stat().st_size / 1e6
step(f"  metadata_all.parquet now has {n_meta_total:,} rows ({sz:.0f} MB)")

# ---- D. write unresolved list -----------------------------------------------
n_unres = n_new - n_resolved
con.execute(f"""
COPY (
  SELECT n.fsq_place_id
  FROM new_ids n
  ANTI JOIN resolved_local rl USING (fsq_place_id)
  ORDER BY 1
) TO '{UNRES}' (HEADER FALSE, DELIMITER ' ')
""")
step(f"  {n_unres:,} POIs still unresolved -> {UNRES}")

print()
print("=== Stage 10 output ===")
print(f"  metadata rows total:      {n_meta_total:,}  ({n_meta_total/687173*100:.1f}% of POI universe)")
print(f"  rows with FSQ metadata:   {n_meta_with_fsq:,}  ({n_meta_with_fsq/n_meta_total*100:.1f}%)")
print(f"  rows with lat/lon:        {n_meta_with_coords:,}  ({n_meta_with_coords/n_meta_total*100:.1f}%)")
print(f"  POIs needing FSQ API:     {n_unres:,}")
print(f"  total elapsed:            {time.time()-t0:.1f}s")
