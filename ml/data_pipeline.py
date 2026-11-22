"""Shared Spine: Bronze -> Silver -> Gold Medallion Pipeline + Pandera Validation + 5-Fold CV.

Run once (or whenever cleaning rules change):
    .venv/bin/python -m ml.data_pipeline

Outputs in `data/gold/`:
    - pois_clean.parquet            (687K POIs with noise/closed/recommendable flags & GPS)
    - cv_folds.parquet              (User-grouped 5-fold CV mapping: user_id -> fold)
    - trips_multicity.parquet       (Chronological multi-city trips: history_pois -> target_pois)
    - trip_history_exploded.parquet (Flat table: trip_id, poi_id, source_region_id, is_home)
    - trip_targets_exploded.parquet (Flat ground-truth table: trip_id, dest_region_id, poi_id)
"""

from __future__ import annotations

import time
import duckdb
import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Column, Check, DataFrameSchema

from ml.config import (
    DATA_GOLD_DIR,
    DATA_RAW_DIR,
    DATA_SILVER_DIR,
    MIN_HISTORY_POIS,
    MIN_TARGET_POIS,
    N_FOLDS,
    NOISE_SCHEMAS,
)


POIS_SCHEMA = DataFrameSchema(
    {
        "poi_id": Column(str, nullable=False, unique=True),
        "region_id": Column(str, nullable=False),
        "lat": Column(float, nullable=True, checks=Check.in_range(-90.0, 90.0)),
        "lon": Column(float, nullable=True, checks=Check.in_range(-180.0, 180.0)),
        "is_noise": Column(bool, nullable=False),
        "is_closed": Column(bool, nullable=False),
        "is_recommendable": Column(bool, nullable=False),
    }
)

FOLDS_SCHEMA = DataFrameSchema(
    {
        "user_id": Column("int64", nullable=False, unique=True),
        "fold": Column("int64", nullable=False, checks=Check.in_range(0, N_FOLDS - 1)),
    }
)

TRIPS_SCHEMA = DataFrameSchema(
    {
        "trip_id": Column("int64", nullable=False, unique=True),
        "user_id": Column("int64", nullable=False),
        "fold": Column("int64", nullable=False, checks=Check.in_range(0, N_FOLDS - 1)),
        "home_region_id": Column(str, nullable=False),
        "dest_region_id": Column(str, nullable=False),
        "dest_month": Column("int32", nullable=False, checks=Check.in_range(1, 12)),
        "n_history_cities": Column("int64", nullable=False, checks=Check.ge(1)),
        "n_history_pois": Column("int64", nullable=False, checks=Check.ge(MIN_HISTORY_POIS)),
        "n_target_pois": Column("int64", nullable=False, checks=Check.ge(MIN_TARGET_POIS)),
    }
)


def build_pipeline() -> None:
    t0 = time.perf_counter()
    DATA_SILVER_DIR.mkdir(parents=True, exist_ok=True)
    DATA_GOLD_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    noise_sql = ", ".join(f"'{s}'" for s in sorted(NOISE_SCHEMAS))

    print("[1/5] Building Silver/Gold clean POI catalog (`pois_clean.parquet`)...")
    pois_out = DATA_GOLD_DIR / "pois_clean.parquet"
    con.execute(f"""
        COPY (
            SELECT
                p.fsq_place_id AS poi_id,
                p.locality AS region_id,
                COALESCE(r.city_name, p.locality) AS city_name,
                COALESCE(r.country_name, m.fsq_country, 'Unknown') AS country_name,
                COALESCE(NULLIF(p.google_name, ''), NULLIF(m.fsq_name, ''), p.fsq_place_id) AS name,
                COALESCE(p.venue_schema, 'schema:Place') AS venue_schema,
                p.venue_category,
                p.google_categories,
                m.fsq_category_labels,
                m.fsq_latitude AS lat,
                m.fsq_longitude AS lon,
                p.google_rating,
                COALESCE(p.google_num_reviews, 0) AS google_num_reviews,
                COALESCE(p.n_checkins, 0) AS n_checkins,
                COALESCE(p.n_users_visited, 0) AS n_users_visited,
                COALESCE(p.n_reviews, 0) AS n_reviews,
                (p.google_rating IS NOT NULL) AS has_google_rating,
                (m.fsq_date_closed IS NOT NULL) AS is_closed,
                (COALESCE(p.venue_schema, '') IN ({noise_sql})) AS is_noise,
                (
                    COALESCE(p.venue_schema, '') NOT IN ({noise_sql})
                    AND m.fsq_date_closed IS NULL
                    AND m.fsq_latitude IS NOT NULL
                    AND m.fsq_longitude IS NOT NULL
                ) AS is_recommendable
            FROM '{DATA_RAW_DIR}/pois.parquet' p
            LEFT JOIN '{DATA_RAW_DIR}/metadata/metadata_all.parquet' m
                ON p.fsq_place_id = m.fsq_place_id
            LEFT JOIN '{DATA_RAW_DIR}/region_labels.parquet' r
                ON p.locality = r.region_id
        ) TO '{pois_out}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """)

    print("[2/5] Creating deterministic User-Grouped 5-Fold CV (`cv_folds.parquet`)...")
    folds_out = DATA_GOLD_DIR / "cv_folds.parquet"
    con.execute(f"""
        COPY (
            SELECT
                CAST(user_id AS BIGINT) AS user_id,
                CAST(ABS(HASH(user_id * 2654435761 + 42)) % {N_FOLDS} AS BIGINT) AS fold
            FROM (SELECT DISTINCT user_id FROM '{DATA_RAW_DIR}/travel_behaviors.parquet')
            ORDER BY user_id
        ) TO '{folds_out}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """)

    print("[3/5] Building chronological Multi-City Trips (`trips_multicity.parquet`)...")
    # Step 3a: Extract per-trip metadata, home unique POIs, and recommendable destination target POIs
    con.execute(f"""
        CREATE TEMP TABLE pois_ref AS
        SELECT poi_id, region_id, venue_schema, is_noise, is_recommendable
        FROM '{pois_out}';

        CREATE TEMP TABLE raw_trips AS
        SELECT
            ROW_NUMBER() OVER (ORDER BY t.user_id, list_min(list_transform(t.c_o, lambda x: x.ts)), t.r_o) AS raw_trip_id,
            CAST(t.user_id AS BIGINT) AS user_id,
            f.fold,
            t.r_h AS home_region_id,
            t.r_o AS dest_region_id,
            list_min(list_transform(t.c_o, lambda x: x.ts)) AS dest_start_ts,
            CAST(EXTRACT(MONTH FROM list_min(list_transform(t.c_o, lambda x: x.ts))) AS INTEGER) AS dest_month,
            ROW_NUMBER() OVER (
                PARTITION BY t.user_id
                ORDER BY list_min(list_transform(t.c_o, lambda x: x.ts)), t.r_o
            ) AS trip_seq,
            t.c_h,
            t.c_o
        FROM '{DATA_RAW_DIR}/travel_behaviors.parquet' t
        JOIN '{folds_out}' f ON t.user_id = f.user_id
        WHERE t.r_h != t.r_o;
    """)

    # Step 3b: Explode clean recommendable destination targets per trip
    con.execute("""
        CREATE TEMP TABLE target_visits AS
        SELECT DISTINCT
            rt.raw_trip_id,
            rt.user_id,
            rt.fold,
            rt.dest_region_id,
            rt.trip_seq,
            u.venue_id AS poi_id,
            p.venue_schema
        FROM raw_trips rt,
        UNNEST(rt.c_o) AS _(u)
        JOIN pois_ref p ON u.venue_id = p.poi_id
        WHERE p.is_recommendable = TRUE
          AND p.region_id = rt.dest_region_id;

        -- All non-noise destination visits from earlier trips (used as multi-city history for later trips)
        CREATE TEMP TABLE earlier_travel_visits AS
        SELECT DISTINCT
            rt.user_id,
            rt.trip_seq AS visit_trip_seq,
            rt.dest_region_id AS source_region_id,
            u.venue_id AS poi_id,
            p.venue_schema
        FROM raw_trips rt,
        UNNEST(rt.c_o) AS _(u)
        JOIN pois_ref p ON u.venue_id = p.poi_id
        WHERE p.is_noise = FALSE;

        -- Deduplicated home-city visits per user (non-noise)
        CREATE TEMP TABLE home_visits AS
        SELECT DISTINCT
            rt.user_id,
            rt.home_region_id AS source_region_id,
            u.venue_id AS poi_id,
            p.venue_schema
        FROM (SELECT user_id, home_region_id, c_h FROM raw_trips WHERE trip_seq = 1) rt,
        UNNEST(rt.c_h) AS _(u)
        JOIN pois_ref p ON u.venue_id = p.poi_id
        WHERE p.is_noise = FALSE;
    """)

    # Step 3c: Combine home visits + strictly earlier other-city visits into multi-city history
    con.execute("""
        CREATE TEMP TABLE valid_target_trips AS
        SELECT
            raw_trip_id,
            LIST(poi_id ORDER BY poi_id) AS target_pois,
            COUNT(*) AS n_target_pois
        FROM target_visits
        GROUP BY raw_trip_id
        HAVING COUNT(*) >= """ + str(MIN_TARGET_POIS) + """;

        CREATE TEMP TABLE history_all AS
        -- Home history for every valid trip
        SELECT
            rt.raw_trip_id,
            rt.user_id,
            rt.fold,
            hv.source_region_id,
            hv.poi_id,
            hv.venue_schema,
            TRUE AS is_home
        FROM raw_trips rt
        JOIN valid_target_trips vt ON rt.raw_trip_id = vt.raw_trip_id
        JOIN home_visits hv ON rt.user_id = hv.user_id
        WHERE hv.source_region_id != rt.dest_region_id

        UNION ALL

        -- Earlier destination trips in OTHER cities (strictly earlier trip_seq)
        SELECT
            rt.raw_trip_id,
            rt.user_id,
            rt.fold,
            etv.source_region_id,
            etv.poi_id,
            etv.venue_schema,
            FALSE AS is_home
        FROM raw_trips rt
        JOIN valid_target_trips vt ON rt.raw_trip_id = vt.raw_trip_id
        JOIN earlier_travel_visits etv
            ON rt.user_id = etv.user_id
           AND etv.visit_trip_seq < rt.trip_seq
           AND etv.source_region_id != rt.dest_region_id;

        CREATE TEMP TABLE history_dedup AS
        SELECT
            raw_trip_id,
            user_id,
            fold,
            poi_id,
            ANY_VALUE(source_region_id) AS source_region_id,
            ANY_VALUE(venue_schema) AS venue_schema,
            BOOL_OR(is_home) AS is_home
        FROM history_all
        GROUP BY raw_trip_id, user_id, fold, poi_id;

        CREATE TEMP TABLE history_agg AS
        SELECT
            raw_trip_id,
            LIST(poi_id ORDER BY poi_id) AS history_pois,
            LIST(DISTINCT source_region_id ORDER BY source_region_id) AS history_region_ids,
            COUNT(DISTINCT source_region_id) AS n_history_cities,
            COUNT(*) AS n_history_pois
        FROM history_dedup
        GROUP BY raw_trip_id
        HAVING COUNT(*) >= """ + str(MIN_HISTORY_POIS) + """;
    """)

    trips_out = DATA_GOLD_DIR / "trips_multicity.parquet"
    hist_out = DATA_GOLD_DIR / "trip_history_exploded.parquet"
    targ_out = DATA_GOLD_DIR / "trip_targets_exploded.parquet"

    con.execute(f"""
        CREATE TEMP TABLE final_trips AS
        SELECT
            CAST(ROW_NUMBER() OVER (ORDER BY rt.raw_trip_id) AS BIGINT) AS trip_id,
            rt.raw_trip_id,
            rt.user_id,
            rt.fold,
            rt.home_region_id,
            rt.dest_region_id,
            rt.dest_start_ts,
            rt.dest_month,
            CAST(rt.trip_seq AS BIGINT) AS trip_seq,
            ha.n_history_cities,
            ha.n_history_pois,
            vt.n_target_pois,
            ha.history_region_ids,
            ha.history_pois,
            vt.target_pois
        FROM raw_trips rt
        JOIN history_agg ha ON rt.raw_trip_id = ha.raw_trip_id
        JOIN valid_target_trips vt ON rt.raw_trip_id = vt.raw_trip_id;

        COPY (
            SELECT
                trip_id, user_id, fold, home_region_id, dest_region_id,
                dest_start_ts, dest_month, trip_seq,
                n_history_cities, n_history_pois, n_target_pois,
                history_region_ids, history_pois, target_pois
            FROM final_trips
            ORDER BY trip_id
        ) TO '{trips_out}' (FORMAT PARQUET, COMPRESSION ZSTD);

        COPY (
            SELECT
                ft.trip_id,
                ft.user_id,
                ft.fold,
                hd.source_region_id,
                hd.poi_id,
                hd.venue_schema,
                hd.is_home
            FROM final_trips ft
            JOIN history_dedup hd ON ft.raw_trip_id = hd.raw_trip_id
            ORDER BY ft.trip_id, hd.poi_id
        ) TO '{hist_out}' (FORMAT PARQUET, COMPRESSION ZSTD);

        COPY (
            SELECT
                ft.trip_id,
                ft.user_id,
                ft.fold,
                tv.dest_region_id,
                tv.poi_id,
                tv.venue_schema
            FROM final_trips ft
            JOIN target_visits tv ON ft.raw_trip_id = tv.raw_trip_id
            ORDER BY ft.trip_id, tv.poi_id
        ) TO '{targ_out}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """)

    print("[4/5] Running Pandera Data Validation & Anti-Leakage Gates...")
    pois_df = pd.read_parquet(
        pois_out,
        columns=["poi_id", "region_id", "lat", "lon", "is_noise", "is_closed", "is_recommendable"],
    )
    POIS_SCHEMA.validate(pois_df)

    folds_df = pd.read_parquet(folds_out)
    FOLDS_SCHEMA.validate(folds_df)

    trips_df = pd.read_parquet(
        trips_out,
        columns=[
            "trip_id", "user_id", "fold", "home_region_id", "dest_region_id",
            "dest_month", "n_history_cities", "n_history_pois", "n_target_pois",
        ],
    )
    TRIPS_SCHEMA.validate(trips_df)

    # Hard anti-leakage check: zero overlap between history_pois and target_pois for any trip
    leak_cnt = con.sql(f"""
        SELECT COUNT(*)
        FROM '{hist_out}' h
        JOIN '{targ_out}' t
          ON h.trip_id = t.trip_id AND h.poi_id = t.poi_id
    """).fetchall()[0][0]
    assert leak_cnt == 0, f"DATA LEAKAGE DETECTED: {leak_cnt} overlapping history/target POIs!"

    # Hard anti-leakage check: every user belongs to exactly 1 fold
    multi_fold_users = con.sql(f"""
        SELECT COUNT(*) FROM (
            SELECT user_id FROM '{trips_out}' GROUP BY user_id HAVING COUNT(DISTINCT fold) > 1
        )
    """).fetchall()[0][0]
    assert multi_fold_users == 0, f"CV LEAKAGE DETECTED: {multi_fold_users} users in multiple folds!"

    elapsed = time.perf_counter() - t0
    print(f"[5/5] Done in {elapsed:.1f}s! All Pandera & Anti-Leakage checks PASSED.")
    print(f"      POIs clean:         {len(pois_df):,} ({int(pois_df['is_recommendable'].sum()):,} recommendable)")
    print(f"      Multi-city trips:   {len(trips_df):,} across {trips_df['user_id'].nunique():,} users")
    multi_city_share = 100.0 * (trips_df["n_history_cities"] >= 2).mean()
    print(f"      Multi-city history: {multi_city_share:.1f}% of trips use 2+ prior cities!")
    print("      Fold distribution: ", trips_df["fold"].value_counts().sort_index().to_dict())


if __name__ == "__main__":
    build_pipeline()
