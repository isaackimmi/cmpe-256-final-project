"""Shared Official Grader & Leaderboard Recorder for all 3 teammates.

Every model (Stage 1 retrieval OR Stage 2 ranking) outputs a Parquet file with:
    - trip_id (BIGINT)
    - poi_id  (VARCHAR)
    - score   (DOUBLE / FLOAT, higher = better)

Usage:
    .venv/bin/python -m ml.evaluate \\
        --preds data/preds/baseline_popularity.parquet \\
        --name "baseline_popularity_v1" \\
        --author "spine" \\
        --fold 0 \\
        --notes "Destination popularity among recommendable POIs"
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

from ml.config import DATA_GOLD_DIR, LEADERBOARD_PATH, REPORTS_DIR


def evaluate_predictions(
    preds_path: Path,
    fold: int | None = 0,
    max_k: int = 100,
) -> dict[str, float]:
    """Compute Recall@10/20/100, NDCG@10, MRR@10, HitRate@10, Coverage@10, Diversity@10."""
    con = duckdb.connect()
    trips_path = DATA_GOLD_DIR / "trips_multicity.parquet"
    targets_path = DATA_GOLD_DIR / "trip_targets_exploded.parquet"
    pois_path = DATA_GOLD_DIR / "pois_clean.parquet"

    fold_filter = f"WHERE fold = {fold}" if fold is not None else ""

    # Rank predictions per trip_id (top max_k) inside DuckDB for speed
    con.execute(f"""
        CREATE TEMP TABLE eval_trips AS
        SELECT trip_id, n_target_pois, dest_region_id
        FROM '{trips_path}'
        {fold_filter};

        CREATE TEMP TABLE eval_targets AS
        SELECT t.trip_id, t.poi_id
        FROM '{targets_path}' t
        JOIN eval_trips e ON t.trip_id = e.trip_id;

        CREATE TEMP TABLE ranked_preds AS
        SELECT
            trip_id,
            poi_id,
            ROW_NUMBER() OVER (PARTITION BY trip_id ORDER BY score DESC, poi_id ASC) AS rank
        FROM (
            SELECT p.trip_id, p.poi_id, MAX(p.score) AS score
            FROM '{preds_path}' p
            JOIN eval_trips e ON p.trip_id = e.trip_id
            GROUP BY p.trip_id, p.poi_id
        )
        QUALIFY rank <= {max_k};
    """)

    n_trips = con.sql("SELECT COUNT(*) FROM eval_trips").fetchall()[0][0]
    if n_trips == 0:
        raise ValueError(f"No evaluation trips found for fold={fold}")

    # Exact DCG, IDCG, Recall@10/20/100, HitRate@10, MRR@10 in one fast SQL pass
    metrics_row = con.sql("""
        WITH hits AS (
            SELECT
                rp.trip_id,
                rp.rank,
                CASE WHEN et.poi_id IS NOT NULL THEN 1 ELSE 0 END AS is_hit
            FROM ranked_preds rp
            LEFT JOIN eval_targets et
              ON rp.trip_id = et.trip_id AND rp.poi_id = et.poi_id
        ),
        per_trip AS (
            SELECT
                e.trip_id,
                e.n_target_pois,
                COALESCE(SUM(CASE WHEN h.rank <= 10 THEN h.is_hit ELSE 0 END), 0) AS hits_10,
                COALESCE(SUM(CASE WHEN h.rank <= 20 THEN h.is_hit ELSE 0 END), 0) AS hits_20,
                COALESCE(SUM(CASE WHEN h.rank <= 100 THEN h.is_hit ELSE 0 END), 0) AS hits_100,
                COALESCE(SUM(CASE WHEN h.rank <= 10 AND h.is_hit = 1 THEN 1.0 / LOG2(h.rank + 1.0) ELSE 0.0 END), 0.0) AS dcg_10,
                MIN(CASE WHEN h.rank <= 10 AND h.is_hit = 1 THEN h.rank ELSE NULL END) AS first_hit_10
            FROM eval_trips e
            LEFT JOIN hits h ON e.trip_id = h.trip_id
            GROUP BY e.trip_id, e.n_target_pois
        ),
        idcg_lookup AS (
            SELECT
                k,
                SUM(1.0 / LOG2(pos + 1.0)) AS idcg
            FROM generate_series(1, 10) AS _(k),
                 generate_series(1, 10) AS __(pos)
            WHERE pos <= k
            GROUP BY k
        )
        SELECT
            AVG(CAST(pt.hits_10 AS DOUBLE) / pt.n_target_pois) AS recall_10,
            AVG(CAST(pt.hits_20 AS DOUBLE) / pt.n_target_pois) AS recall_20,
            AVG(CAST(pt.hits_100 AS DOUBLE) / pt.n_target_pois) AS recall_100,
            AVG(pt.dcg_10 / il.idcg) AS ndcg_10,
            AVG(CASE WHEN pt.hits_10 > 0 THEN 1.0 ELSE 0.0 END) AS hitrate_10,
            AVG(CASE WHEN pt.first_hit_10 IS NOT NULL THEN 1.0 / pt.first_hit_10 ELSE 0.0 END) AS mrr_10
        FROM per_trip pt
        JOIN idcg_lookup il ON LEAST(pt.n_target_pois, 10) = il.k
    """).fetchall()[0]

    # Catalog coverage@10 and category diversity@10
    cov_div = con.sql(f"""
        WITH top10 AS (
            SELECT rp.trip_id, rp.poi_id, p.venue_schema
            FROM ranked_preds rp
            LEFT JOIN '{pois_path}' p ON rp.poi_id = p.poi_id
            WHERE rp.rank <= 10
        ),
        div_per_trip AS (
            SELECT trip_id, COUNT(DISTINCT venue_schema) AS n_cats
            FROM top10
            GROUP BY trip_id
        ),
        total_rec_pois AS (
            SELECT COUNT(*) AS total
            FROM '{pois_path}'
            WHERE is_recommendable = TRUE
              AND region_id IN (SELECT DISTINCT dest_region_id FROM eval_trips)
        )
        SELECT
            CAST((SELECT COUNT(DISTINCT poi_id) FROM top10) AS DOUBLE) / NULLIF((SELECT total FROM total_rec_pois), 0) AS coverage_10,
            COALESCE((SELECT AVG(n_cats) FROM div_per_trip), 0.0) AS diversity_10
    """).fetchall()[0]

    return {
        "n_trips": int(n_trips),
        "ndcg_10": round(float(metrics_row[3] or 0.0), 5),
        "recall_10": round(float(metrics_row[0] or 0.0), 5),
        "recall_20": round(float(metrics_row[1] or 0.0), 5),
        "recall_100": round(float(metrics_row[2] or 0.0), 5),
        "hitrate_10": round(float(metrics_row[4] or 0.0), 5),
        "mrr_10": round(float(metrics_row[5] or 0.0), 5),
        "coverage_10": round(float(cov_div[0] or 0.0), 5),
        "diversity_10": round(float(cov_div[1] or 0.0), 3),
    }


def append_leaderboard(
    name: str,
    author: str,
    fold_label: str,
    metrics: dict[str, float],
    notes: str = "",
) -> pd.DataFrame:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "experiment": name,
        "author": author,
        "fold": fold_label,
        **metrics,
        "notes": notes,
    }
    new_df = pd.DataFrame([row])
    if LEADERBOARD_PATH.exists():
        df = pd.read_csv(LEADERBOARD_PATH)
        df = pd.concat([df, new_df], ignore_index=True)
    else:
        df = new_df
    df.to_csv(LEADERBOARD_PATH, index=False)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate TripWorld predictions and log to leaderboard.")
    parser.add_argument("--preds", type=Path, required=True, help="Parquet file with (trip_id, poi_id, score)")
    parser.add_argument("--name", type=str, required=True, help="Experiment name")
    parser.add_argument("--author", type=str, default="team", help="Teammate name/track")
    parser.add_argument("--fold", type=int, default=0, help="Validation fold (0-4), ignored if --all-folds")
    parser.add_argument("--all-folds", action="store_true", help="Evaluate across all 5 folds")
    parser.add_argument("--notes", type=str, default="", help="Short note on what changed")
    parser.add_argument("--no-log", action="store_true", help="Print metrics without appending to leaderboard.csv")
    args = parser.parse_args()

    fold = None if args.all_folds else args.fold
    fold_label = "all_5_folds" if args.all_folds else f"fold_{args.fold}"
    metrics = evaluate_predictions(args.preds, fold=fold)

    print(f"\n=== Evaluation: {args.name} ({fold_label}, {metrics['n_trips']:,} trips) ===")
    for k, v in metrics.items():
        if k != "n_trips":
            print(f"  {k:14s}: {v}")

    if not args.no_log:
        lb = append_leaderboard(args.name, args.author, fold_label, metrics, args.notes)
        print(f"\nUpdated {LEADERBOARD_PATH} (top 5 by NDCG@10):")
        cols = ["experiment", "author", "fold", "ndcg_10", "recall_10", "recall_100", "mrr_10", "diversity_10"]
        print(lb.sort_values("ndcg_10", ascending=False)[cols].head(5).to_string(index=False))


if __name__ == "__main__":
    main()
