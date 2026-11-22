"""Reload a Stage 2 ranker and return ranked recommendations without labels."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.config import DATA_GOLD_DIR
from ml.ranking.features import (
    CANDIDATE_SCHEMA_VERSION,
    FEATURE_COLS,
    OPTIONAL_FEATURES,
    PREPROCESSING,
    assemble_matrix,
    audit_candidates,
    feature_paths,
    open_parquets,
    require_columns,
    validate_feature_sources,
)


MODEL_FORMAT_VERSION = 1


def load_ranker(model_path: Path) -> dict:
    """Load a trusted joblib file and verify its feature and preprocessing metadata."""
    artifact = joblib.load(model_path)
    if not isinstance(artifact, dict) or not isinstance(artifact.get("model"), lgb.LGBMRanker):
        raise ValueError("Expected a Stage 2 LightGBM ranker artifact.")
    features = artifact.get("features")
    if (
        not isinstance(features, list)
        or features != artifact["model"].feature_name_
        or not set(features) <= set(FEATURE_COLS + list(OPTIONAL_FEATURES))
    ):
        raise ValueError("Model feature names and ordering do not match the artifact schema.")

    version = artifact.get("format_version", 0)
    if version == 0:
        return {**artifact, "format_version": 0, "model_version": model_path.stem}
    if (
        version != MODEL_FORMAT_VERSION
        or artifact.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION
        or artifact.get("preprocessing") != PREPROCESSING
        or not artifact.get("model_version")
    ):
        raise ValueError("Unsupported ranker artifact format or preprocessing schema.")
    return artifact


def predict_scores(model: lgb.LGBMRanker, matrix: pd.DataFrame, features: list[str]) -> np.ndarray:
    scores = np.asarray(model.predict(matrix[features], validate_features=True), dtype=np.float64)
    if scores.shape != (len(matrix),) or not np.isfinite(scores).all():
        raise ValueError("Ranker did not return one finite score per candidate.")
    return scores


def top_ranked_candidates(predictions: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
    """Order by descending score within a trip, breaking ties the evaluator's way."""
    if top_k < 1:
        raise ValueError("top_k must be positive.")
    ordered = predictions.sort_values(["trip_id", "score", "poi_id"], ascending=[True, False, True])
    ranked = ordered.groupby("trip_id", sort=False).head(top_k).copy()
    ranked["rank"] = ranked.groupby("trip_id", sort=False).cumcount() + 1
    return ranked.reset_index(drop=True)


def rank_candidates(
    candidates_path: Path,
    model_path: Path,
    *,
    gold_dir: Path | None = None,
    trip_id: int | None = None,
    top_k: int = 10,
) -> pd.DataFrame:
    """Score one trip or a batch of Stage 1 candidates using the saved feature order."""
    artifact = load_ranker(model_path)
    features = artifact["features"]
    with duckdb.connect() as con:
        schemas = open_parquets(
            con, {"candidate_source": candidates_path, **feature_paths(gold_dir or DATA_GOLD_DIR)}
        )
        schema = schemas["candidate_source"]
        require_columns(schema, "candidates", "trip_id")
        if trip_id is None:
            con.execute("CREATE TEMP VIEW candidates AS SELECT * FROM candidate_source")
        else:
            con.execute(
                "CREATE TEMP TABLE candidates AS SELECT * FROM candidate_source WHERE trip_id = ?", [trip_id]
            )
        validate_feature_sources(con, schemas)
        audit_candidates(con, schema, training=False)
        matrix = assemble_matrix(con, schema, features, legacy_imputation=artifact["format_version"] == 0)
        predictions = matrix[["trip_id", "poi_id"]].assign(
            score=predict_scores(artifact["model"], matrix, features),
            model_version=artifact["model_version"],
        )
        con.register("ranked", top_ranked_candidates(predictions, top_k=top_k))
        name = "p.name" if "name" in schemas["poi_catalog"] else "NULL::VARCHAR"
        return con.execute(f"""
            SELECT r.trip_id, r.rank, r.poi_id, r.score, r.model_version,
                {name} AS name, p.venue_schema, p.region_id AS dest_region_id
            FROM ranked r
            JOIN poi_catalog p ON r.poi_id = p.poi_id
            ORDER BY r.trip_id, r.rank
        """).df()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True, help="A trusted Stage 2 joblib artifact")
    parser.add_argument("--gold-dir", type=Path, default=DATA_GOLD_DIR)
    parser.add_argument("--trip-id", type=int, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    try:
        ranking = rank_candidates(
            args.candidates, args.model, gold_dir=args.gold_dir, trip_id=args.trip_id, top_k=args.top_k
        )
    except (OSError, ValueError, duckdb.Error) as exc:
        parser.exit(1, f"Stage 2 inference: {exc}\n")
    print(ranking.to_string(index=False))


if __name__ == "__main__":
    main()
