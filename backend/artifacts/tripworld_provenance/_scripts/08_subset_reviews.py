"""
Stage 8: subset reviews/reviews_all.parquet to only POIs in Trip World.

Source precursor reviews/ contains six per-source parquet files plus a unified
reviews_all.parquet (~13 GB).  We only re-emit the unified file -- it's
the only one downstream pipelines actually read (reviews_*.parquet glob
matches reviews_all.parquet so it's de-facto the canonical).
"""
import duckdb, time
from pathlib import Path
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
SRC = str(Path(os.environ["PRECURSOR_BUILD_ROOT"]) / "reviews" / "reviews_all.parquet")
POIS = ROOT / "pois.parquet"
OUT = ROOT / "reviews" / "reviews_all.parquet"
OUT.parent.mkdir(parents=True, exist_ok=True)

t0 = time.time()
def step(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

con = duckdb.connect()
con.execute("PRAGMA threads=32")
con.execute("SET memory_limit='48GB'")
con.execute("SET preserve_insertion_order=false")
con.execute(f"SET temp_directory='{os.environ.get('DUCKDB_TMP_DIR', '/tmp/duckdb_trip_world')}'")

step(f"reading Trip World POI universe from {POIS}")
con.execute(f"CREATE TABLE keep_ids AS SELECT fsq_place_id FROM '{POIS}'")
n_keep = con.execute("SELECT COUNT(*) FROM keep_ids").fetchone()[0]
step(f"  {n_keep:,} POIs to keep")

step(f"streaming + filtering {SRC} ... (this takes a few minutes)")
con.execute(f"""
COPY (
  SELECT r.* FROM '{SRC}' r
  SEMI JOIN keep_ids k USING (fsq_place_id)
) TO '{OUT}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 200000)
""")
n_rev = con.execute(f"SELECT COUNT(*) FROM '{OUT}'").fetchone()[0]
n_pois_with_reviews = con.execute(
    f"SELECT COUNT(DISTINCT fsq_place_id) FROM '{OUT}'").fetchone()[0]
sz = OUT.stat().st_size / 1e6
print()
print("=== Stage 8 output ===")
print(f"  file:                 {OUT}  ({sz/1024:.2f} GB)")
print(f"  reviews:              {n_rev:,}")
print(f"  POIs with reviews:    {n_pois_with_reviews:,} of {n_keep:,}")
print(f"  total elapsed:        {time.time()-t0:.1f}s")
