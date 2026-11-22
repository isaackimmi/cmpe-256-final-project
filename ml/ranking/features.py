"""Validate Stage 1 inputs and assemble the same features for fitting and serving."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ml.config import N_FOLDS


CONTEXT_FEATURES = ("dest_month", "n_history_cities", "n_history_pois")
CANDIDATE_FEATURES = ("stage1_score", "stage1_rank", *CONTEXT_FEATURES)
SEMANTIC_FEATURES = ("sem_sim_mean", "sem_sim_max", "sem_sim_top3", "sem_stage1a_score")
OPTIONAL_FEATURES = (*SEMANTIC_FEATURES, "two_tower_score")
POI_DEFAULTS = {
    "bayesian_rating": 3.98,
    "has_google_rating": 0.0,
    "log_google_reviews": 0.0,
    "log_n_checkins": 0.0,
    "log_n_users": 0.0,
    "log_train_tourist_visits": 0.0,
    "tourist_ratio": 0.2,
    "dist_to_center_km": 5.0,
    "dest_cat_supply_share": 0.0,
    "dest_city_total_pois": 1.0,
    "city_pop_pct_rank": 0.5,
}
TASTE_DEFAULTS = {
    "user_cat_visits": 0.0,
    "user_prior_travel_cat_visits": 0.0,
    "user_cat_share": 0.0,
    "avg_hist_supply_share": 0.0,
    "opportunity_lift": 0.0,
    "was_available_in_history": 0.0,
    "user_cat_diversity": 1.0,
}
FEATURE_COLS = [*CANDIDATE_FEATURES, *POI_DEFAULTS, *TASTE_DEFAULTS]
CANDIDATE_SCHEMA_VERSION = 1
SEMANTIC_WEIGHTS = {"sem_sim_mean": 0.5, "sem_sim_top3": 0.5}
PREPROCESSING = {
    "poi_defaults": POI_DEFAULTS,
    "taste_defaults": TASTE_DEFAULTS,
    "missing_retrieval_signal": "NaN",
    "sem_stage1a_weights": SEMANTIC_WEIGHTS,
}
INTEGER_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
}


def feature_paths(gold_dir: Path) -> dict[str, Path]:
    return {
        "poi_catalog": gold_dir / "pois_clean.parquet",
        "poi_stats": gold_dir / "feat_poi_stats.parquet",
        "user_taste": gold_dir / "feat_user_locality_taste.parquet",
    }


def open_parquets(
    con: duckdb.DuckDBPyConnection,
    paths: dict[str, Path],
) -> dict[str, dict[str, str]]:
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing ranking inputs:\n  " + "\n  ".join(missing))

    schemas = {}
    for table, path in paths.items():
        relation = con.read_parquet(str(path))
        schemas[table] = dict(zip(relation.columns, map(str, relation.types), strict=True))
        relation.create_view(table)
    return schemas


def require_columns(schema: dict[str, str], table: str, *columns: str) -> None:
    missing = sorted(set(columns) - schema.keys())
    if missing:
        raise ValueError(f"{table} is missing required columns: {', '.join(missing)}")


def require_unique_keys(con: duckdb.DuckDBPyConnection, table: str, *keys: str) -> None:
    key_list = ", ".join(keys)
    any_null = " OR ".join(f"{key} IS NULL" for key in keys)
    if con.execute(f"""
        SELECT 1 FROM {table}
        GROUP BY {key_list}
        HAVING COUNT(*) > 1 OR {any_null}
        LIMIT 1
    """).fetchone():
        raise ValueError(f"{table} must have unique, non-null ({key_list}) keys.")


def validate_feature_sources(
    con: duckdb.DuckDBPyConnection, schemas: dict[str, dict[str, str]]
) -> None:
    require_columns(
        schemas["poi_catalog"], "poi_catalog", "poi_id", "region_id", "venue_schema", "is_recommendable"
    )
    require_columns(schemas["poi_stats"], "poi_stats", "poi_id", *POI_DEFAULTS)
    require_columns(schemas["user_taste"], "user_taste", "trip_id", "venue_schema", *TASTE_DEFAULTS)
    require_unique_keys(con, "poi_catalog", "poi_id")
    require_unique_keys(con, "poi_stats", "poi_id")
    require_unique_keys(con, "user_taste", "trip_id", "venue_schema")


def retrieval_expressions(schema: dict[str, str]) -> dict[str, str]:
    # DuckDB treats NaN as a distinct numeric value. Give NaN and Parquet null
    # the same missing-value semantics while preserving genuine zeros.
    expressions = {
        feature: f"NULLIF(c.{feature}::DOUBLE, 'NaN'::DOUBLE)"
        for feature in OPTIONAL_FEATURES if feature in schema
    }
    if SEMANTIC_WEIGHTS.keys() <= expressions.keys():
        derived = " + ".join(f"{weight} * {expressions[feature]}" for feature, weight in SEMANTIC_WEIGHTS.items())
        supplied = expressions.get("sem_stage1a_score")
        expressions["sem_stage1a_score"] = f"COALESCE({supplied}, {derived})" if supplied else derived
    return expressions


def audit_candidates(
    con: duckdb.DuckDBPyConnection, schema: dict[str, str], *, training: bool
) -> None:
    """Check candidate rows and record counts per trip without loading them into Python."""
    integer_columns = ["trip_id", "stage1_rank", *CONTEXT_FEATURES]
    if training or "fold" in schema:
        integer_columns.append("fold")
    if "user_id" in schema:
        integer_columns.append("user_id")
    text_columns = ["poi_id"]
    if "dest_region_id" in schema:
        text_columns.append("dest_region_id")
    numeric_columns = ["stage1_score", *(feature for feature in OPTIONAL_FEATURES if feature in schema)]
    require_columns(schema, "candidates", *integer_columns, *text_columns, "stage1_score")
    for column in integer_columns:
        if schema[column] not in INTEGER_TYPES:
            raise ValueError(f"candidates.{column} must be an integer, got {schema[column]}.")
    for column in text_columns:
        if schema[column] != "VARCHAR":
            raise ValueError(f"candidates.{column} must be a string, got {schema[column]}.")
    for column in numeric_columns:
        datatype = schema[column]
        if datatype not in INTEGER_TYPES | {"FLOAT", "DOUBLE"} and not datatype.startswith("DECIMAL("):
            raise ValueError(f"candidates.{column} must be numeric, got {datatype}.")

    context = [*CONTEXT_FEATURES, *(column for column in ("fold", "user_id", "dest_region_id") if column in schema)]
    any_null = " OR ".join(f"c.{column} IS NULL" for column in context)
    inconsistent = " OR ".join(f"MIN(c.{column}) <> MAX(c.{column})" for column in context)
    issues = {
        "Invalid trip_id or poi_id": "TRY_CAST(c.trip_id AS BIGINT) IS NULL OR NULLIF(TRIM(c.poi_id), '') IS NULL",
        "Invalid trip context": (
            f"{any_null} OR c.dest_month NOT BETWEEN 1 AND 12 "
            "OR c.n_history_cities < 0 OR c.n_history_pois < 0"
        ),
        "Invalid stage1_rank or stage1_score": (
            "c.stage1_rank IS NULL OR c.stage1_rank < 1 "
            "OR NOT COALESCE(isfinite(TRY_CAST(c.stage1_score AS FLOAT)), FALSE)"
        ),
        "Unknown or non-recommendable candidate POI": "p.is_recommendable IS DISTINCT FROM TRUE",
    }
    if "fold" in schema:
        issues["Candidate fold is out of range"] = f"c.fold NOT BETWEEN 0 AND {N_FOLDS - 1}"
    if training:
        issues["Candidate fold does not match the Gold trip"] = "t.trip_id IS NULL OR c.fold <> t.fold"
        issues["Candidate trip context does not match the Gold trip"] = " OR ".join(
            f"c.{column} IS DISTINCT FROM t.{column}" for column in context if column != "fold"
        )
        issues["Candidate POI is outside the trip destination"] = "p.region_id IS DISTINCT FROM t.dest_region_id"
    elif "dest_region_id" in schema:
        issues["Candidate POI is outside the trip destination"] = "p.region_id IS DISTINCT FROM c.dest_region_id"

    retrieval = retrieval_expressions(schema)
    for column in numeric_columns[1:]:
        signal = f"NULLIF(c.{column}::DOUBLE, 'NaN'::DOUBLE)"
        issues[f"Invalid {column}"] = (
            f"{signal} IS NOT NULL AND NOT COALESCE(isfinite(TRY_CAST({signal} AS FLOAT)), FALSE)"
        )
        if column in SEMANTIC_FEATURES:
            # The hybrid retriever normalizes user embeddings before storing them in float16.
            issues[f"Invalid {column}"] += f" OR ABS({signal}) > 1.001"
    if {"sem_sim_top3", "sem_sim_max"} <= retrieval.keys():
        issues["sem_sim_top3 exceeds sem_sim_max"] = (
            f"{retrieval['sem_sim_top3']} > {retrieval['sem_sim_max']} + 0.00001"
        )
    if "sem_stage1a_score" in schema and SEMANTIC_WEIGHTS.keys() <= retrieval.keys():
        expected = " + ".join(f"{weight} * {retrieval[feature]}" for feature, weight in SEMANTIC_WEIGHTS.items())
        issues["sem_stage1a_score does not match its components"] = (
            f"ABS(NULLIF(c.sem_stage1a_score::DOUBLE, 'NaN'::DOUBLE) - ({expected})) > 0.000001"
        )

    issue_case = "CASE " + " ".join(f"WHEN {check} THEN '{message}'" for message, check in issues.items()) + " END"
    fold = "MIN(c.fold)" if "fold" in schema else "NULL::BIGINT"
    trip_join = "LEFT JOIN trips t ON c.trip_id = t.trip_id" if training else ""
    missing_counts = "".join(
        f", COUNT(*) FILTER (WHERE {expression} IS NULL) AS missing_{feature}"
        for feature, expression in retrieval.items()
    )
    con.execute(f"""
        CREATE TEMP TABLE candidate_groups AS
        SELECT c.trip_id, {fold} AS fold, COUNT(*) AS n_candidates,
            COALESCE(MAX({issue_case}), CASE
                WHEN COUNT(DISTINCT c.poi_id) <> COUNT(*) THEN 'Duplicate (trip_id, poi_id) candidate'
                WHEN {inconsistent} THEN 'Inconsistent context within a trip'
            END) AS issue
            {missing_counts}
        FROM candidates c
        LEFT JOIN poi_catalog p ON c.poi_id = p.poi_id
        {trip_join}
        GROUP BY c.trip_id
    """)
    failed = con.execute("SELECT trip_id, issue FROM candidate_groups WHERE issue IS NOT NULL LIMIT 1").fetchone()
    if failed:
        trip, issue = failed
        raise ValueError(f"{issue} (trip_id={trip}).")
    if not con.execute("SELECT 1 FROM candidate_groups LIMIT 1").fetchone():
        raise ValueError("No candidates found.")


def assemble_matrix(
    con: duckdb.DuckDBPyConnection,
    schema: dict[str, str],
    feature_cols: list[str],
    *,
    selected_trips: str | None = None,
    legacy_imputation: bool = False,
) -> pd.DataFrame:
    """Assemble one row per candidate. A selected training split also gets binary relevance."""
    expressions = {name: f"c.{name}" for name in CANDIDATE_FEATURES}
    expressions.update({name: f"COALESCE(ps.{name}::FLOAT, {default})" for name, default in POI_DEFAULTS.items()})
    expressions.update({name: f"COALESCE(ut.{name}::FLOAT, {default})" for name, default in TASTE_DEFAULTS.items()})
    retrieval = retrieval_expressions(schema)
    for name in OPTIONAL_FEATURES:
        expression = retrieval.get(name, "NULL")
        expressions[name] = f"COALESCE({expression}, 0.0)" if legacy_imputation else expression

    columns = ", ".join(f"CAST({expressions[name]} AS FLOAT) AS {name}" for name in feature_cols)
    label = ""
    split_joins = ""
    if selected_trips is not None:
        label = ", (y.poi_id IS NOT NULL)::TINYINT AS label"
        split_joins = f"""
            JOIN {selected_trips} s ON c.trip_id = s.trip_id
            LEFT JOIN targets y ON c.trip_id = y.trip_id AND c.poi_id = y.poi_id AND c.fold = y.fold
        """
    return con.execute(f"""
        SELECT c.trip_id::BIGINT AS trip_id, c.poi_id {label}, {columns}
        FROM candidates c
        {split_joins}
        JOIN poi_catalog p ON c.poi_id = p.poi_id
        LEFT JOIN poi_stats ps ON c.poi_id = ps.poi_id
        LEFT JOIN user_taste ut ON c.trip_id = ut.trip_id AND p.venue_schema = ut.venue_schema
        ORDER BY c.trip_id, c.stage1_rank, c.poi_id
    """).df()
