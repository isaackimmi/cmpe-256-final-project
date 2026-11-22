"""
Stage 12 (UCSD bridge):  match the 81,592 NEW clean-benchmark POIs (those
absent from the precursor build) against the two UCSD POI corpora to inherit Google Maps
metadata + reviews for free.

Strategy
--------
The UCSD POIs use FSQ-OS (bare 24-hex) IDs while our benchmark uses FSQ v2
(`foursquare:<24-hex>`); the two ID spaces don't bridge directly.  We
therefore do a SPATIAL + NAME-SIMILARITY match:

  1. Build a unified UCSD POI table (benchmark + all20) keyed by
     (gmap_id, name, lat, lon, gmaps_*, gl_*).
  2. Bucket both sides into 0.005°-cells (~500 m) and inner-join on bucket.
  3. Keep candidate pairs within 100 m Haversine distance.
  4. Compute normalized-name similarity (rapidfuzz token_set_ratio).
  5. For each new POI, keep its best UCSD match if similarity >= 70 and
     distance <= 100 m.

Outputs
-------
    _intermediate/ucsd_matches.parquet   one row per matched new-POI
    _intermediate/ucsd_unified.parquet   the unified UCSD source table

Empirically the 95 % precision quoted by the precursor README was achieved at
similarity >= 70 + distance <= 100 m; we keep those thresholds.
"""
from __future__ import annotations
import json, math, os, time
from pathlib import Path
import duckdb
import pyarrow as pa, pyarrow.parquet as pq
from rapidfuzz import fuzz
from unidecode import unidecode
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
GMAPS = Path(os.environ["GMAPS_FULL_ROOT"])
INTER = ROOT / "_intermediate"
INTER.mkdir(parents=True, exist_ok=True)

UCSD_BENCH    = GMAPS / "metadata/ucsd_benchmark_pois.parquet"
UCSD_ALL20    = GMAPS / "metadata/ucsd_all20_pois.jsonl"
NEW_POIS_PARQ = INTER / "new_pois_for_match.parquet"
UCSD_UNIFIED  = INTER / "ucsd_unified.parquet"
MATCHES_OUT   = INTER / "ucsd_matches.parquet"

# Tunables (proven 95% precision on precursor build)
MAX_DIST_M    = 100.0
MIN_NAME_SIM  = 70.0
BUCKET_DEG    = 0.005   # ~ 555 m


# ---------------------------------------------------------------------------
# Step 1. Build a unified UCSD POI table
# ---------------------------------------------------------------------------

def build_unified_ucsd() -> int:
    """Materialise UCSD POIs from both sources into one parquet."""
    print("[step 1] reading ucsd_all20_pois.jsonl ...")
    rows_all20 = []
    with open(UCSD_ALL20) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            lat = r.get("gl_latitude")
            lon = r.get("gl_longitude")
            if lat is None or lon is None:
                continue
            rows_all20.append({
                "src":              "all20",
                "ucsd_fsq_os_id":   r.get("fsq_place_id"),
                "name":             r.get("gl_name") or r.get("gmaps_name") or r.get("fsq_name"),
                "lat":              float(lat),
                "lon":              float(lon),
                "gmap_id":          r.get("gmap_id"),
                "gmaps_name":       r.get("gmaps_name"),
                "gmaps_full_address": r.get("gmaps_full_address"),
                "gmaps_address":    r.get("gmaps_address"),
                "gmaps_website":    None,
                "gmaps_rating":     r.get("gmaps_rating"),
                "gmaps_num_reviews": r.get("gmaps_num_reviews"),
                "gmaps_categories": r.get("gmaps_categories"),
                "gmaps_url":        r.get("gmaps_url"),
                "place_id":         r.get("place_id"),
                "gl_name":          r.get("gl_name"),
                "gl_address":       r.get("gl_address"),
                "gl_avg_rating":    r.get("gl_avg_rating"),
                "gl_num_reviews":   r.get("gl_num_reviews"),
                "gl_url":           r.get("gl_url"),
                "gl_category":      r.get("gl_category"),
                "gl_description":   r.get("gl_description"),
                "gl_price":         r.get("gl_price"),
                "gl_hours":         r.get("gl_hours"),
                "gl_state":         r.get("gl_state"),
            })
    print(f"  all20 rows with coords: {len(rows_all20):,}")

    print("[step 1] reading ucsd_benchmark_pois.parquet ...")
    # Bench file has no lat/lon columns, so extract them from `gmaps_url`
    # (URLs of form .../@<lat>,<lon>,17z).
    import re
    LATLON_RE = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
    con = duckdb.connect()
    con.execute("PRAGMA threads=32")
    bench_q = con.execute(f"""
SELECT fsq_place_id, fsq_name, cid AS gmap_id,
       gmaps_name, gmaps_full_address, gmaps_address, gmaps_website,
       gmaps_rating, gmaps_num_reviews, gmaps_categories, gmaps_url, place_id,
       gl_name, gl_address, gl_avg_rating, gl_num_reviews, gl_url, gl_category,
       gl_description, gl_price, gl_hours, gl_state
FROM '{UCSD_BENCH}' WHERE status='ok'
""")
    bench_rows = bench_q.fetchall()
    cols = [d[0] for d in bench_q.description]
    rows_bench = []
    for tup in bench_rows:
        r = dict(zip(cols, tup))
        url = r.get("gmaps_url") or r.get("gl_url") or ""
        m = LATLON_RE.search(url or "")
        if not m:
            continue
        rows_bench.append({
            "src":              "bench",
            "ucsd_fsq_os_id":   r["fsq_place_id"],
            "name":             r.get("gl_name") or r.get("gmaps_name") or r.get("fsq_name"),
            "lat":              float(m.group(1)),
            "lon":              float(m.group(2)),
            "gmap_id":          r["gmap_id"],
            "gmaps_name":       r.get("gmaps_name"),
            "gmaps_full_address": r.get("gmaps_full_address"),
            "gmaps_address":    r.get("gmaps_address"),
            "gmaps_website":    r.get("gmaps_website"),
            "gmaps_rating":     r.get("gmaps_rating"),
            "gmaps_num_reviews": r.get("gmaps_num_reviews"),
            "gmaps_categories": r.get("gmaps_categories"),
            "gmaps_url":        r.get("gmaps_url"),
            "place_id":         r.get("place_id"),
            "gl_name":          r.get("gl_name"),
            "gl_address":       r.get("gl_address"),
            "gl_avg_rating":    r.get("gl_avg_rating"),
            "gl_num_reviews":   r.get("gl_num_reviews"),
            "gl_url":           r.get("gl_url"),
            "gl_category":      r.get("gl_category"),
            "gl_description":   r.get("gl_description"),
            "gl_price":         r.get("gl_price"),
            "gl_hours":         r.get("gl_hours"),
            "gl_state":         r.get("gl_state"),
        })
    print(f"  bench rows with parsable coords: {len(rows_bench):,}")

    all_rows = rows_all20 + rows_bench

    # Normalize: cast list-typed columns to list-or-None; string-typed to str-or-None.
    LIST_COLS    = {"gmaps_categories", "gl_category", "gl_hours"}
    STRING_COLS  = {"src", "ucsd_fsq_os_id", "name", "gmap_id", "gmaps_name",
                     "gmaps_full_address", "gmaps_address", "gmaps_website",
                     "gmaps_url", "place_id",
                     "gl_name", "gl_address", "gl_url", "gl_description",
                     "gl_price", "gl_state"}
    FLOAT_COLS   = {"lat", "lon", "gmaps_rating", "gl_avg_rating"}
    INT_COLS     = {"gmaps_num_reviews", "gl_num_reviews"}
    for r in all_rows:
        for c in LIST_COLS:
            v = r.get(c)
            if v is None:
                r[c] = None
            elif isinstance(v, list):
                r[c] = v
            else:
                r[c] = [str(v)]
        for c in STRING_COLS:
            v = r.get(c)
            r[c] = None if v is None else (str(v) if not isinstance(v, str) else v)
        for c in FLOAT_COLS:
            v = r.get(c)
            try:    r[c] = None if v is None else float(v)
            except (TypeError, ValueError): r[c] = None
        for c in INT_COLS:
            v = r.get(c)
            try:    r[c] = None if v is None else int(v)
            except (TypeError, ValueError): r[c] = None

    # Build with an explicit schema to avoid type inference surprises.
    schema = pa.schema([
        ("src", pa.string()),
        ("ucsd_fsq_os_id", pa.string()),
        ("name", pa.string()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("gmap_id", pa.string()),
        ("gmaps_name", pa.string()),
        ("gmaps_full_address", pa.string()),
        ("gmaps_address", pa.string()),
        ("gmaps_website", pa.string()),
        ("gmaps_rating", pa.float64()),
        ("gmaps_num_reviews", pa.int64()),
        ("gmaps_categories", pa.list_(pa.string())),
        ("gmaps_url", pa.string()),
        ("place_id", pa.string()),
        ("gl_name", pa.string()),
        ("gl_address", pa.string()),
        ("gl_avg_rating", pa.float64()),
        ("gl_num_reviews", pa.int64()),
        ("gl_url", pa.string()),
        ("gl_category", pa.list_(pa.string())),
        ("gl_description", pa.string()),
        ("gl_price", pa.string()),
        ("gl_hours", pa.list_(pa.list_(pa.string()))),
        ("gl_state", pa.string()),
    ])
    table = pa.Table.from_pylist(all_rows, schema=schema)
    pq.write_table(table, UCSD_UNIFIED, compression="zstd")
    print(f"  wrote unified table: {UCSD_UNIFIED}  ({UCSD_UNIFIED.stat().st_size/1e6:.1f} MB, "
          f"{len(all_rows):,} rows)")
    return len(all_rows)


# ---------------------------------------------------------------------------
# Step 2-5. Bucket-join + filter
# ---------------------------------------------------------------------------

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(min(1.0, math.sqrt(a)))


def normalize_name(s: str | None) -> str:
    if not s: return ""
    return unidecode(str(s)).lower().strip()


def run_bridge():
    print(f"\n[step 2] bucket-join (cell={BUCKET_DEG}deg) ...")
    con = duckdb.connect()
    con.execute("PRAGMA threads=32")
    con.execute(f"SET memory_limit='32GB'")

    # Build candidate-pair table via bucket join, then keep only pairs where
    # both POIs land in the same OR an immediately-adjacent cell.
    # We expand "same cell" to a 3x3 neighborhood by joining on each of the 9
    # offsets of the UCSD side.
    con.execute(f"""
CREATE TEMP TABLE new_p AS
SELECT fsq_place_id AS new_id, fsq_name AS new_name, lat AS new_lat, lon AS new_lon,
       FLOOR(lat / {BUCKET_DEG}) AS by_, FLOOR(lon / {BUCKET_DEG}) AS bx_
FROM '{NEW_POIS_PARQ}'
""")
    con.execute(f"""
CREATE TEMP TABLE ucsd_p AS
SELECT * EXCLUDE (lat, lon),
       lat AS u_lat, lon AS u_lon,
       FLOOR(lat / {BUCKET_DEG}) AS by_, FLOOR(lon / {BUCKET_DEG}) AS bx_
FROM '{UCSD_UNIFIED}'
WHERE name IS NOT NULL
""")
    n_new   = con.execute("SELECT COUNT(*) FROM new_p").fetchone()[0]
    n_ucsd  = con.execute("SELECT COUNT(*) FROM ucsd_p").fetchone()[0]
    print(f"  new POIs:  {n_new:,}")
    print(f"  ucsd POIs: {n_ucsd:,}")

    # 3x3 neighborhood join on bucket coords (each of the 9 offsets).
    # Avoid materialising all 9 unions in memory: compute candidate pairs
    # straight to a temp table.
    con.execute("""
CREATE TEMP TABLE cand AS
SELECT n.new_id, n.new_name, n.new_lat, n.new_lon,
       u.ucsd_fsq_os_id, u.gmap_id, u.name AS u_name,
       u.u_lat, u.u_lon, u.src
FROM new_p n
JOIN ucsd_p u
  ON   u.by_ BETWEEN n.by_ - 1 AND n.by_ + 1
   AND u.bx_ BETWEEN n.bx_ - 1 AND n.bx_ + 1
""")
    n_cand = con.execute("SELECT COUNT(*) FROM cand").fetchone()[0]
    print(f"[step 3] candidate pairs (bucket-neighbors): {n_cand:,}")

    if n_cand == 0:
        print("no candidate pairs -- writing empty matches table")
        empty = pa.table({c: pa.array([], type=pa.string()) for c in
                          ["fsq_place_id", "ucsd_fsq_os_id", "gmap_id", "match_src",
                           "distance_m", "name_sim"]})
        pq.write_table(empty, MATCHES_OUT, compression="zstd")
        return 0

    # Pull into Python (list of tuples), score, and keep best per new_id.
    print("[step 4] scoring (haversine + token_set_ratio) ...")
    rows = con.execute("""
SELECT new_id, new_name, new_lat, new_lon, ucsd_fsq_os_id, gmap_id, u_name, u_lat, u_lon, src
FROM cand
""").fetchall()

    best: dict[str, tuple[float, float, dict]] = {}
    t0 = time.time()
    n = len(rows)
    eval_ct = 0
    accept_ct = 0
    for i, (new_id, new_name, n_lat, n_lon, ucsd_fsq_os_id, gmap_id, u_name, u_lat, u_lon, src) in enumerate(rows):
        d = haversine_m(n_lat, n_lon, u_lat, u_lon)
        if d > MAX_DIST_M:
            continue
        sim = fuzz.token_set_ratio(normalize_name(new_name), normalize_name(u_name))
        eval_ct += 1
        if sim < MIN_NAME_SIM:
            continue
        accept_ct += 1
        # Score = sim - distance_in_m * 0.2 (favor close + similar)
        score = sim - d * 0.2
        prev = best.get(new_id)
        if prev is None or score > prev[0]:
            best[new_id] = (score, d, sim, gmap_id, ucsd_fsq_os_id, src)
        if (i + 1) % 200_000 == 0:
            rate = (i + 1) / (time.time() - t0)
            eta = (n - i - 1) / max(rate, 1)
            print(f"  scored {i+1:>10,}/{n:,}  rate {rate/1000:5.1f}k/s  eta {eta:.0f}s  "
                  f"so_far {len(best):,} matches")

    print(f"\n[step 4] eval after distance filter: {eval_ct:,}  accept: {accept_ct:,}")
    print(f"[step 5] best-per-new-POI: {len(best):,} matches")

    # Materialise matches table
    out = []
    for new_id, (score, d, sim, gmap_id, ucsd_fsq_os_id, src) in best.items():
        out.append({"fsq_place_id": new_id, "ucsd_fsq_os_id": ucsd_fsq_os_id,
                    "gmap_id": gmap_id, "match_src": src,
                    "distance_m": d, "name_sim": sim})
    if not out:
        out = [{"fsq_place_id": "_dummy_", "ucsd_fsq_os_id": "", "gmap_id": "",
                 "match_src": "", "distance_m": 0.0, "name_sim": 0.0}][:0]
    pq.write_table(pa.Table.from_pylist(out), MATCHES_OUT, compression="zstd")
    print(f"wrote {MATCHES_OUT}  ({MATCHES_OUT.stat().st_size/1e6:.2f} MB)")
    return len(best)


def main():
    if not UCSD_UNIFIED.exists():
        build_unified_ucsd()
    else:
        print(f"reusing existing {UCSD_UNIFIED}  "
              f"({UCSD_UNIFIED.stat().st_size/1e6:.1f} MB)")
    n = run_bridge()
    print(f"\nDONE. matched {n:,} of 81,592 new POIs.")


if __name__ == "__main__":
    main()
