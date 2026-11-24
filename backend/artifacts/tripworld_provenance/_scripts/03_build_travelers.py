"""
Stage 3 of the Trip World build pipeline.

Given users_hometown.parquet (each user's r_h) and the consolidated check-in
stream, identify (user, r_o) pairs where:
  (a) r_o != r_h
  (b) the user has at least --min-travel-ci check-ins in r_o
  (c) the (r_h, r_o) pair appears at least --min-pair-freq times across users

Output: _intermediate/travelers.parquet
        Columns: user_id, r_h, r_o, n_home_ci, n_travel_ci
"""
import duckdb, time
from pathlib import Path
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
INC  = ROOT / "_intermediate" / "checkins_consolidated.parquet"
INH  = ROOT / "_intermediate" / "users_hometown.parquet"
OUT  = ROOT / "_intermediate" / "travelers.parquet"

MIN_TRAVEL_CI = 2
MIN_PAIR_FREQ = 10

t0 = time.time()
def step(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

con = duckdb.connect()
con.execute("PRAGMA threads=32")
con.execute("SET memory_limit='48GB'")
con.execute("SET preserve_insertion_order=false")
con.execute(f"SET temp_directory='{os.environ.get('DUCKDB_TMP_DIR', '/tmp/duckdb_trip_world')}'")

# --- Step A: per (user, region) check-in counts -------------------------------
step("counting check-ins per (user, region) ...")
con.execute(f"""
CREATE TABLE ur_counts AS
SELECT user_id, region_id, COUNT(*) AS n_ci
FROM read_parquet('{INC}')
GROUP BY user_id, region_id
""")

# --- Step B: candidate destination tuples (user, r_h, r_o, n_travel_ci) -------
step("forming candidate (user, r_h, r_o, n_travel_ci) tuples ...")
con.execute(f"""
CREATE TABLE candidates AS
SELECT
  h.user_id,
  h.r_h,
  c.region_id AS r_o,
  h.n_home_ci,
  c.n_ci AS n_travel_ci
FROM read_parquet('{INH}') h
JOIN ur_counts c USING (user_id)
WHERE c.region_id <> h.r_h
  AND c.n_ci >= {MIN_TRAVEL_CI}
""")
n_cand = con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
step(f"  candidates after |c_o| >= {MIN_TRAVEL_CI}: {n_cand:,}")

# --- Step C: pair frequency filter -------------------------------------------
step(f"applying (r_h, r_o) pair frequency >= {MIN_PAIR_FREQ} filter ...")
con.execute(f"""
CREATE TABLE pair_freq AS
SELECT r_h, r_o, COUNT(*) AS pair_n
FROM candidates GROUP BY r_h, r_o HAVING pair_n >= {MIN_PAIR_FREQ}
""")
n_pairs = con.execute("SELECT COUNT(*) FROM pair_freq").fetchone()[0]
step(f"  pairs surviving: {n_pairs:,}")

con.execute(f"""
COPY (
  SELECT c.user_id, c.r_h, c.r_o, c.n_home_ci, c.n_travel_ci
  FROM candidates c JOIN pair_freq p USING (r_h, r_o)
  ORDER BY c.user_id
) TO '{OUT}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 50000)
""")

n_kept = con.execute(f"SELECT COUNT(*) FROM read_parquet('{OUT}')").fetchone()[0]
n_users = con.execute(f"SELECT COUNT(DISTINCT user_id) FROM read_parquet('{OUT}')").fetchone()[0]
n_homes = con.execute(f"SELECT COUNT(DISTINCT r_h) FROM read_parquet('{OUT}')").fetchone()[0]
n_dests = con.execute(f"SELECT COUNT(DISTINCT r_o) FROM read_parquet('{OUT}')").fetchone()[0]

# Sanity: there must be ZERO phantom rows (r_h == r_o) by construction
n_phantom = con.execute(f"SELECT COUNT(*) FROM read_parquet('{OUT}') WHERE r_h = r_o").fetchone()[0]

print()
print("=== Stage 3 output ===")
print(f"  file:                {OUT}  ({OUT.stat().st_size/1e6:.1f} MB)")
print(f"  travel-behavior rows: {n_kept:,}")
print(f"  unique travelers:    {n_users:,}")
print(f"  unique hometowns:    {n_homes:,}")
print(f"  unique destinations: {n_dests:,}")
print(f"  unique pairs:        {n_pairs:,}")
print(f"  phantom rows:        {n_phantom}  (must be 0)")
print(f"  total elapsed:       {time.time()-t0:.1f}s")
