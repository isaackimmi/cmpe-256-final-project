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


@pytest.mark.parametrize("dirty", [False, True])
def test_audit_raw_inputs(tmp_path, dirty) -> None:
    """Count issues without join multiplication, modifying data, or writing outputs."""
    from ml.data_pipeline import audit_raw_inputs

    raw = tmp_path / "raw's data"
    (raw / "metadata").mkdir(parents=True)
    with duckdb.connect() as con:
        queries = {
            "pois.parquet": """
                SELECT * FROM (VALUES ('p1', 'r1', 'Museum'), ('p2', 'r1', NULL))
                AS t(fsq_place_id, locality, name)
            """,
            "metadata/metadata_all.parquet": """
                SELECT * FROM (VALUES ('p1'), ('p2')) AS t(fsq_place_id)
            """,
            "region_labels.parquet": "SELECT 'r1' AS region_id",
            "travel_behaviors.parquet": """
                SELECT 1::BIGINT AS user_id, 'r1' AS r_h, 'r1' AS r_o,
                    [struct_pack(venue_id := 'p1', ts := TIMESTAMPTZ '2020-01-01 00:00:00+00')] AS c_h,
                    [struct_pack(venue_id := 'p2', ts := TIMESTAMPTZ '2020-02-01 00:00:00+00')] AS c_o
            """,
        }
        if dirty:
            queries.update({
                "pois.parquet": """
                    SELECT * FROM (VALUES ('p1', 'r1'), ('p1', 'r1'), ('p2', 'unknown'),
                        (NULL, 'r1'), ('  ', NULL)) AS t(fsq_place_id, locality)
                """,
                "metadata/metadata_all.parquet": """
                    SELECT * FROM (VALUES ('p1'), ('p1'), ('orphan'), ('')) AS t(fsq_place_id)
                """,
                "region_labels.parquet": """
                    SELECT * FROM (VALUES ('r1'), ('r1'), (NULL)) AS t(region_id)
                """,
                "travel_behaviors.parquet": """
                    SELECT NULL::BIGINT AS user_id, 'unknown' AS r_h, '' AS r_o,
                        [struct_pack(venue_id := 'missing', ts := NULL::TIMESTAMPTZ),
                         struct_pack(venue_id := ' ', ts := NULL::TIMESTAMPTZ)] AS c_h,
                        []::STRUCT(venue_id VARCHAR, ts TIMESTAMPTZ)[] AS c_o
                """,
            })
        for filename, query in queries.items():
            dest = str(raw / filename).replace("'", "''")
            con.execute(f"COPY ({query}) TO '{dest}' (FORMAT PARQUET)")
        before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        audit = audit_raw_inputs(con, raw)
        assert audit == audit_raw_inputs(con, raw)
        after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        assert before == after
        if dirty:
            assert audit["tables"]["pois"]["rows"] == 5
            assert audit["tables"]["pois"]["duplicate_key_rows"] == 1
            assert audit["tables"]["metadata"]["duplicate_key_rows"] == 1
            assert audit["tables"]["regions"]["duplicate_key_rows"] == 1
            assert audit["tables"]["pois"]["missing_ids"] == {"fsq_place_id": 2, "locality": 1}
            assert audit["tables"]["travel"]["missing_ids"] == {"user_id": 1, "r_h": 0, "r_o": 1}
            assert audit["unmatched_references"] == {
                "pois_without_metadata": 1, "metadata_without_pois": 1,
                "pois_without_region_label": 1, "travel_home_without_region_label": 1,
                "travel_destination_without_region_label": 0,
            }
            assert audit["visits"]["c_h"] == {
                "rows": 2, "missing_poi_ids": 1, "missing_timestamps": 2,
                "unmatched_poi_ids": 1, "empty_lists": 0,
            }
            assert audit["visits"]["c_o"]["rows"] == 0
            assert audit["visits"]["c_o"]["empty_lists"] == 1
        else:
            assert all(v == 0 for v in audit["unmatched_references"].values())
            assert audit["tables"]["pois"]["null_counts"]["name"] == 1
            for table in audit["tables"].values():
                assert all(v == 0 for v in table["missing_ids"].values())
                assert table.get("duplicate_key_rows", 0) == 0
            for visit in audit["visits"].values():
                assert visit == {"rows": 1, "missing_poi_ids": 0, "missing_timestamps": 0,
                                 "unmatched_poi_ids": 0, "empty_lists": 0}


def test_name_normalization_preserves_unicode_and_fallbacks():
    from ml.data_pipeline import normalized_name_sql

    with duckdb.connect() as con:
        con.register('names', pd.DataFrame({
            'google': ['  Café 東京\t', '\t\n ', None, None],
            'fsq': ['Ignored', '\n Musée d’Orsay  ', '  ', None],
            'poi_id': ['p1', 'p2', 'p3', 'p4'],
        }))
        expression = normalized_name_sql('google', 'fsq', 'poi_id')
        result = con.sql(f'SELECT {expression} FROM names').fetchall()
    assert result == [('Café 東京',), ('Musée d’Orsay',), ('p3',), ('p4',)]


@pytest.mark.parametrize('field,value', [
    ('lat', 91.0), ('lon', -181.0), ('lat', float('inf')),
    ('google_rating', 0.0), ('google_rating', float('inf')),
    ('n_checkins', -1), ('n_users_visited', 5), ('n_reviews_with_text', 4),
    ('venue_category', '\t'), ('name', '   '),
    ('google_num_reviews', -1),
])
def test_invalid_poi_values_are_rejected(field, value):
    from ml.data_pipeline import validate_poi_values

    row = {'name': 'Café 東京', 'venue_category': 'id', 'venue_schema': 'schema:Museum',
           'lat': 1.0, 'lon': 2.0, 'google_rating': 4.5, 'google_num_reviews': 1,
           'n_checkins': 3, 'n_users_visited': 2, 'n_reviews': 3, 'n_reviews_with_text': 2}
    row[field] = value
    with duckdb.connect() as con:
        con.register('catalog', pd.DataFrame([row]))
        with pytest.raises(ValueError, match='Invalid POI values'):
            validate_poi_values(con, 'catalog')


def test_missing_values_and_external_review_discrepancies_are_allowed():
    from ml.data_pipeline import validate_poi_values

    with duckdb.connect() as con:
        con.execute("""
            CREATE TABLE catalog AS SELECT 'Café 東京' AS name, 'id' AS venue_category,
                'schema:Museum' AS venue_schema, NULL::DOUBLE AS lat, NULL::DOUBLE AS lon,
                NULL::DOUBLE AS google_rating, 0::BIGINT AS google_num_reviews,
                3::BIGINT AS n_checkins, 2::BIGINT AS n_users_visited,
                3::BIGINT AS n_reviews, 2::BIGINT AS n_reviews_with_text
        """)
        assert not any(validate_poi_values(con, 'catalog').values())


def test_input_gate_allows_missing_labels_but_rejects_broken_keys():
    from ml.data_pipeline import validate_raw_audit

    audit = {'tables': {'pois': {'missing_ids': {'fsq_place_id': 0}, 'duplicate_key_rows': 0}},
             'visits': {'c_h': {'missing_poi_ids': 0, 'unmatched_poi_ids': 0}},
             'unmatched_references': {'pois_without_region_label': 13755}}
    validate_raw_audit(audit)
    audit['tables']['pois']['duplicate_key_rows'] = 1
    with pytest.raises(ValueError, match='duplicate_keys'):
        validate_raw_audit(audit)
    audit['tables']['pois']['duplicate_key_rows'] = 0
    audit['visits']['c_h']['unmatched_poi_ids'] = 1
    with pytest.raises(ValueError, match='unmatched_poi_ids'):
        validate_raw_audit(audit)
