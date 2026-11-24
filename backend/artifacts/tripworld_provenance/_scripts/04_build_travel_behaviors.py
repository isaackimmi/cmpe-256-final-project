"""
Stage 4: assemble the final travel_behaviors.parquet (one row per τ).

Joins travelers + consolidated check-ins, packing each user's hometown / travel
check-in sequence into list<struct> columns.  Schema matches the precursor build:

    user_id          int64
    r_h, r_o         string  (bare metro QID, no 'wd:' prefix)
    n_home_ci        int64
    n_travel_ci      int64
    c_h              list<struct{trail_id, venue_id, venue_category, venue_schema, ts}>
    c_o              list<struct<...same...>>
"""
import duckdb, time, os
from pathlib import Path
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
INC = ROOT / "_intermediate" / "checkins_consolidated.parquet"
INT = ROOT / "_intermediate" / "travelers.parquet"
OUT = ROOT / "travel_behaviors.parquet"

t0 = time.time()
def step(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

con = duckdb.connect()
con.execute("PRAGMA threads=32")
con.execute("SET memory_limit='48GB'")
con.execute("SET preserve_insertion_order=false")
con.execute(f"SET temp_directory='{os.environ.get('DUCKDB_TMP_DIR', '/tmp/duckdb_trip_world')}'")

step("loading inputs ...")
con.execute(f"CREATE TABLE travelers AS SELECT * FROM '{INT}'")
con.execute(f"""
CREATE TABLE ck AS
SELECT user_id, region_id, trail_id, venue_id, venue_category, venue_schema, ts
FROM '{INC}'
""")
n_tr = con.execute("SELECT COUNT(*) FROM travelers").fetchone()[0]
n_ck = con.execute("SELECT COUNT(*) FROM ck").fetchone()[0]
step(f"  travelers: {n_tr:,}, check-ins: {n_ck:,}")

step("building per-(user, region) ordered check-in lists ...")
con.execute("""
CREATE TABLE user_region_seq AS
SELECT
  user_id, region_id,
  list({
    'trail_id': trail_id,
    'venue_id': venue_id,
    'venue_category': venue_category,
    'venue_schema': venue_schema,
    'ts': ts
  } ORDER BY ts) AS seq
FROM ck
GROUP BY user_id, region_id
""")
n_seq = con.execute("SELECT COUNT(*) FROM user_region_seq").fetchone()[0]
step(f"  user-region sequences: {n_seq:,}")

step(f"writing {OUT} ...")
con.execute(f"""
COPY (
  SELECT
    t.user_id, t.r_h, t.r_o, t.n_home_ci, t.n_travel_ci,
    h.seq AS c_h,
    o.seq AS c_o
  FROM travelers t
  LEFT JOIN user_region_seq h ON h.user_id = t.user_id AND h.region_id = t.r_h
  LEFT JOIN user_region_seq o ON o.user_id = t.user_id AND o.region_id = t.r_o
) TO '{OUT}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 50000)
""")
sz = OUT.stat().st_size / 1e6

# Verify
r = con.execute(f"""
SELECT
  COUNT(*) AS n_rows,
  COUNT(DISTINCT user_id) AS n_users,
  COUNT(DISTINCT r_h) AS n_homes,
  COUNT(DISTINCT r_o) AS n_dests,
  SUM(CASE WHEN r_h = r_o THEN 1 ELSE 0 END) AS n_phantom,
  SUM(CASE WHEN c_h IS NULL THEN 1 ELSE 0 END) AS missing_c_h,
  SUM(CASE WHEN c_o IS NULL THEN 1 ELSE 0 END) AS missing_c_o,
  AVG(len(c_h))::DOUBLE AS avg_ch,
  AVG(len(c_o))::DOUBLE AS avg_co
FROM '{OUT}'
""").fetchone()

print()
print("=== Stage 4 output ===")
print(f"  file:           {OUT}  ({sz:.1f} MB)")
for k, v in zip(['rows','users','homes','dests','phantom','missing_c_h','missing_c_o','avg_c_h','avg_c_o'], r):
    if isinstance(v, (int,)):
        print(f"  {k:14s}: {v:,}")
    else:
        print(f"  {k:14s}: {v:.2f}")
print(f"  total elapsed:  {time.time()-t0:.1f}s")
