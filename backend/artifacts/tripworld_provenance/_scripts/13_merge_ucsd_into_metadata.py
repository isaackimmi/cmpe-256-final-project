"""
Stage 13:  fold the 1,608 UCSD-matched new POIs' Google metadata into
metadata_all.parquet.

For each matched POI we populate the existing google_* columns:
    google_cid, google_name, google_full_address, google_address,
    google_website, google_rating, google_num_reviews, google_categories,
    google_place_id, google_gmaps_url, google_meta_source, has_google_metadata

`google_meta_source` is set to 'ucsd_<src>' (ucsd_all20 / ucsd_bench).

We DO NOT overwrite Google fields that are already populated for any POI
(none of the 1,608 should have any, but this safety check keeps the script
idempotent on re-run).
"""
from __future__ import annotations
from pathlib import Path
import duckdb
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
META   = ROOT / "metadata" / "metadata_all.parquet"
INTER  = ROOT / "_intermediate"
MATCHES = INTER / "ucsd_matches.parquet"
UNIFIED = INTER / "ucsd_unified.parquet"
META_TMP = META.with_suffix(".tmp.parquet")


def main():
    con = duckdb.connect()
    con.execute("PRAGMA threads=32")
    con.execute("SET memory_limit='32GB'")

    n_matches = con.execute(f"SELECT COUNT(*) FROM '{MATCHES}'").fetchone()[0]
    print(f"matches to fold in: {n_matches:,}")

    # Build the UCSD->google_* enrichment table for the matched fsq_place_ids.
    # We pick the first row per ucsd_fsq_os_id from the unified table (rare
    # duplicates between bench/all20 -- prefer 'bench' which is already
    # validated against the benchmark).
    con.execute(f"""
CREATE TEMP TABLE ucsd_dedup AS
SELECT * FROM (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY ucsd_fsq_os_id
                            ORDER BY CASE WHEN src='bench' THEN 0 ELSE 1 END) AS rn
  FROM '{UNIFIED}'
) WHERE rn = 1
""")

    con.execute(f"""
CREATE TEMP TABLE enrich AS
SELECT
  m.fsq_place_id,
  u.gmap_id                                      AS google_cid_new,
  COALESCE(u.gmaps_name,  u.gl_name)             AS google_name_new,
  u.gmaps_full_address                           AS google_full_address_new,
  COALESCE(u.gmaps_address, u.gl_address)        AS google_address_new,
  u.gmaps_website                                AS google_website_new,
  COALESCE(u.gmaps_rating, u.gl_avg_rating)      AS google_rating_new,
  COALESCE(u.gmaps_num_reviews, u.gl_num_reviews) AS google_num_reviews_new,
  COALESCE(u.gmaps_categories, u.gl_category)    AS google_categories_new,
  u.place_id                                     AS google_place_id_new,
  COALESCE(u.gmaps_url, u.gl_url)                AS google_gmaps_url_new,
  ('ucsd_' || u.src)                             AS google_meta_source_new
FROM '{MATCHES}' m
JOIN ucsd_dedup u USING (ucsd_fsq_os_id)
""")
    n_enrich = con.execute("SELECT COUNT(*) FROM enrich").fetchone()[0]
    print(f"  enrichment table size: {n_enrich:,}")

    # Inspect coverage of the enrichment payload.
    cov = con.execute("""
SELECT
  SUM(CASE WHEN google_cid_new IS NOT NULL                   THEN 1 ELSE 0 END) AS cid,
  SUM(CASE WHEN google_name_new IS NOT NULL                  THEN 1 ELSE 0 END) AS nm,
  SUM(CASE WHEN google_full_address_new IS NOT NULL          THEN 1 ELSE 0 END) AS addr,
  SUM(CASE WHEN google_website_new IS NOT NULL               THEN 1 ELSE 0 END) AS web,
  SUM(CASE WHEN google_rating_new IS NOT NULL                THEN 1 ELSE 0 END) AS rating,
  SUM(CASE WHEN google_categories_new IS NOT NULL            THEN 1 ELSE 0 END) AS cats
FROM enrich
""").fetchone()
    print(f"  field coverage: cid={cov[0]} name={cov[1]} addr={cov[2]} "
          f"web={cov[3]} rating={cov[4]} cats={cov[5]}")

    # COPY-write a new metadata_all.parquet that overlays google_* fields for
    # POIs in the enrichment table, leaving everything else unchanged.
    print("\nrewriting metadata_all.parquet ...")
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
    COALESCE(m.google_cid,           e.google_cid_new)           AS google_cid,
    COALESCE(m.google_name,          e.google_name_new)          AS google_name,
    COALESCE(m.google_full_address,  e.google_full_address_new)  AS google_full_address,
    COALESCE(m.google_address,       e.google_address_new)       AS google_address,
    COALESCE(m.google_website,       e.google_website_new)       AS google_website,
    COALESCE(m.google_rating,        e.google_rating_new)        AS google_rating,
    COALESCE(m.google_num_reviews,   e.google_num_reviews_new)   AS google_num_reviews,
    COALESCE(m.google_categories,    e.google_categories_new)    AS google_categories,
    COALESCE(m.google_place_id,      e.google_place_id_new)      AS google_place_id,
    COALESCE(m.google_gmaps_url,     e.google_gmaps_url_new)     AS google_gmaps_url,
    CASE
      WHEN m.has_google_metadata THEN m.google_meta_source
      WHEN e.google_cid_new IS NOT NULL THEN e.google_meta_source_new
      ELSE m.google_meta_source
    END AS google_meta_source,
    (m.has_google_metadata OR e.google_cid_new IS NOT NULL) AS has_google_metadata
  FROM '{META}' m
  LEFT JOIN enrich e USING (fsq_place_id)
) TO '{META_TMP}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 200000)
""")
    META.unlink(); META_TMP.rename(META)

    n_total = con.execute(f"SELECT COUNT(*) FROM '{META}'").fetchone()[0]
    n_with_g = con.execute(f"SELECT SUM(CASE WHEN has_google_metadata THEN 1 ELSE 0 END) FROM '{META}'").fetchone()[0]
    print(f"\nmetadata_all.parquet rewritten: {n_total:,} rows, "
          f"{n_with_g:,} with Google metadata ({n_with_g/n_total*100:.2f}%)")

    by_src = con.execute(f"""
SELECT google_meta_source, COUNT(*) FROM '{META}'
WHERE google_cid IS NOT NULL GROUP BY 1 ORDER BY 2 DESC
""").fetchall()
    print("\ngoogle_meta_source breakdown:")
    for s, c in by_src:
        print(f"  {s or '(null)':30s} {c:>9,}")


if __name__ == "__main__":
    main()
