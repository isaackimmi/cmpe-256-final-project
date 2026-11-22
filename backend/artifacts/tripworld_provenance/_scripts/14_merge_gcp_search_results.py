"""
Stage 14:  fold the GCP search-and-scrape results into Trip World.

Reads:
    _intermediate/gcp_search_attrs/shard_*/search_attrs.jsonl
        produced by gmaps_search_gcp/collect.sh
        Each row contains:
            fsq_place_id, status, search_query, match_dist_m, match_name_sim,
            biz: {cid, name, full_address, address, website, rating,
                   num_reviews, categories, place_id, gmaps_url, lat, lon},
            description_short, description_long,
            hours_today, hours_week,
            price_token, price_min, price_max,
            attributes: [...],
            inline_reviews: [...],
            raw_size, fetched_at, error

Writes:
    metadata/metadata_all.parquet     (overwritten with google_* + new
                                       google_attrs_* cols populated)
    metadata/place_attributes.parquet (NEW: description/hours/price/attrs)
    reviews/google_inline_reviews.parquet  (NEW)

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
META  = ROOT / "metadata" / "metadata_all.parquet"
ATTRS_OUT = ROOT / "metadata" / "place_attributes.parquet"
REVIEWS_DIR = ROOT / "reviews"
REVIEWS_OUT = REVIEWS_DIR / "google_inline_reviews.parquet"
INTER = ROOT / "_intermediate"
GCP_DIR = INTER / "gcp_search_attrs"
META_TMP = META.with_suffix(".tmp.parquet")


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Load all GCP shards into memory
    # ------------------------------------------------------------------
    log("loading GCP shards ...")
    rows = []
    files = sorted(GCP_DIR.glob("shard_*/search_attrs.jsonl"))
    if not files:
        # Fallback: also look for un-merged worker files
        files = sorted(GCP_DIR.glob("shard_*/search_attrs*.jsonl"))
    log(f"  found {len(files)} shard files")
    for fp in files:
        with open(fp) as fh:
            for line in fh:
                try: rows.append(json.loads(line))
                except Exception: continue
    log(f"  loaded {len(rows):,} records")

    # Deduplicate by fsq_place_id, keeping the LATEST 'ok' if any, else last
    by_id: dict[str, dict] = {}
    for r in rows:
        fid = r.get("fsq_place_id")
        if not fid: continue
        prev = by_id.get(fid)
        if prev is None: by_id[fid] = r; continue
        prev_ok = prev.get("status") == "ok"
        cur_ok  = r.get("status") == "ok"
        if cur_ok and not prev_ok:
            by_id[fid] = r
    rows = list(by_id.values())
    log(f"  after dedup by fsq_place_id: {len(rows):,}")

    # ------------------------------------------------------------------
    # 2. Build the enrichment table (google_* + place_attributes)
    # ------------------------------------------------------------------
    log("building enrichment tables ...")
    google_rows = []     # for metadata overlay
    attrs_rows = []      # for place_attributes.parquet
    review_rows = []     # for inline_reviews.parquet
    for r in rows:
        fid = r["fsq_place_id"]
        if r.get("status") != "ok": continue
        biz = r.get("biz") or {}
        cid = biz.get("cid")
        if not cid: continue
        google_rows.append({
            "fsq_place_id": fid,
            "google_cid":          cid,
            "google_name":         biz.get("name"),
            "google_full_address": biz.get("full_address"),
            "google_address":      biz.get("address"),
            "google_website":      biz.get("website"),
            "google_rating":       (float(biz["rating"])
                                     if biz.get("rating") is not None else None),
            "google_num_reviews":  (int(biz["num_reviews"])
                                     if biz.get("num_reviews") is not None else None),
            "google_categories":   biz.get("categories"),
            "google_place_id":     biz.get("place_id"),
            "google_gmaps_url":    biz.get("gmaps_url"),
            "google_meta_source":  "gcp_search_2026",
        })
        attrs_rows.append({
            "fsq_place_id":      fid,
            "google_cid":        cid,
            "search_query":      r.get("search_query"),
            "match_dist_m":      r.get("match_dist_m"),
            "match_name_sim":    r.get("match_name_sim"),
            "description_short": r.get("description_short"),
            "description_long":  r.get("description_long"),
            "hours_today":       json.dumps(r.get("hours_today")) if r.get("hours_today") else None,
            "hours_week":        json.dumps(r.get("hours_week"))  if r.get("hours_week")  else None,
            "price_token":       r.get("price_token"),
            "price_min":         r.get("price_min"),
            "price_max":         r.get("price_max"),
            "attributes":        json.dumps(r.get("attributes")) if r.get("attributes") else None,
            "n_inline_reviews":  len(r.get("inline_reviews") or []),
            "fetched_at":        r.get("fetched_at"),
        })
        for rev in (r.get("inline_reviews") or []):
            review_rows.append({
                "fsq_place_id":   fid,
                "google_cid":     cid,
                "review_id":      rev.get("review_id"),
                "rating":         rev.get("rating"),
                "text":           rev.get("text"),
                "author":         rev.get("author"),
                "timestamp_us":   rev.get("timestamp_us"),
                "relative_time":  rev.get("relative_time"),
                "source":         rev.get("source"),
            })
    log(f"  google enrichment rows: {len(google_rows):,}")
    log(f"  place_attributes rows:  {len(attrs_rows):,}")
    log(f"  inline_reviews rows:    {len(review_rows):,}")

    # ------------------------------------------------------------------
    # 3. Write place_attributes + inline_reviews parquet (replace, idempotent)
    # ------------------------------------------------------------------
    log("writing place_attributes.parquet ...")
    pq.write_table(
        pa.Table.from_pylist(attrs_rows, schema=pa.schema([
            ("fsq_place_id", pa.string()),
            ("google_cid", pa.string()),
            ("search_query", pa.string()),
            ("match_dist_m", pa.float64()),
            ("match_name_sim", pa.float64()),
            ("description_short", pa.string()),
            ("description_long", pa.string()),
            ("hours_today", pa.string()),
            ("hours_week", pa.string()),
            ("price_token", pa.string()),
            ("price_min", pa.string()),
            ("price_max", pa.string()),
            ("attributes", pa.string()),
            ("n_inline_reviews", pa.int64()),
            ("fetched_at", pa.string()),
        ])),
        ATTRS_OUT, compression="zstd")
    log(f"  wrote {ATTRS_OUT}  ({ATTRS_OUT.stat().st_size/1e6:.1f} MB)")

    log("writing google_inline_reviews.parquet ...")
    pq.write_table(
        pa.Table.from_pylist(review_rows, schema=pa.schema([
            ("fsq_place_id", pa.string()),
            ("google_cid", pa.string()),
            ("review_id", pa.string()),
            ("rating", pa.int64()),
            ("text", pa.string()),
            ("author", pa.string()),
            ("timestamp_us", pa.int64()),
            ("relative_time", pa.string()),
            ("source", pa.string()),
        ])),
        REVIEWS_OUT, compression="zstd")
    log(f"  wrote {REVIEWS_OUT}  ({REVIEWS_OUT.stat().st_size/1e6:.1f} MB)")

    # ------------------------------------------------------------------
    # 4. Overlay google_* fields into metadata_all.parquet
    # ------------------------------------------------------------------
    log("overlaying google_* into metadata_all.parquet ...")
    enrich_path = INTER / "_gcp_google_overlay.parquet"
    pq.write_table(
        pa.Table.from_pylist(google_rows, schema=pa.schema([
            ("fsq_place_id", pa.string()),
            ("google_cid", pa.string()),
            ("google_name", pa.string()),
            ("google_full_address", pa.string()),
            ("google_address", pa.string()),
            ("google_website", pa.string()),
            ("google_rating", pa.float64()),
            ("google_num_reviews", pa.int64()),
            ("google_categories", pa.list_(pa.string())),
            ("google_place_id", pa.string()),
            ("google_gmaps_url", pa.string()),
            ("google_meta_source", pa.string()),
        ])),
        enrich_path, compression="zstd")

    con = duckdb.connect()
    con.execute("PRAGMA threads=32")
    con.execute("SET memory_limit='32GB'")
    con.execute(f"""
COPY (
  SELECT
    m.fsq_place_id,
    m.benchmark_name, m.benchmark_locality,
    m.benchmark_venue_category, m.benchmark_venue_schema,
    m.fsq_name, m.fsq_latitude, m.fsq_longitude, m.fsq_address,
    m.fsq_locality, m.fsq_region, m.fsq_country, m.fsq_postcode,
    m.fsq_formatted_address, m.fsq_category_ids, m.fsq_category_labels,
    m.fsq_website, m.fsq_tel, m.fsq_email, m.fsq_facebook_id,
    m.fsq_instagram, m.fsq_twitter,
    m.fsq_date_created, m.fsq_date_refreshed, m.fsq_date_closed,
    m.fsq_meta_source, m.has_fsq_metadata,
    COALESCE(m.google_cid,           e.google_cid)           AS google_cid,
    COALESCE(m.google_name,          e.google_name)          AS google_name,
    COALESCE(m.google_full_address,  e.google_full_address)  AS google_full_address,
    COALESCE(m.google_address,       e.google_address)       AS google_address,
    COALESCE(m.google_website,       e.google_website)       AS google_website,
    COALESCE(m.google_rating,        e.google_rating)        AS google_rating,
    COALESCE(m.google_num_reviews,   e.google_num_reviews)   AS google_num_reviews,
    COALESCE(m.google_categories,    e.google_categories)    AS google_categories,
    COALESCE(m.google_place_id,      e.google_place_id)      AS google_place_id,
    COALESCE(m.google_gmaps_url,     e.google_gmaps_url)     AS google_gmaps_url,
    CASE
      WHEN m.has_google_metadata THEN m.google_meta_source
      WHEN e.google_cid IS NOT NULL THEN e.google_meta_source
      ELSE m.google_meta_source
    END AS google_meta_source,
    (m.has_google_metadata OR e.google_cid IS NOT NULL) AS has_google_metadata
  FROM '{META}' m
  LEFT JOIN '{enrich_path}' e USING (fsq_place_id)
) TO '{META_TMP}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 200000)
""")
    META.unlink(); META_TMP.rename(META)
    log(f"  rewrote {META}")

    # ------------------------------------------------------------------
    # 5. Final coverage stats
    # ------------------------------------------------------------------
    log("computing final coverage ...")
    n_total = con.execute(f"SELECT COUNT(*) FROM '{META}'").fetchone()[0]
    n_with_g = con.execute(f"SELECT SUM(CASE WHEN has_google_metadata THEN 1 ELSE 0 END) FROM '{META}'").fetchone()[0]
    n_attrs  = con.execute(f"SELECT COUNT(*) FROM '{ATTRS_OUT}'").fetchone()[0]
    n_revs   = con.execute(f"SELECT COUNT(*) FROM '{REVIEWS_OUT}'").fetchone()[0]
    n_revs_text = con.execute(f"""
SELECT COUNT(*) FROM '{REVIEWS_OUT}'
WHERE text IS NOT NULL AND length(text) >= 30
""").fetchone()[0]
    print()
    print("=" * 60)
    print("FINAL COVERAGE")
    print("=" * 60)
    print(f"  metadata_all rows:               {n_total:,}")
    print(f"  POIs with Google metadata:       {n_with_g:,} "
          f"({n_with_g/n_total*100:.2f}%)")
    print(f"  POIs with place_attributes:      {n_attrs:,} "
          f"({n_attrs/n_total*100:.2f}%)")
    print(f"  Inline reviews collected:        {n_revs:,}")
    print(f"  Reviews with >=30 char text:     {n_revs_text:,}")
    print()

    by_src = con.execute(f"""
SELECT google_meta_source, COUNT(*) FROM '{META}'
WHERE google_cid IS NOT NULL GROUP BY 1 ORDER BY 2 DESC
""").fetchall()
    print("google_meta_source breakdown:")
    for s, c in by_src:
        print(f"  {s or '(null)':30s} {c:>9,}")


if __name__ == "__main__":
    main()
