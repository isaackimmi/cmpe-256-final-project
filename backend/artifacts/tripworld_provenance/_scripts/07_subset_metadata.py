"""
Stage 7: subset metadata/metadata_all.parquet to only POIs in Trip World.
Output: $TRIP_WORLD_ROOT/metadata/metadata_all.parquet
"""
import duckdb, time, os
from pathlib import Path
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
SRC = str(Path(os.environ["PRECURSOR_BUILD_ROOT"]) / "metadata" / "metadata_all.parquet")
POIS = ROOT / "pois.parquet"
OUT = ROOT / "metadata" / "metadata_all.parquet"
OUT.parent.mkdir(parents=True, exist_ok=True)

t0 = time.time()
def step(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

con = duckdb.connect()
con.execute("PRAGMA threads=32")
con.execute("SET memory_limit='32GB'")

step(f"reading Trip World POI universe from {POIS}")
con.execute(f"CREATE TABLE keep_ids AS SELECT fsq_place_id FROM '{POIS}'")
n_keep = con.execute("SELECT COUNT(*) FROM keep_ids").fetchone()[0]
step(f"  {n_keep:,} clean POIs to keep")

step(f"streaming subset of {SRC} ...")
con.execute(f"""
COPY (
  SELECT m.* FROM '{SRC}' m
  SEMI JOIN keep_ids k USING (fsq_place_id)
) TO '{OUT}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 200000)
""")
n_out = con.execute(f"SELECT COUNT(*) FROM '{OUT}'").fetchone()[0]
sz = OUT.stat().st_size / 1e6
print()
print("=== Stage 7 output ===")
print(f"  file:           {OUT}  ({sz:.1f} MB)")
print(f"  metadata rows:  {n_out:,} of {n_keep:,} POIs ({n_out/n_keep*100:.1f}% covered)")
print(f"  total elapsed:  {time.time()-t0:.1f}s")
