"""Automated pytest suite verifying TripWorld ML spine integrity, anti-leakage, and evaluation math."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from ml.config import DATA_GOLD_DIR, N_FOLDS
from ml.data_pipeline import FOLDS_SCHEMA, POIS_SCHEMA, TRIPS_SCHEMA


def _gold_ready() -> bool:
    return (DATA_GOLD_DIR / "trips_multicity.parquet").exists()


@pytest.mark.skipif(not _gold_ready(), reason="Run `python -m ml.data_pipeline` first")
def test_pandera_gold_schemas() -> None:
    pois = pd.read_parquet(
        DATA_GOLD_DIR / "pois_clean.parquet",
        columns=["poi_id", "region_id", "lat", "lon", "is_noise", "is_closed", "is_recommendable"],
    )
    POIS_SCHEMA.validate(pois)

    folds = pd.read_parquet(DATA_GOLD_DIR / "cv_folds.parquet")
    FOLDS_SCHEMA.validate(folds)
    assert set(folds["fold"].unique()) == set(range(N_FOLDS))

    trips = pd.read_parquet(
        DATA_GOLD_DIR / "trips_multicity.parquet",
        columns=[
            "trip_id", "user_id", "fold", "home_region_id", "dest_region_id",
            "dest_month", "n_history_cities", "n_history_pois", "n_target_pois",
        ],
    )
    TRIPS_SCHEMA.validate(trips)


@pytest.mark.skipif(not _gold_ready(), reason="Run `python -m ml.data_pipeline` first")
def test_zero_history_target_leakage() -> None:
    con = duckdb.connect()
    hist = DATA_GOLD_DIR / "trip_history_exploded.parquet"
    targ = DATA_GOLD_DIR / "trip_targets_exploded.parquet"
    trips = DATA_GOLD_DIR / "trips_multicity.parquet"

    poi_overlap = con.sql(f"""
        SELECT COUNT(*) FROM '{hist}' h
        JOIN '{targ}' t ON h.trip_id = t.trip_id AND h.poi_id = t.poi_id
    """).fetchall()[0][0]
    assert poi_overlap == 0

    city_overlap = con.sql(f"""
        SELECT COUNT(*) FROM '{hist}' h
        JOIN '{trips}' tr ON h.trip_id = tr.trip_id
        WHERE h.source_region_id = tr.dest_region_id
    """).fetchall()[0][0]
    assert city_overlap == 0

    multi_fold_users = con.sql(f"""
        SELECT COUNT(*) FROM (
            SELECT user_id FROM '{trips}' GROUP BY user_id HAVING COUNT(DISTINCT fold) > 1
        )
    """).fetchall()[0][0]
    assert multi_fold_users == 0


@pytest.mark.skipif(not _gold_ready(), reason="Run `python -m ml.data_pipeline` first")
def test_targets_are_only_recommendable() -> None:
    con = duckdb.connect()
    bad_targets = con.sql(f"""
        SELECT COUNT(*)
        FROM '{DATA_GOLD_DIR}/trip_targets_exploded.parquet' t
        JOIN '{DATA_GOLD_DIR}/pois_clean.parquet' p ON t.poi_id = p.poi_id
        WHERE p.is_recommendable = FALSE
    """).fetchall()[0][0]
    assert bad_targets == 0
