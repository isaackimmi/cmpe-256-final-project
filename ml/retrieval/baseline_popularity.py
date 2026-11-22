"""Working Stage 1 & Baseline Retriever: Destination City Tourist Popularity.

Generates Top-100 candidate POIs per trip using strictly training-fold tourist popularity
(zero validation leakage!). Serves TWO purposes:
  1. Immediately establishes Leaderboard Entry #1 (`baseline_popularity_v1`).
  2. Provides a ready-to-use `candidates_top100.parquet` so Person 3 can train LightGBM
     on Day 1 while Person 2 builds Sentence-Transformer + FAISS + Two-Tower retrieval!

Usage:
    .venv/bin/python -m ml.retrieval.baseline_popularity --val-fold 0 --top-k 100
"""

from __future__ import annotations

import argparse
import time
import duckdb

from ml.config import DATA_GOLD_DIR, DEFAULT_TOP_K, PREDS_DIR


def run_popularity_baseline(val_fold: int = 0, top_k: int = DEFAULT_TOP_K, all_folds_for_training: bool = True) -> None:
    t0 = time.perf_counter()
    PREDS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    pois_path = DATA_GOLD_DIR / "pois_clean.parquet"
    trips_path = DATA_GOLD_DIR / "trips_multicity.parquet"
    targ_path = DATA_GOLD_DIR / "trip_targets_exploded.parquet"

    val_preds_out = PREDS_DIR / f"baseline_popularity_fold{val_fold}.parquet"
    cands_out = DATA_GOLD_DIR / f"candidates_popularity_top{top_k}_fold{val_fold}.parquet"

    print(f"[Baseline] Computing Top-{top_k} destination POIs using train folds != {val_fold}...")
    con.execute(f"""
        CREATE TEMP TABLE city_top_pois AS
        WITH train_pop AS (
            SELECT poi_id, COUNT(*) AS train_tourist_visits
            FROM '{targ_path}'
            WHERE fold != {val_fold}
            GROUP BY poi_id
        ),
        scored AS (
            SELECT
                p.region_id AS dest_region_id,
                p.poi_id,
                CAST(COALESCE(tp.train_tourist_visits, 0) AS DOUBLE)
                    + 0.05 * LN(1.0 + p.google_num_reviews)
                    + 0.01 * COALESCE(p.google_rating, 3.98) AS stage1_score,
                ROW_NUMBER() OVER (
                    PARTITION BY p.region_id
                    ORDER BY COALESCE(tp.train_tourist_visits, 0) DESC,
                             p.google_num_reviews DESC,
                             p.n_checkins DESC,
                             p.poi_id ASC
                ) AS stage1_rank
            FROM '{pois_path}' p
            LEFT JOIN train_pop tp ON p.poi_id = tp.poi_id
            WHERE p.is_recommendable = TRUE
        )
        SELECT dest_region_id, poi_id, stage1_score, stage1_rank
        FROM scored
        WHERE stage1_rank <= {top_k};
    """)

    # 1. Validation fold predictions for `ml/evaluate.py`
    con.execute(f"""
        COPY (
            SELECT
                t.trip_id,
                c.poi_id,
                c.stage1_score AS score
            FROM '{trips_path}' t
            JOIN city_top_pois c ON t.dest_region_id = c.dest_region_id
            WHERE t.fold = {val_fold}
        ) TO '{val_preds_out}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """)

    # 2. Candidate table (all trips, tagged with fold) so Person 3 can train/val LightGBM right away
    fold_clause = "" if all_folds_for_training else f"WHERE t.fold = {val_fold}"
    con.execute(f"""
        COPY (
            SELECT
                t.trip_id,
                t.user_id,
                t.fold,
                t.dest_region_id,
                t.dest_month,
                t.n_history_cities,
                t.n_history_pois,
                c.poi_id,
                c.stage1_score,
                c.stage1_rank
            FROM '{trips_path}' t
            JOIN city_top_pois c ON t.dest_region_id = c.dest_region_id
            {fold_clause}
        ) TO '{cands_out}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """)

    elapsed = time.perf_counter() - t0
    print(f"Done in {elapsed:.1f}s!")
    print(f"  Val predictions: {val_preds_out}")
    print(f"  Stage 1 cands:   {cands_out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stage 1 Popularity Baseline.")
    parser.add_argument("--val-fold", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    args = parser.parse_args()
    run_popularity_baseline(val_fold=args.val_fold, top_k=args.top_k)


if __name__ == "__main__":
    main()
