"""Person 1 Track: Locality-Aware & Opportunity-Normalized Feature Plug-In.

Usage:
    .venv/bin/python -m ml.features.build_locality_features --val-fold 0

Outputs in `data/gold/`:
    1. feat_city_supply.parquet         (region_id, venue_schema -> city supply share & affordance)
    2. feat_poi_stats_fold{val_fold}.parquet           (poi_id -> Bayesian rating, log popularity, tourist ratio,
                                         distance to city center, city rank percentile)
    3. feat_user_locality_taste.parquet (trip_id, venue_schema -> multi-city user share,
                                         opportunity-normalized lift, was_available_in_history)

How to improve this module (Person 1 ideas):
    - Add H3 / spatial neighborhood POI density around each venue
    - Add cross-city category transition probabilities P(dest_cat | home_cat)
    - Add season / hemisphere x coastal / mountain interaction features using `dest_month` + `lat`
    - Add Google review sentiment / topic tags streamed from `reviews_all.parquet`
"""

from __future__ import annotations

import argparse
import time
import duckdb

from ml.config import DATA_GOLD_DIR
from ml.features.popularity import create_training_poi_counts


def build_locality_features(val_fold: int = 0) -> None:
    t0 = time.perf_counter()
    con = duckdb.connect()
    create_training_poi_counts(con, val_fold, gold_dir=DATA_GOLD_DIR)

    pois_path = DATA_GOLD_DIR / "pois_clean.parquet"
    trips_path = DATA_GOLD_DIR / "trips_multicity.parquet"
    hist_path = DATA_GOLD_DIR / "trip_history_exploded.parquet"
    targ_path = DATA_GOLD_DIR / "trip_targets_exploded.parquet"

    supply_out = DATA_GOLD_DIR / "feat_city_supply.parquet"
    poi_stats_out = DATA_GOLD_DIR / f"feat_poi_stats_fold{val_fold}.parquet"
    taste_out = DATA_GOLD_DIR / "feat_user_locality_taste.parquet"

    print("[Person 1 - 1/3] Computing city activity supply & affordances (`feat_city_supply.parquet`)...")
    con.execute(f"""
        COPY (
            WITH rec_pois AS (
                SELECT region_id, venue_schema
                FROM '{pois_path}'
                WHERE is_recommendable = TRUE
            ),
            city_totals AS (
                SELECT region_id, COUNT(*) AS city_total_pois
                FROM rec_pois
                GROUP BY region_id
            ),
            city_cats AS (
                SELECT region_id, venue_schema, COUNT(*) AS city_cat_pois
                FROM rec_pois
                GROUP BY region_id, venue_schema
            )
            SELECT
                cc.region_id,
                cc.venue_schema,
                cc.city_cat_pois,
                ct.city_total_pois,
                CAST(cc.city_cat_pois AS DOUBLE) / ct.city_total_pois AS city_supply_share
            FROM city_cats cc
            JOIN city_totals ct ON cc.region_id = ct.region_id
        ) TO '{supply_out}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """)

    print(f"[Person 1 - 2/3] Computing leakage-safe POI stats (train folds != {val_fold})...")
    con.execute(f"""
        COPY (
            WITH global_rating AS (
                SELECT AVG(google_rating) AS mean_r FROM '{pois_path}' WHERE google_rating IS NOT NULL
            ),
            city_center AS (
                SELECT
                    region_id,
                    AVG(lat) AS center_lat,
                    AVG(lon) AS center_lon
                FROM '{pois_path}'
                WHERE is_recommendable = TRUE
                GROUP BY region_id
            ),
            -- Tourist check-ins strictly from training folds (zero validation leakage!)
            train_tourist_counts AS (
                SELECT
                    poi_id,
                    COUNT(*) AS train_tourist_visits
                FROM '{targ_path}'
                WHERE fold != {val_fold}
                GROUP BY poi_id
            ),
            -- Home/local visits strictly from training folds
            train_local_counts AS (
                SELECT
                    poi_id,
                    COUNT(*) AS train_local_visits
                FROM '{hist_path}'
                WHERE fold != {val_fold} AND is_home = TRUE
                GROUP BY poi_id
            ),
            base AS (
                SELECT
                    p.poi_id,
                    p.region_id,
                    p.venue_schema,
                    p.is_recommendable,
                    p.has_google_rating,
                    -- Bayesian smoothed rating (prior weight m = 25 reviews)
                    (COALESCE(p.google_rating, gr.mean_r) * p.google_num_reviews + gr.mean_r * 25.0)
                        / (p.google_num_reviews + 25.0) AS bayesian_rating,
                    LN(1.0 + p.google_num_reviews) AS log_google_reviews,
                    LN(1.0 + COALESCE(pc.checkins, 0)) AS log_n_checkins,
                    LN(1.0 + COALESCE(pc.users, 0)) AS log_n_users,
                    COALESCE(tc.train_tourist_visits, 0) AS train_tourist_visits,
                    LN(1.0 + COALESCE(tc.train_tourist_visits, 0)) AS log_train_tourist_visits,
                    -- Tourist-vs-local ratio (high = iconic destination spot; low = local errand spot)
                    (COALESCE(tc.train_tourist_visits, 0) + 1.0)
                        / (COALESCE(tc.train_tourist_visits, 0) + COALESCE(lc.train_local_visits, 0) + 5.0) AS tourist_ratio,
                    -- Approximate Euclidean km from city centroid
                    SQRT(
                        POW((p.lat - cc.center_lat) * 111.0, 2) +
                        POW((p.lon - cc.center_lon) * 111.0 * COS(RADIANS(cc.center_lat)), 2)
                    ) AS dist_to_center_km,
                    COALESCE(cs.city_supply_share, 0.0) AS dest_cat_supply_share,
                    COALESCE(cs.city_total_pois, 1) AS dest_city_total_pois,
                    -- Popularity rank within destination city (using only training tourist visits + prior)
                    PERCENT_RANK() OVER (
                        PARTITION BY p.region_id
                        ORDER BY COALESCE(tc.train_tourist_visits, 0) DESC, COALESCE(pc.checkins, 0) DESC
                    ) AS city_pop_pct_rank
                FROM '{pois_path}' p
                LEFT JOIN training_poi_counts pc ON p.poi_id = pc.poi_id
                CROSS JOIN global_rating gr
                LEFT JOIN city_center cc ON p.region_id = cc.region_id
                LEFT JOIN train_tourist_counts tc ON p.poi_id = tc.poi_id
                LEFT JOIN train_local_counts lc ON p.poi_id = lc.poi_id
                LEFT JOIN '{supply_out}' cs
                    ON p.region_id = cs.region_id AND p.venue_schema = cs.venue_schema
            )
            SELECT * FROM base
        ) TO '{poi_stats_out}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """)

    print("[Person 1 - 3/3] Computing Multi-City Opportunity-Normalized Taste (`feat_user_locality_taste.parquet`)...")
    # For each trip, compare what categories the user chose across ALL prior cities
    # against what those cities actually offered (supply share).
    con.execute(f"""
        COPY (
            WITH trip_cats AS (
                SELECT
                    h.trip_id,
                    h.venue_schema,
                    COUNT(*) AS user_cat_visits,
                    SUM(CASE WHEN h.is_home THEN 0 ELSE 1 END) AS user_prior_travel_cat_visits
                FROM '{hist_path}' h
                GROUP BY h.trip_id, h.venue_schema
            ),
            trip_totals AS (
                SELECT
                    trip_id,
                    COUNT(*) AS total_hist_visits,
                    COUNT(DISTINCT venue_schema) AS user_cat_diversity
                FROM '{hist_path}'
                GROUP BY trip_id
            ),
            -- Average supply share of each category across the exact cities this user previously visited
            trip_cities AS (
                SELECT DISTINCT trip_id, source_region_id
                FROM '{hist_path}'
            ),
            user_opportunity AS (
                SELECT
                    tc.trip_id,
                    cs.venue_schema,
                    AVG(cs.city_supply_share) AS avg_hist_supply_share,
                    MAX(cs.city_cat_pois) AS max_hist_cat_pois
                FROM trip_cities tc
                JOIN '{supply_out}' cs ON tc.source_region_id = cs.region_id
                GROUP BY tc.trip_id, cs.venue_schema
            )
            SELECT
                uo.trip_id,
                uo.venue_schema,
                COALESCE(c.user_cat_visits, 0) AS user_cat_visits,
                COALESCE(c.user_prior_travel_cat_visits, 0) AS user_prior_travel_cat_visits,
                CAST(COALESCE(c.user_cat_visits, 0) AS DOUBLE) / tt.total_hist_visits AS user_cat_share,
                uo.avg_hist_supply_share,
                -- Opportunity-Normalized Lift: >1.0 means user actively sought this category relative to supply!
                (CAST(COALESCE(c.user_cat_visits, 0) AS DOUBLE) / tt.total_hist_visits)
                    / (uo.avg_hist_supply_share + 0.005) AS opportunity_lift,
                (uo.max_hist_cat_pois > 0) AS was_available_in_history,
                tt.user_cat_diversity
            FROM user_opportunity uo
            JOIN trip_totals tt ON uo.trip_id = tt.trip_id
            LEFT JOIN trip_cats c
                ON uo.trip_id = c.trip_id AND uo.venue_schema = c.venue_schema
            WHERE COALESCE(c.user_cat_visits, 0) > 0
        ) TO '{taste_out}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """)

    elapsed = time.perf_counter() - t0
    print(f"Done in {elapsed:.1f}s! Wrote Person 1 locality features to `{DATA_GOLD_DIR}`.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Person 1 locality & opportunity-normalized features.")
    parser.add_argument("--val-fold", type=int, default=0, help="Validation fold held out from tourist count stats")
    args = parser.parse_args()
    build_locality_features(val_fold=args.val_fold)


if __name__ == "__main__":
    main()
