"""
Stage 15:  fold the listugcposts (Stage 2) reviews into Trip World.

Reads:
    _intermediate/gcp_reviews/reviews_NN.jsonl
        produced by gmaps_reviews_gcp/collect.sh
        Each row contains:
            fsq_place_id, fid, fsq_name, fetched_at, status, num_pages,
            num_reviews,
            reviews: [
                {review_id, author, author_id, timestamp_us, relative_time,
                 rating, text, lang, owner_reply}
            ]

Writes:
    reviews/reviews_listugcposts.parquet
        flat per-review table for the listugcposts crawl
    reviews/reviews_all.parquet
        union with the existing google_inline_reviews.parquet, deduped on
        review_id, prioritising listugcposts over inline (former is fuller).

Idempotent — safe to re-run.
"""
from __future__ import annotations
import json, time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

import os
ROOT  = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
INTER = ROOT / "_intermediate"
GCP_DIR = INTER / "gcp_reviews"
REVIEWS_DIR = ROOT / "reviews"

INLINE  = REVIEWS_DIR / "google_inline_reviews.parquet"   # from Stage 14
STAGE2  = REVIEWS_DIR / "reviews_listugcposts.parquet"    # output (this script)
ALL_OUT = REVIEWS_DIR / "reviews_all.parquet"             # union output


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main() -> None:
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Load all listugcposts JSONL files
    # ------------------------------------------------------------------
    log("loading listugcposts JSONL ...")
    files = sorted(GCP_DIR.glob("reviews_*.jsonl"))
    log(f"  found {len(files)} files")
    if not files:
        log("  no input — Stage 2 hasn't been collected yet?")
        return

    # Per-POI dedup: keep the record with most reviews per fsq_place_id.
    poi_rows: dict[str, dict] = {}
    n_lines = 0
    for fp in files:
        with open(fp) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                n_lines += 1
                fid = r.get("fsq_place_id")
                if not fid: continue
                prev = poi_rows.get(fid)
                if prev is None or len(r.get("reviews") or []) > len(prev.get("reviews") or []):
                    poi_rows[fid] = r
    log(f"  read {n_lines:,} rows -> {len(poi_rows):,} unique POIs")

    # ------------------------------------------------------------------
    # 2. Flatten -> per-review table
    # ------------------------------------------------------------------
    log("flattening to per-review rows ...")
    flat = []
    n_pois_with_reviews = 0
    for fid, r in poi_rows.items():
        revs = r.get("reviews") or []
        if not revs: continue
        n_pois_with_reviews += 1
        cid = r.get("fid")
        for rev in revs:
            flat.append({
                "fsq_place_id":   fid,
                "google_cid":     cid,
                "review_id":      rev.get("review_id"),
                "rating":         rev.get("rating"),
                "text":           rev.get("text"),
                "author":         rev.get("author"),
                "author_id":      rev.get("author_id"),
                "timestamp_us":   rev.get("timestamp_us"),
                "relative_time": rev.get("relative_time"),
                "lang":           rev.get("lang"),
                "owner_reply":    rev.get("owner_reply"),
                "source":         "listugcposts",
            })
    log(f"  POIs with >=1 review: {n_pois_with_reviews:,}")
    log(f"  total reviews:        {len(flat):,}")

    # ------------------------------------------------------------------
    # 3. Write reviews_listugcposts.parquet
    # ------------------------------------------------------------------
    log("writing reviews_listugcposts.parquet ...")
    schema = pa.schema([
        ("fsq_place_id", pa.string()),
        ("google_cid",   pa.string()),
        ("review_id",    pa.string()),
        ("rating",       pa.int64()),
        ("text",         pa.string()),
        ("author",       pa.string()),
        ("author_id",    pa.string()),
        ("timestamp_us", pa.int64()),
        ("relative_time", pa.string()),
        ("lang",         pa.string()),
        ("owner_reply",  pa.string()),
        ("source",       pa.string()),
    ])
    pq.write_table(pa.Table.from_pylist(flat, schema=schema),
                    STAGE2, compression="zstd")
    log(f"  wrote {STAGE2}  ({STAGE2.stat().st_size/1e6:.1f} MB)")

    # ------------------------------------------------------------------
    # 4. Build reviews_all.parquet = union(listugcposts, inline) deduped
    # ------------------------------------------------------------------
    if not INLINE.exists():
        log(f"  inline reviews parquet missing ({INLINE}) — writing reviews_all = stage2 only")
        STAGE2.replace(ALL_OUT) if False else None  # leave files separate
        import shutil; shutil.copy(STAGE2, ALL_OUT)
    else:
        log("computing union with inline reviews ...")
        con = duckdb.connect()
        con.execute("PRAGMA threads=16")
        con.execute("SET memory_limit='16GB'")
        # Inline reviews don't have author_id / lang / owner_reply; project them as NULL.
        con.execute(f"""
COPY (
  WITH unioned AS (
    SELECT
      fsq_place_id, google_cid, review_id, rating, text,
      author, author_id, timestamp_us, relative_time, lang, owner_reply,
      source, 1 AS prio
    FROM '{STAGE2}'
    UNION ALL
    SELECT
      fsq_place_id, google_cid, review_id, rating, text,
      author, NULL AS author_id, timestamp_us, relative_time,
      NULL AS lang, NULL AS owner_reply,
      'inline_preload' AS source, 2 AS prio
    FROM '{INLINE}'
  ),
  ranked AS (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY COALESCE(review_id, fsq_place_id || '|' || COALESCE(author,'') || '|' || COALESCE(text,''))
      ORDER BY prio
    ) AS rn
    FROM unioned
  )
  SELECT
    fsq_place_id, google_cid, review_id, rating, text,
    author, author_id, timestamp_us, relative_time, lang, owner_reply, source
  FROM ranked WHERE rn = 1
) TO '{ALL_OUT}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 200000)
""")
        log(f"  wrote {ALL_OUT}  ({ALL_OUT.stat().st_size/1e6:.1f} MB)")

    # ------------------------------------------------------------------
    # 5. Final stats
    # ------------------------------------------------------------------
    log("computing final stats ...")
    con = duckdb.connect()
    con.execute("PRAGMA threads=16")
    n_revs   = con.execute(f"SELECT COUNT(*) FROM '{ALL_OUT}'").fetchone()[0]
    n_text   = con.execute(f"SELECT COUNT(*) FROM '{ALL_OUT}' WHERE text IS NOT NULL AND length(text) >= 30").fetchone()[0]
    n_pois   = con.execute(f"SELECT COUNT(DISTINCT fsq_place_id) FROM '{ALL_OUT}'").fetchone()[0]
    n_pois_text = con.execute(f"SELECT COUNT(DISTINCT fsq_place_id) FROM '{ALL_OUT}' WHERE text IS NOT NULL AND length(text) >= 30").fetchone()[0]
    by_src = con.execute(f"SELECT source, COUNT(*) FROM '{ALL_OUT}' GROUP BY 1 ORDER BY 2 DESC").fetchall()

    print()
    print("=" * 60)
    print("FINAL REVIEW COVERAGE (Trip World, new POIs only)")
    print("=" * 60)
    print(f"  unique POIs with reviews:       {n_pois:,}")
    print(f"  unique POIs with text reviews:  {n_pois_text:,}")
    print(f"  total reviews:                  {n_revs:,}")
    print(f"  reviews with >=30 char text:    {n_text:,}")
    print()
    print("by source:")
    for s, c in by_src:
        print(f"  {s:30s} {c:>10,}")


if __name__ == "__main__":
    main()
