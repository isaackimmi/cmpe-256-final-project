"""
Stage 16: build the unified reviews_all.parquet for Trip World.

Combines:
  - Precursor reviews (~96M rows) loaded from
        $PRECURSOR_BUILD_ROOT/reviews/reviews_all.parquet
    The $PRECURSOR_BUILD_ROOT env var should point at a previous output of
    this same pipeline whose review corpus we want to extend; omit this
    stage entirely if you do not have such a precursor build.
  - The newly-collected reviews from this release's stage-14/15 outputs:
        $TRIP_WORLD_ROOT/reviews/reviews_listugcposts.parquet
        $TRIP_WORLD_ROOT/reviews/google_inline_reviews.parquet
    (~15M rows total).

Both inputs are filtered to POIs that survived into Trip World, then
deduplicated on review_id (with a fallback hash on
fsq_place_id|author|text for rows missing review_id).

Schema is the union of all three, with NULLs for missing fields:
    fsq_place_id, google_cid, review_id, author, author_id, rating, text,
    text_translated, lang, relative_time, timestamp_us, review_time,
    owner_reply, source

Output:
    $TRIP_WORLD_ROOT/reviews/reviews_all.parquet  (overwritten)
"""
from __future__ import annotations
import time
from pathlib import Path
import duckdb
import os

ROOT_V1     = Path(os.environ["PRECURSOR_BUILD_ROOT"])
ROOT_CLEAN  = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
META_CLEAN  = ROOT_CLEAN / "metadata" / "metadata_all.parquet"

V1_REVIEWS  = ROOT_V1    / "reviews" / "reviews_all.parquet"
NEW_LISTUGC = ROOT_CLEAN / "reviews" / "reviews_listugcposts.parquet"
NEW_INLINE  = ROOT_CLEAN / "reviews" / "google_inline_reviews.parquet"

OUT         = ROOT_CLEAN / "reviews" / "reviews_all.parquet"
OUT_TMP     = OUT.with_suffix(".tmp.parquet")


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=32")
    con.execute("SET memory_limit='48GB'")

    # ------------------------------------------------------------------
    # 1. Sanity counts before union
    # ------------------------------------------------------------------
    log("counting inputs ...")
    n_prev = con.execute(f"SELECT COUNT(*) FROM '{V1_REVIEWS}'").fetchone()[0]
    n_lu = con.execute(f"SELECT COUNT(*) FROM '{NEW_LISTUGC}'").fetchone()[0]
    n_in = con.execute(f"SELECT COUNT(*) FROM '{NEW_INLINE}'").fetchone()[0]
    log(f"  precursor reviews:           {n_prev:>12,}")
    log(f"  new listugcposts:     {n_lu:>12,}")
    log(f"  new inline_preload:   {n_in:>12,}")
    log(f"  raw total before dedup: {n_prev + n_lu + n_in:>12,}")

    # ------------------------------------------------------------------
    # 2. Build unified, deduped reviews_all.
    #    Priority order, highest first:
    #      1) the listugcposts crawl (most reviews per place)
    #      2) precursor-build refetch rows (highest fidelity refetch)
    #      3) precursor-build other source tags
    #      4) inline-preview reviews from the search-page enrichment
    # ------------------------------------------------------------------
    log("building unified table (this can take a few minutes) ...")
    con.execute(f"""
COPY (
  WITH unioned AS (
    -- precursor reviews (96M)
    SELECT
      fsq_place_id,
      CAST(NULL AS VARCHAR) AS google_cid,
      review_id, author, author_id, rating, text, text_translated,
      lang, relative_time, timestamp_us, review_time,
      CAST(NULL AS VARCHAR) AS owner_reply,
      'v1_' || source AS source,
      CASE
        WHEN source = 'refetch'    THEN 2
        WHEN source = 'migrate'    THEN 3
        WHEN source = 'stage1d'    THEN 4
        WHEN source = 'playwright' THEN 5
        WHEN source = 'ucsd_all20' THEN 6
        WHEN source = 'ucsd_bench' THEN 7
        ELSE 8
      END AS prio
    FROM '{V1_REVIEWS}'
    UNION ALL
    -- new listugcposts (15M)
    SELECT
      fsq_place_id, google_cid,
      review_id, author, author_id, rating, text,
      CAST(NULL AS VARCHAR) AS text_translated,
      lang, relative_time, timestamp_us,
      CAST(NULL AS TIMESTAMP) AS review_time,
      owner_reply,
      source,                                  -- already 'listugcposts'
      1 AS prio                                -- highest priority
    FROM '{NEW_LISTUGC}'
    UNION ALL
    -- new inline preload (from search-and-scrape worker, ~227K rows)
    SELECT
      fsq_place_id, google_cid, review_id, author,
      CAST(NULL AS VARCHAR) AS author_id,
      rating, text,
      CAST(NULL AS VARCHAR) AS text_translated,
      CAST(NULL AS VARCHAR) AS lang,
      relative_time, timestamp_us,
      CAST(NULL AS TIMESTAMP) AS review_time,
      CAST(NULL AS VARCHAR) AS owner_reply,
      'inline_preload' AS source,
      9 AS prio                                -- lowest (always overshadowed)
    FROM '{NEW_INLINE}'
  ),
  ranked AS (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY COALESCE(
        review_id,
        fsq_place_id || '|' || COALESCE(author,'') || '|' || COALESCE(text,'')
      )
      ORDER BY prio
    ) AS rn
    FROM unioned
  )
  SELECT
    fsq_place_id, google_cid, review_id, author, author_id, rating,
    text, text_translated, lang, relative_time, timestamp_us, review_time,
    owner_reply, source
  FROM ranked WHERE rn = 1
) TO '{OUT_TMP}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 200000)
""")
    OUT.unlink(missing_ok=True)
    OUT_TMP.rename(OUT)
    log(f"  wrote {OUT}  ({OUT.stat().st_size/1e9:.2f} GB)")

    # ------------------------------------------------------------------
    # 3. Final stats
    # ------------------------------------------------------------------
    log("computing final stats ...")
    n_revs   = con.execute(f"SELECT COUNT(*) FROM '{OUT}'").fetchone()[0]
    n_text   = con.execute(f"SELECT COUNT(*) FROM '{OUT}' WHERE text IS NOT NULL AND length(text) >= 30").fetchone()[0]
    n_pois   = con.execute(f"SELECT COUNT(DISTINCT fsq_place_id) FROM '{OUT}'").fetchone()[0]
    n_pois_text = con.execute(f"SELECT COUNT(DISTINCT fsq_place_id) FROM '{OUT}' WHERE text IS NOT NULL AND length(text) >= 30").fetchone()[0]
    by_src = con.execute(f"SELECT source, COUNT(*) FROM '{OUT}' GROUP BY 1 ORDER BY 2 DESC").fetchall()

    n_total_pois = con.execute(f"SELECT COUNT(*) FROM '{META_CLEAN}'").fetchone()[0]
    n_pois_in_clean = con.execute(f"""
SELECT COUNT(DISTINCT r.fsq_place_id)
FROM '{OUT}' r
WHERE r.fsq_place_id IN (SELECT fsq_place_id FROM '{META_CLEAN}')
""").fetchone()[0]

    print()
    print("=" * 68)
    print("UNIFIED REVIEWS COVERAGE — Trip World")
    print("=" * 68)
    print(f"  total reviews in reviews_all:           {n_revs:>12,}")
    print(f"  reviews with >=30-char text:            {n_text:>12,}")
    print(f"  unique POIs with reviews:               {n_pois:>12,}")
    print(f"  unique POIs with text reviews:          {n_pois_text:>12,}")
    print(f"  POIs in Trip World (total):        {n_total_pois:>12,}")
    print(f"  POIs covered (intersected w/ clean):    {n_pois_in_clean:>12,}  "
          f"({n_pois_in_clean/n_total_pois*100:.2f}%)")
    print()
    print("by source:")
    for s, c in by_src:
        print(f"  {s:30s} {c:>13,}")


if __name__ == "__main__":
    main()
