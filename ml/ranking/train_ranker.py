"""Train the Stage 2 LightGBM LambdaRank reranker on all-fold Stage 1 candidates."""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import joblib
import lightgbm as lgb
import pandas as pd

from ml.config import ARTIFACTS_DIR, DATA_GOLD_DIR, N_FOLDS, PREDS_DIR, RANDOM_SEED
from ml.ranking.features import (
    CANDIDATE_SCHEMA_VERSION,
    CONTEXT_FEATURES,
    FEATURE_COLS,
    OPTIONAL_FEATURES,
    PREPROCESSING,
    assemble_matrix,
    audit_candidates,
    feature_paths,
    open_parquets,
    require_columns,
    require_unique_keys,
    retrieval_expressions,
    validate_feature_sources,
)
from ml.ranking.inference import MODEL_FORMAT_VERSION, predict_scores


def _validate_training_sources(
    con: duckdb.DuckDBPyConnection, schemas: dict[str, dict[str, str]], val_fold: int
) -> None:
    require_columns(
        schemas["trips"], "trips", "trip_id", "user_id", "fold", "dest_region_id", "n_target_pois",
        *CONTEXT_FEATURES,
    )
    require_columns(schemas["cv_folds"], "cv_folds", "user_id", "fold")
    require_columns(schemas["targets"], "targets", "trip_id", "fold", "poi_id")
    require_columns(schemas["poi_stats"], "poi_stats", "train_tourist_visits")
    require_unique_keys(con, "trips", "trip_id")
    require_unique_keys(con, "cv_folds", "user_id")

    wrong_user_fold = con.execute(f"""
        SELECT t.trip_id FROM trips t
        LEFT JOIN cv_folds f ON t.user_id = f.user_id
        WHERE t.fold IS NULL OR t.fold NOT BETWEEN 0 AND {N_FOLDS - 1}
            OR t.fold IS DISTINCT FROM f.fold
        LIMIT 1
    """).fetchone()
    if wrong_user_fold:
        raise ValueError(f"Gold trip fold disagrees with cv_folds.parquet (trip_id={wrong_user_fold[0]}).")

    bad_target_group = con.execute("""
        WITH target_groups AS (
            SELECT y.trip_id, COUNT(*) AS n_targets, COUNT(DISTINCT y.poi_id) AS n_pois,
                COUNT(*) FILTER (WHERE y.fold IS DISTINCT FROM t.fold
                    OR p.is_recommendable IS DISTINCT FROM TRUE
                    OR p.region_id IS DISTINCT FROM t.dest_region_id) AS invalid_targets
            FROM targets y
            LEFT JOIN trips t ON y.trip_id = t.trip_id
            LEFT JOIN poi_catalog p ON y.poi_id = p.poi_id
            GROUP BY y.trip_id
        )
        SELECT COALESCE(t.trip_id, g.trip_id) FROM trips t
        FULL JOIN target_groups g ON t.trip_id = g.trip_id
        WHERE t.trip_id IS NULL OR t.n_target_pois IS NULL OR t.n_target_pois < 1
            OR g.n_targets IS DISTINCT FROM t.n_target_pois
            OR g.n_targets <> g.n_pois OR g.invalid_targets > 0
        LIMIT 1
    """).fetchone()
    if bad_target_group:
        raise ValueError(f"Gold targets have an invalid fold, POI, or count (trip_id={bad_target_group[0]}).")

    # The Person 1 Parquet has a common filename for all folds. Cross-check its
    # visit counts before using it so a stale table cannot leak validation visits.
    wrong_poi_stats = con.execute("""
        WITH expected AS (
            SELECT poi_id, COUNT(*) AS n_visits FROM targets WHERE fold <> ? GROUP BY poi_id
        )
        SELECT s.poi_id FROM poi_stats s
        LEFT JOIN expected e ON s.poi_id = e.poi_id
        WHERE s.train_tourist_visits IS DISTINCT FROM COALESCE(e.n_visits, 0)
        LIMIT 1
    """, [val_fold]).fetchone()
    if wrong_poi_stats:
        raise ValueError(
            f"feat_poi_stats.parquet does not match tourist counts outside held-out fold {val_fold}. "
            f"Rebuild it with python -m ml.features.build_locality_features --val-fold {val_fold}."
        )


def _print_input_audit(
    con: duckdb.DuckDBPyConnection, schema: dict[str, str], feature_cols: list[str]
) -> None:
    print("Candidate schema:", ", ".join(f"{name} {dtype}" for name, dtype in schema.items()))
    optional = [feature for feature in feature_cols if feature in OPTIONAL_FEATURES]
    missing_sql = "".join(
        f", COALESCE(SUM(missing_{feature}), 0)::BIGINT AS missing_{feature}" for feature in optional
    )
    summary = con.execute(f"""
        WITH gold_counts AS (SELECT fold, COUNT(*) AS gold_trips FROM trips GROUP BY fold)
        SELECT g.fold, g.gold_trips, COUNT(c.trip_id) AS candidate_trips,
            COALESCE(SUM(c.n_candidates), 0)::BIGINT AS rows,
            MIN(c.n_candidates) AS min_per_trip, MEDIAN(c.n_candidates) AS median_per_trip,
            MAX(c.n_candidates) AS max_per_trip,
            COUNT(*) FILTER (WHERE c.n_candidates >= 10) AS trips_with_10
            {missing_sql}
        FROM gold_counts g
        LEFT JOIN candidate_groups c ON g.fold = c.fold
        GROUP BY g.fold, g.gold_trips
        ORDER BY g.fold
    """).df()
    print(summary.to_string(index=False))


def _load_ranking_data(
    candidates_path: Path, val_fold: int, train_sample_trips: int | None, gold_dir: Path
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict]:
    if not 0 <= val_fold < N_FOLDS:
        raise ValueError(f"val_fold must be between 0 and {N_FOLDS - 1}.")
    if train_sample_trips is not None and train_sample_trips < 1:
        raise ValueError("train_sample_trips must be positive.")
    # The shared exporters stamp the held-out fold in the filename. The row
    # fold can match Gold even when the retrieval model held out the wrong fold.
    export = re.fullmatch(r"candidates_(?:hybrid|popularity)_top\d+_fold(\d+)", candidates_path.stem)
    if export and int(export[1]) != val_fold:
        raise ValueError(f"Candidate export held out fold {export[1]}, but --val-fold is {val_fold}.")

    paths = {
        "candidates": candidates_path,
        **feature_paths(gold_dir),
        "trips": gold_dir / "trips_multicity.parquet",
        "cv_folds": gold_dir / "cv_folds.parquet",
        "targets": gold_dir / "trip_targets_exploded.parquet",
    }
    with duckdb.connect() as con:
        schemas = open_parquets(con, paths)
        validate_feature_sources(con, schemas)
        _validate_training_sources(con, schemas, val_fold)
        schema = schemas["candidates"]
        audit_candidates(con, schema, training=True)
        retrieval = retrieval_expressions(schema)
        feature_cols = FEATURE_COLS + [feature for feature in OPTIONAL_FEATURES if feature in retrieval]
        _print_input_audit(con, schema, feature_cols)

        limit = "LIMIT ?" if train_sample_trips is not None else ""
        train_params = [val_fold, RANDOM_SEED]
        if train_sample_trips is not None:
            train_params.append(train_sample_trips)
        con.execute(f"""
            CREATE TEMP TABLE train_trips AS
            SELECT trip_id, fold FROM candidate_groups
            WHERE fold <> ?
            ORDER BY HASH(trip_id, ?), trip_id
            {limit}
        """, train_params)
        con.execute("""
            CREATE TEMP TABLE val_trips AS
            SELECT trip_id FROM candidate_groups WHERE fold = ?
        """, [val_fold])
        if not con.execute("SELECT 1 FROM train_trips LIMIT 1").fetchone():
            raise ValueError("No training candidates. Use an all-fold Stage 1 export to fit the ranker.")
        if not con.execute("SELECT 1 FROM val_trips LIMIT 1").fetchone():
            raise ValueError(f"No candidates for validation fold {val_fold}.")

        train_df = assemble_matrix(con, schema, feature_cols, selected_trips="train_trips")
        val_df = assemble_matrix(con, schema, feature_cols, selected_trips="val_trips")
        gold_targets = con.execute(
            "SELECT trip_id, n_target_pois FROM trips WHERE fold = ?", [val_fold]
        ).df().set_index("trip_id")["n_target_pois"]
        train_folds = [
            fold for (fold,) in con.execute("SELECT DISTINCT fold FROM train_trips ORDER BY fold").fetchall()
        ]

    retrieved_targets = val_df.groupby("trip_id")["label"].sum().reindex(gold_targets.index, fill_value=0)
    evaluation = {
        "fold": val_fold,
        "gold_trips": len(gold_targets),
        "trips_with_candidates": val_df["trip_id"].nunique(),
        "trips_with_retrieved_targets": int(retrieved_targets.gt(0).sum()),
        "candidate_recall": float((retrieved_targets / gold_targets).mean()),
    }
    return train_df, val_df, feature_cols, {"train_folds": train_folds, "evaluation": evaluation}


def load_joined_matrix(
    candidates_path: Path,
    val_fold: int,
    train_sample_trips: int | None = 40_000,
    *,
    gold_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Preserve the joined-matrix interface used by the ranking notebook."""
    train_df, val_df, feature_cols, _ = _load_ranking_data(
        candidates_path, val_fold, train_sample_trips, gold_dir or DATA_GOLD_DIR
    )
    return train_df, val_df, feature_cols


def train_and_predict(
    candidates_path: Path,
    val_fold: int = 0,
    train_sample_trips: int | None = 40_000,
    name: str = "lgbm_locality_v1",
    *,
    gold_dir: Path | None = None,
) -> Path:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ValueError("Experiment name must be a nonempty filename component.")

    start = time.perf_counter()
    train_df, val_df, feature_cols, audit = _load_ranking_data(
        candidates_path, val_fold, train_sample_trips, gold_dir or DATA_GOLD_DIR
    )

    # A LambdaRank query needs a positive/negative pair. Keep every validation
    # candidate, including trips with zero relevant hits, for the official scorer.
    train_summary = train_df.groupby("trip_id", sort=False)["label"].agg(["size", "sum"])
    rankable = train_summary["sum"].between(1, train_summary["size"] - 1)
    train_groups = train_summary.loc[rankable, "size"].to_numpy()
    if not len(train_groups):
        raise ValueError("No training trips contain both a relevant and an irrelevant candidate.")
    train_df = train_df[train_df["trip_id"].isin(train_summary.index[rankable])]
    excluded_trips = len(train_summary) - len(train_groups)
    print(
        f"Fitting LambdaRank on {len(train_groups):,} trips and {len(train_df):,} rows "
        f"(excluded {excluded_trips:,} trips without a positive/negative pair)."
    )
    print("Model features:", ", ".join(feature_cols))
    evaluation = audit["evaluation"]
    print(
        f"Fold {val_fold}: {evaluation['trips_with_candidates']:,}/{evaluation['gold_trips']:,} "
        f"trips have candidates, candidate recall = {evaluation['candidate_recall']:.5f}."
    )

    # Use a fixed tree budget so the official holdout is never used for early
    # stopping or choosing an iteration count.
    model = lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        lambdarank_truncation_level=13,
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=63,
        subsample_for_bin=100_000,
        colsample_bytree=0.8,
        random_state=RANDOM_SEED,
        n_jobs=-1,
        verbosity=-1,
    )
    model.fit(train_df[feature_cols], train_df["label"], group=train_groups, eval_at=(10,))

    predictions = val_df[["trip_id", "poi_id"]].assign(score=predict_scores(model, val_df, feature_cols))
    artifact = {
        "model": model,
        "features": feature_cols,
        "format_version": MODEL_FORMAT_VERSION,
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "model_version": name,
        "preprocessing": PREPROCESSING,
        "training": {
            "candidate_file": candidates_path.name,
            "folds_sampled": audit["train_folds"],
            "train_sample_trips": train_sample_trips,
            "trips_fitted": len(train_groups),
            "trips_without_pairs": excluded_trips,
            "rows_fitted": len(train_df),
            "lightgbm_version": lgb.__version__,
            "parameters": {**model.get_params(), "eval_at": [10]},
        },
        "evaluation": {**evaluation, "prediction_rows": len(predictions)},
    }

    stem = f"{name}_fold{val_fold}"
    PREDS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    preds_out = PREDS_DIR / f"{stem}.parquet"
    model_out = ARTIFACTS_DIR / f"{stem}.joblib"
    with TemporaryDirectory(dir=ARTIFACTS_DIR) as model_tmp, TemporaryDirectory(dir=PREDS_DIR) as preds_tmp:
        model_staging = Path(model_tmp) / model_out.name
        preds_staging = Path(preds_tmp) / preds_out.name
        joblib.dump(artifact, model_staging)
        predictions.to_parquet(preds_staging, index=False)
        model_staging.replace(model_out)
        preds_staging.replace(preds_out)

    importance = pd.Series(model.booster_.feature_importance(importance_type="gain"), index=feature_cols)
    print(f"Top features by gain ({time.perf_counter() - start:.1f}s):")
    print(importance.nlargest(10).to_string())
    print(f"Saved model: {model_out}")
    print(f"Saved predictions: {preds_out}")
    return preds_out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, help="All-fold Stage 1 candidate Parquet")
    parser.add_argument("--gold-dir", type=Path, default=DATA_GOLD_DIR)
    parser.add_argument("--val-fold", type=int, default=0, choices=range(N_FOLDS))
    parser.add_argument("--train-sample-trips", type=int, default=40_000)
    parser.add_argument("--name", default="lgbm_locality_v1")
    args = parser.parse_args()
    candidates = args.candidates or args.gold_dir / f"candidates_popularity_top100_fold{args.val_fold}.parquet"
    try:
        train_and_predict(candidates, args.val_fold, args.train_sample_trips, args.name, gold_dir=args.gold_dir)
    except (OSError, ValueError, duckdb.Error) as exc:
        parser.exit(1, f"Stage 2 training: {exc}\n")


if __name__ == "__main__":
    main()
