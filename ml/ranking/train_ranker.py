"""Person 3 Track: Stage 2 LightGBM LambdaRank Re-Ranker joining Person 1 + Person 2 features.

North Star Metric: NDCG@10 & Recall@10 (measured via `python -m ml.evaluate`).

Usage:
    .venv/bin/python -m ml.ranking.train_ranker \\
        --candidates data/gold/candidates_popularity_top100_fold0.parquet \\
        --val-fold 0 \\
        --train-sample-trips 40000 \\
        --name lgbm_locality_v1

How to improve this module (Person 3 ideas):
    1. Swap `--candidates` to Person 2's semantic FAISS / Two-Tower Top-100 candidates!
    2. Add Optuna hyperparameter tuning (AutoML rubric: 15 pts) & log runs to MLflow.
    3. Train CatBoost YetiRank and ensemble-blend LightGBM + CatBoost + Two-Tower scores.
    4. Compute SHAP TreeExplainer values for Interpretability (20 pts) & error analysis.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
import duckdb
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.config import ARTIFACTS_DIR, DATA_GOLD_DIR, PREDS_DIR, RANDOM_SEED


FEATURE_COLS = [
    "stage1_score",
    "stage1_rank",
    "dest_month",
    "n_history_cities",
    "n_history_pois",
    "bayesian_rating",
    "has_google_rating",
    "log_google_reviews",
    "log_n_checkins",
    "log_n_users",
    "log_train_tourist_visits",
    "tourist_ratio",
    "dist_to_center_km",
    "dest_cat_supply_share",
    "dest_city_total_pois",
    "city_pop_pct_rank",
    # Person 1 Opportunity-Normalized Multi-City Taste Features!
    "user_cat_visits",
    "user_prior_travel_cat_visits",
    "user_cat_share",
    "avg_hist_supply_share",
    "opportunity_lift",
    "was_available_in_history",
    "user_cat_diversity",
]


def load_joined_matrix(
    candidates_path: Path,
    val_fold: int,
    train_sample_trips: int | None = 40_000,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Join Stage 1 candidates + Person 1 locality features + ground truth labels inside DuckDB."""
    con = duckdb.connect()
    poi_stats = DATA_GOLD_DIR / "feat_poi_stats.parquet"
    user_taste = DATA_GOLD_DIR / "feat_user_locality_taste.parquet"
    targets = DATA_GOLD_DIR / "trip_targets_exploded.parquet"

    # Detect any extra Stage 1 semantic/neural columns automatically (from Person 2!)
    cand_cols = [c[0] for c in con.sql(f"DESCRIBE SELECT * FROM '{candidates_path}'").fetchall()]
    extra_stage1_cols = [c for c in ("sem_sim_mean", "sem_sim_max", "sem_sim_top3", "two_tower_score") if c in cand_cols]
    extra_select = "".join(f", COALESCE(c.{col}, 0.0) AS {col}" for col in extra_stage1_cols)
    feature_cols = FEATURE_COLS + extra_stage1_cols

    sample_cte = (
        f"SELECT DISTINCT trip_id FROM '{candidates_path}' WHERE fold != {val_fold} "
        f"ORDER BY HASH(trip_id + {RANDOM_SEED}) LIMIT {train_sample_trips}"
        if train_sample_trips is not None
        else f"SELECT DISTINCT trip_id FROM '{candidates_path}' WHERE fold != {val_fold}"
    )

    def fetch_split(trip_filter_sql: str) -> pd.DataFrame:
        return con.sql(f"""
            WITH selected_trips AS ({trip_filter_sql})
            SELECT
                c.trip_id,
                c.poi_id,
                CASE WHEN t.poi_id IS NOT NULL THEN 1 ELSE 0 END AS label,
                CAST(c.stage1_score AS DOUBLE) AS stage1_score,
                CAST(c.stage1_rank AS DOUBLE) AS stage1_rank,
                CAST(c.dest_month AS DOUBLE) AS dest_month,
                CAST(c.n_history_cities AS DOUBLE) AS n_history_cities,
                CAST(c.n_history_pois AS DOUBLE) AS n_history_pois,
                COALESCE(ps.bayesian_rating, 3.98) AS bayesian_rating,
                CAST(COALESCE(ps.has_google_rating, FALSE) AS DOUBLE) AS has_google_rating,
                COALESCE(ps.log_google_reviews, 0.0) AS log_google_reviews,
                COALESCE(ps.log_n_checkins, 0.0) AS log_n_checkins,
                COALESCE(ps.log_n_users, 0.0) AS log_n_users,
                COALESCE(ps.log_train_tourist_visits, 0.0) AS log_train_tourist_visits,
                COALESCE(ps.tourist_ratio, 0.2) AS tourist_ratio,
                COALESCE(ps.dist_to_center_km, 5.0) AS dist_to_center_km,
                COALESCE(ps.dest_cat_supply_share, 0.0) AS dest_cat_supply_share,
                COALESCE(ps.dest_city_total_pois, 1.0) AS dest_city_total_pois,
                COALESCE(ps.city_pop_pct_rank, 0.5) AS city_pop_pct_rank,
                COALESCE(ut.user_cat_visits, 0.0) AS user_cat_visits,
                COALESCE(ut.user_prior_travel_cat_visits, 0.0) AS user_prior_travel_cat_visits,
                COALESCE(ut.user_cat_share, 0.0) AS user_cat_share,
                COALESCE(ut.avg_hist_supply_share, 0.0) AS avg_hist_supply_share,
                COALESCE(ut.opportunity_lift, 0.0) AS opportunity_lift,
                CAST(COALESCE(ut.was_available_in_history, FALSE) AS DOUBLE) AS was_available_in_history,
                COALESCE(ut.user_cat_diversity, 1.0) AS user_cat_diversity
                {extra_select}
            FROM '{candidates_path}' c
            JOIN selected_trips st ON c.trip_id = st.trip_id
            LEFT JOIN '{poi_stats}' ps ON c.poi_id = ps.poi_id
            LEFT JOIN '{user_taste}' ut
                ON c.trip_id = ut.trip_id AND ps.venue_schema = ut.venue_schema
            LEFT JOIN '{targets}' t
                ON c.trip_id = t.trip_id AND c.poi_id = t.poi_id
            ORDER BY c.trip_id, c.stage1_rank
        """).df()

    train_df = fetch_split(sample_cte)
    val_df = fetch_split(f"SELECT DISTINCT trip_id FROM '{candidates_path}' WHERE fold = {val_fold}")
    return train_df, val_df, feature_cols


def train_and_predict(
    candidates_path: Path,
    val_fold: int = 0,
    train_sample_trips: int | None = 40_000,
    name: str = "lgbm_locality_v1",
) -> Path:
    t0 = time.perf_counter()
    print(f"[Person 3] Joining Stage 1 candidates + Person 1 locality features...")
    train_df, val_df, feature_cols = load_joined_matrix(candidates_path, val_fold, train_sample_trips)

    # LightGBM LambdaRank requires query group sizes matching consecutive trip_id blocks
    # Keep only training trips that have at least 1 positive hit in the candidate list
    pos_trips = train_df.groupby("trip_id")["label"].sum()
    valid_train_ids = pos_trips[pos_trips > 0].index
    train_df = train_df[train_df["trip_id"].isin(valid_train_ids)].reset_index(drop=True)

    train_groups = train_df.groupby("trip_id", sort=False).size().to_numpy()
    val_groups = val_df.groupby("trip_id", sort=False).size().to_numpy()

    print(
        f"[Person 3] Training LightGBM LambdaRank on {len(train_groups):,} trips "
        f"({len(train_df):,} rows, {len(feature_cols)} features)..."
    )

    model = lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        ndcg_eval_at=[10],
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=63,
        subsample_for_bin=100_000,
        colsample_bytree=0.8,
        subsample=0.8,
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    model.fit(
        train_df[feature_cols],
        train_df["label"],
        group=train_groups,
        eval_set=[(val_df[feature_cols], val_df["label"])],
        eval_group=[val_groups],
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )

    val_scores = model.predict(val_df[feature_cols])
    PREDS_DIR.mkdir(parents=True, exist_ok=True)
    preds_out = PREDS_DIR / f"{name}_fold{val_fold}.parquet"
    pd.DataFrame({
        "trip_id": val_df["trip_id"].to_numpy(),
        "poi_id": val_df["poi_id"].to_numpy(),
        "score": val_scores.astype(np.float64),
    }).to_parquet(preds_out, index=False)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    model_out = ARTIFACTS_DIR / f"{name}_fold{val_fold}.joblib"
    joblib.dump({"model": model, "features": feature_cols}, model_out)

    # Print Top-10 features by gain for quick interpretability & team feedback
    imp = pd.Series(model.booster_.feature_importance(importance_type="gain"), index=feature_cols)
    print(f"\n[Person 3] Finished in {time.perf_counter()-t0:.1f}s! Top 10 Features by Gain:")
    for feat, gain in imp.sort_values(ascending=False).head(10).items():
        print(f"  {feat:30s}: {gain:,.1f}")
    print(f"\nSaved model -> {model_out}")
    print(f"Saved preds -> {preds_out}")
    return preds_out


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Person 3 Stage 2 LightGBM LambdaRanker.")
    parser.add_argument(
        "--candidates",
        type=Path,
        default=DATA_GOLD_DIR / "candidates_popularity_top100_fold0.parquet",
    )
    parser.add_argument("--val-fold", type=int, default=0)
    parser.add_argument("--train-sample-trips", type=int, default=40_000)
    parser.add_argument("--name", type=str, default="lgbm_locality_v1")
    args = parser.parse_args()
    train_and_predict(
        candidates_path=args.candidates,
        val_fold=args.val_fold,
        train_sample_trips=args.train_sample_trips,
        name=args.name,
    )


if __name__ == "__main__":
    main()
