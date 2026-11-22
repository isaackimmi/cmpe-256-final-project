"""Training-user POI popularity shared by features and retrieval."""

from pathlib import Path

import duckdb

from ml.config import DATA_GOLD_DIR, DATA_RAW_DIR, N_FOLDS


def create_training_poi_counts(
    con: duckdb.DuckDBPyConnection,
    val_fold: int,
    *,
    raw_dir: Path = DATA_RAW_DIR,
    gold_dir: Path = DATA_GOLD_DIR,
) -> None:
    """Create connection-local `training_poi_counts` (poi_id, checkins, users).

    Only users outside val_fold contribute. An event is identified by user, POI,
    trail and timestamp. UNION removes repeated home histories and exact event
    copies across records/sides, while preserving genuine repeat visits. Dates
    identify events only; no chronological filtering is applied. POIs without
    training visits have no row; consumers must left-join and fill with zero.

    Counts cover the public travel_behaviors users, not the broader raw POI
    totals. Call independently for each fold; no shared feature file is read.
    """
    if not isinstance(val_fold, int) or not 0 <= val_fold < N_FOLDS:
        raise ValueError(f"val_fold must be an integer from 0 to {N_FOLDS - 1}")

    travel = str(raw_dir / "travel_behaviors.parquet").replace("'", "''")
    folds = str(gold_dir / "cv_folds.parquet").replace("'", "''")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE training_poi_counts AS
        WITH training_records AS (
            SELECT t.user_id, t.c_h, t.c_o
            FROM '{travel}' t
            JOIN '{folds}' f ON t.user_id = f.user_id
            WHERE f.fold != {val_fold}
        ), events AS (
            SELECT t.user_id, v.venue_id AS poi_id, v.trail_id, v.ts
            FROM training_records t, UNNEST(t.c_h) AS visits(v)
            UNION
            SELECT t.user_id, v.venue_id AS poi_id, v.trail_id, v.ts
            FROM training_records t, UNNEST(t.c_o) AS visits(v)
        )
        SELECT poi_id, COUNT(*) AS checkins, COUNT(DISTINCT user_id) AS users
        FROM events
        GROUP BY poi_id
    """)
