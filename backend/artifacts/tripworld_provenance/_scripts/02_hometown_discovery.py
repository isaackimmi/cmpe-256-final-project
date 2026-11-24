"""
Stage 2 of the Trip World build pipeline: hometown discovery.

For each user u, compute the supporting value
    phi(u, r) = sum_{c_i in r} theta^(-delta_t_i / T) / (N + eps)
across each candidate region r the user has check-ins in.  Pick r_h = argmax phi,
then drop users whose hometown has fewer than --min-home-ci check-ins.

Constants
---------
theta = 2          (matches the doc; halves weight every T days)
T     = 180 days   (typical "season" window)
eps   = 1          (denominator regulariser)
observation_time = MAX(ts) in the consolidated stream

Output: _intermediate/users_hometown.parquet
        Columns: user_id, r_h, phi_home, n_home_ci
"""
import duckdb, time, math
from pathlib import Path
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
IN  = ROOT / "_intermediate" / "checkins_consolidated.parquet"
OUT = ROOT / "_intermediate" / "users_hometown.parquet"

THETA = 2.0
T_DAYS = 180.0
EPS = 1.0
MIN_HOME_CI = 4

t0 = time.time()
def step(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

con = duckdb.connect()
con.execute("PRAGMA threads=32")
con.execute("SET memory_limit='48GB'")
con.execute("SET preserve_insertion_order=false")
con.execute(f"SET temp_directory='{os.environ.get('DUCKDB_TMP_DIR', '/tmp/duckdb_trip_world')}'")

# Determine observation_time (max ts in stream) once.
obs_ts = con.execute(f"SELECT MAX(ts) FROM read_parquet('{IN}')").fetchone()[0]
step(f"observation time: {obs_ts}")

# Compute phi(u, r) per (user, region) and N (total CIs) per user, then pick winner.
# delta_t in days = epoch_seconds(obs_ts - ts) / 86400
step("computing phi(u, r) and selecting hometown ...")
con.execute(f"""
CREATE TABLE phi AS
WITH per_user_total AS (
  SELECT user_id, COUNT(*) AS N
  FROM read_parquet('{IN}')
  GROUP BY user_id
),
weighted AS (
  SELECT user_id, region_id,
         POW({THETA}, -EXTRACT(EPOCH FROM (TIMESTAMP '{obs_ts}' - ts)) / 86400.0 / {T_DAYS}) AS w
  FROM read_parquet('{IN}')
)
SELECT  w.user_id,
        w.region_id,
        SUM(w.w) AS sum_w,
        COUNT(*) AS n_ci,
        SUM(w.w) / (any_value(t.N) + {EPS}) AS phi
FROM weighted w
JOIN per_user_total t USING (user_id)
GROUP BY w.user_id, w.region_id
""")
step(f"  phi rows: {con.execute('SELECT COUNT(*) FROM phi').fetchone()[0]:,}")

# Pick hometown = argmax phi per user
step("picking r_h = argmax phi per user ...")
con.execute("""
CREATE TABLE users_hometown_raw AS
SELECT user_id, region_id AS r_h, phi AS phi_home, n_ci AS n_home_ci
FROM (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY phi DESC, n_ci DESC, region_id) AS rn
  FROM phi
)
WHERE rn = 1
""")
n_users_pre = con.execute("SELECT COUNT(*) FROM users_hometown_raw").fetchone()[0]
step(f"  candidate hometowns assigned: {n_users_pre:,} users")

# Filter: |c_h| >= MIN_HOME_CI
step(f"applying |c_h| >= {MIN_HOME_CI} filter ...")
con.execute(f"""
COPY (
  SELECT user_id, r_h, phi_home, n_home_ci
  FROM users_hometown_raw
  WHERE n_home_ci >= {MIN_HOME_CI}
  ORDER BY user_id
) TO '{OUT}' (FORMAT PARQUET, COMPRESSION 'zstd')
""")
n_kept = con.execute(f"SELECT COUNT(*) FROM read_parquet('{OUT}')").fetchone()[0]
n_dist_homes = con.execute(f"SELECT COUNT(DISTINCT r_h) FROM read_parquet('{OUT}')").fetchone()[0]
sz = OUT.stat().st_size / 1e6
print()
print("=== Stage 2 output ===")
print(f"  file:               {OUT}  ({sz:.1f} MB)")
print(f"  users with hometown: {n_kept:,} (dropped {n_users_pre-n_kept:,})")
print(f"  distinct hometowns:  {n_dist_homes:,}")
print(f"  total elapsed:       {time.time()-t0:.1f}s")
