"""Isolated fixtures for the Stage 1 → ranker → official evaluator contract."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from ml import evaluate
from ml.ranking import train_ranker
from ml.ranking.features import FEATURE_COLS, OPTIONAL_FEATURES, POI_DEFAULTS, TASTE_DEFAULTS
from ml.ranking.inference import load_ranker, rank_candidates, top_ranked_candidates


def _poi(index: int) -> str:
    return f"fixture-poi-{index:02d}"


@pytest.fixture
def ranking_data(tmp_path: Path) -> tuple[Path, Path, pd.DataFrame]:
    gold = tmp_path / "gold"
    gold.mkdir()
    catalog = pd.DataFrame([
        {
            "poi_id": _poi(index),
            "region_id": "destination" if index < 12 else "other-city",
            "venue_schema": f"category-{index}",
            "name": f"Fixture place {index}",
            "is_recommendable": True,
        }
        for index in range(13)
    ])
    trips = []
    targets = []
    tastes = []
    candidates = []
    for trip in [11, 12, 13, 14, *range(100, 162)]:
        user = trip if trip < 100 else 1000 + trip // 2
        fold = 0 if trip < 100 else 1 + user % 2
        positive = 10 + trip % 2
        context = {
            "trip_id": trip,
            "user_id": user,
            "fold": fold,
            "dest_region_id": "destination",
            "dest_month": 5,
            "n_history_cities": 2,
            "n_history_pois": 4,
        }
        trips.append({**context, "n_target_pois": 1})
        targets.append({"trip_id": trip, "fold": fold, "poi_id": _poi(positive)})
        tastes.append({
            **TASTE_DEFAULTS,
            "trip_id": trip,
            "venue_schema": f"category-{positive}",
            "user_cat_visits": 4,
            "user_cat_share": 1.0,
            "opportunity_lift": 2.0,
            "was_available_in_history": True,
        })
        # Include a validation miss, an uncovered validation trip, and training
        # groups with no positive/negative pair.
        candidate_indices = {13: range(2), 14: [], 160: range(4), 161: [positive]}.get(trip, range(12))
        for index in candidate_indices:
            relevant = index == positive
            candidates.append({
                **context,
                "poi_id": _poi(index),
                "stage1_score": 1.0 / (index + 1),
                "stage1_rank": index + 1,
                "sem_sim_mean": None if (trip, index) == (11, 0) else 0.9 if relevant else 0.0,
                "sem_sim_max": 0.97 if relevant else 0.1,
                "sem_sim_top3": 0.85 if relevant else 0.04,
                "two_tower_score": 0.91 if relevant else -0.1,
            })

    trips = pd.DataFrame(trips)
    targets = pd.DataFrame(targets)
    train_visits = targets.loc[targets["fold"] != 0, "poi_id"].value_counts()
    poi_stats = catalog[["poi_id"]].assign(**POI_DEFAULTS)
    poi_stats["has_google_rating"] = False
    poi_stats["train_tourist_visits"] = poi_stats["poi_id"].map(train_visits).fillna(0).astype(int)
    poi_stats["log_train_tourist_visits"] = np.log1p(poi_stats["train_tourist_visits"])

    catalog.to_parquet(gold / "pois_clean.parquet", index=False)
    trips.to_parquet(gold / "trips_multicity.parquet", index=False)
    trips[["user_id", "fold"]].drop_duplicates().to_parquet(gold / "cv_folds.parquet", index=False)
    targets.to_parquet(gold / "trip_targets_exploded.parquet", index=False)
    poi_stats.to_parquet(gold / "feat_poi_stats_fold0.parquet", index=False)
    pd.DataFrame(tastes).to_parquet(gold / "feat_user_locality_taste.parquet", index=False)
    path = gold / "candidates_hybrid_top100_fold0.parquet"
    rows = pd.DataFrame(candidates).sample(frac=1, random_state=42)
    rows.to_parquet(path, index=False)
    return gold, path, rows


def test_feature_join_missing_signals_and_trip_sampling(ranking_data):
    gold, path, rows = ranking_data
    # Accidental target or ID columns in input never reach the feature allowlist.
    rows.assign(label=1, n_target_pois=100).to_parquet(path, index=False)
    train, val, features = train_ranker.load_joined_matrix(path, 0, 5, gold_dir=gold)
    repeated, _, _ = train_ranker.load_joined_matrix(path, 0, 5, gold_dir=gold)
    pd.testing.assert_frame_equal(train, repeated)
    assert train["trip_id"].nunique() == 5
    expected_sizes = rows.groupby("trip_id").size()
    assert train.groupby("trip_id").size().to_dict() == expected_sizes.loc[train["trip_id"].unique()].to_dict()
    assert train["trip_id"].is_monotonic_increasing
    assert set(train["trip_id"]).isdisjoint(val["trip_id"])
    assert set(val["trip_id"]) == {11, 12, 13}
    assert features == FEATURE_COLS + list(OPTIONAL_FEATURES)
    assert val.columns.tolist() == ["trip_id", "poi_id", "label", *features]
    assert val.groupby("trip_id")["label"].sum().to_dict() == {11: 1, 12: 1, 13: 0}

    trip = val[val["trip_id"] == 11].set_index("poi_id")
    assert np.isnan(trip.loc[_poi(0), "sem_sim_mean"])
    assert np.isnan(trip.loc[_poi(0), "sem_stage1a_score"])
    assert trip.loc[_poi(1), "sem_sim_mean"] == 0.0
    assert trip.loc[_poi(1), "sem_stage1a_score"] == pytest.approx(0.02)
    assert trip.loc[_poi(1), "user_cat_diversity"] == 1.0
    assert trip.loc[_poi(11), "sem_stage1a_score"] == pytest.approx(0.875)
    assert trip.loc[_poi(11), "user_cat_visits"] == 4.0


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("missing_column", "missing required columns: stage1_rank"),
        ("duplicate", "Duplicate .* candidate"),
        ("wrong_fold", "Candidate fold does not match the Gold trip"),
        ("wrong_context", "Candidate trip context does not match the Gold trip"),
        ("wrong_destination", "Candidate POI is outside the trip destination"),
        ("infinite_signal", "Invalid sem_sim_mean"),
        ("text_signal", "sem_sim_mean must be numeric"),
        ("incorrect_top3", "sem_sim_top3 exceeds sem_sim_max"),
        ("incorrect_blend", "sem_stage1a_score does not match its components"),
    ],
)
def test_rejects_invalid_candidates(ranking_data, corruption, message):
    gold, path, rows = ranking_data
    index = rows.index[0]
    if corruption == "missing_column":
        rows = rows.drop(columns="stage1_rank")
    elif corruption == "duplicate":
        rows = pd.concat([rows, rows.iloc[:1]])
    elif corruption == "wrong_fold":
        rows.loc[index, "fold"] = 4
    elif corruption == "wrong_context":
        rows.loc[index, "dest_month"] = 7
    elif corruption == "wrong_destination":
        rows.loc[index, "poi_id"] = _poi(12)
    elif corruption == "infinite_signal":
        rows.loc[index, "sem_sim_mean"] = np.inf
    elif corruption == "text_signal":
        rows["sem_sim_mean"] = "unknown"
    elif corruption == "incorrect_top3":
        rows.loc[index, "sem_sim_top3"] = 0.99
    elif corruption == "incorrect_blend":
        rows["sem_stage1a_score"] = 1.0
    rows.to_parquet(path, index=False)
    with pytest.raises(ValueError, match=message):
        train_ranker.load_joined_matrix(path, 0, gold_dir=gold)


@pytest.mark.parametrize(
    ("filename", "column", "value", "message"),
    [
        ("cv_folds.parquet", "fold", 4, "Gold trip fold disagrees"),
        ("trip_targets_exploded.parquet", "fold", 4, "Gold targets have an invalid fold"),
        ("feat_poi_stats_fold0.parquet", "train_tourist_visits", 1000, "tourist counts outside held-out fold 0"),
    ],
)
def test_rejects_gold_tables_from_an_inconsistent_split(ranking_data, filename, column, value, message):
    gold, path, _ = ranking_data
    table = pd.read_parquet(gold / filename)
    table.loc[0, column] = value
    table.to_parquet(gold / filename, index=False)
    with pytest.raises(ValueError, match=message):
        train_ranker.load_joined_matrix(path, 0, gold_dir=gold)


def test_rejects_duplicate_feature_keys(ranking_data):
    gold, path, _ = ranking_data
    tastes = gold / "feat_user_locality_taste.parquet"
    table = pd.read_parquet(tastes)
    pd.concat([table, table.iloc[:1]]).to_parquet(tastes, index=False)
    with pytest.raises(ValueError, match=r"user_taste must have unique, non-null \(trip_id, venue_schema\) keys"):
        train_ranker.load_joined_matrix(path, 0, gold_dir=gold)


def test_missing_inputs_and_validation_only_candidate_export(ranking_data):
    gold, path, rows = ranking_data
    with pytest.raises(FileNotFoundError, match="missing.parquet"):
        train_ranker.load_joined_matrix(gold / "missing.parquet", 0, gold_dir=gold)
    rows[rows["fold"] == 0].to_parquet(path, index=False)
    with pytest.raises(ValueError, match="No training candidates"):
        train_ranker.load_joined_matrix(path, 0, gold_dir=gold)


def test_rejects_candidates_exported_for_the_wrong_holdout(ranking_data):
    gold, path, rows = ranking_data
    other_fold = path.with_name("candidates_hybrid_top100_fold1.parquet")
    rows.to_parquet(other_fold, index=False)
    with pytest.raises(ValueError, match="Candidate export held out fold 1"):
        train_ranker.load_joined_matrix(other_fold, 0, gold_dir=gold)


def test_ranking_is_per_trip_with_evaluator_ties():
    predictions = pd.DataFrame({
        "trip_id": [2, 1, 1, 2, 1],
        "poi_id": ["z", "b", "a", "c", "d"],
        "score": [4.0, 1.0, 1.0, 3.0, 0.0],
    })
    ranked = top_ranked_candidates(predictions, top_k=2)
    assert ranked[["trip_id", "poi_id", "rank"]].values.tolist() == [
        [1, "a", 1], [1, "b", 2], [2, "z", 1], [2, "c", 2],
    ]
    assert len(top_ranked_candidates(predictions, top_k=20)) == len(predictions)
    with pytest.raises(ValueError, match="top_k must be positive"):
        top_ranked_candidates(predictions, top_k=0)


@pytest.mark.parametrize("hybrid", [True, False], ids=["hybrid", "popularity"])
def test_training_export_reload_top10_and_official_evaluator(ranking_data, tmp_path, monkeypatch, hybrid):
    gold, path, rows = ranking_data
    if not hybrid:
        path = gold / "candidates_popularity_top100_fold0.parquet"
        rows = rows.drop(columns=[feature for feature in OPTIONAL_FEATURES if feature in rows])
        rows.to_parquet(path, index=False)
    artifact_dir = tmp_path / "artifacts"
    monkeypatch.setattr(train_ranker, "ARTIFACTS_DIR", artifact_dir)
    monkeypatch.setattr(train_ranker, "PREDS_DIR", tmp_path / "preds")
    monkeypatch.setattr(evaluate, "DATA_GOLD_DIR", gold)
    preds_path = train_ranker.train_and_predict(path, name="fixture_ranker", gold_dir=gold)
    model_path = artifact_dir / "fixture_ranker_fold0.joblib"
    artifact = load_ranker(model_path)
    assert artifact["features"] == FEATURE_COLS + (list(OPTIONAL_FEATURES) if hybrid else [])
    assert artifact["model"].get_params()["objective"] == "lambdarank"
    assert artifact["model"].booster_.num_trees() > 1
    assert artifact["training"]["folds_sampled"] == [1, 2]
    assert artifact["training"]["trips_fitted"] == 60
    assert artifact["training"]["trips_without_pairs"] == 2

    preds = pd.read_parquet(preds_path)
    assert preds.columns.tolist() == ["trip_id", "poi_id", "score"]
    assert preds["score"].dtype == np.float64
    assert np.isfinite(preds["score"]).all()
    val_candidates = rows.loc[rows["fold"] == 0, ["trip_id", "poi_id"]]
    pd.testing.assert_frame_equal(
        preds[["trip_id", "poi_id"]].sort_values(["trip_id", "poi_id"]).reset_index(drop=True),
        val_candidates.sort_values(["trip_id", "poi_id"]).reset_index(drop=True),
    )
    metrics = evaluate.evaluate_predictions(preds_path, fold=0)
    # Hand-calculated test oracle: first hit on two trips, zero on the other two.
    assert metrics["n_trips"] == 4
    assert metrics["ndcg_10"] == metrics["recall_10"] == 0.5

    live_candidates = rows[rows["fold"] == 0].drop(columns="fold")
    live_path = gold / "unlabeled-candidates.parquet"
    live_candidates.to_parquet(live_path, index=False)
    # The inference contract does not depend on the relevance or CV files.
    (gold / "trip_targets_exploded.parquet").unlink()
    (gold / "cv_folds.parquet").unlink()
    ranked = rank_candidates(live_path, model_path, gold_dir=gold)
    assert ranked.groupby("trip_id").size().to_dict() == {11: 10, 12: 10, 13: 2}
    assert ranked.loc[ranked["rank"] == 1, "poi_id"].head(2).tolist() == [_poi(11), _poi(10)]
    assert ranked.loc[0, "name"] == "Fixture place 11"
    assert ranked.loc[0, "model_version"] == "fixture_ranker"
    pd.testing.assert_frame_equal(
        ranked[["trip_id", "poi_id", "score", "rank"]],
        top_ranked_candidates(preds),
    )
    selected = rank_candidates(live_path, model_path, gold_dir=gold, trip_id=11, top_k=20)
    assert selected["trip_id"].unique().tolist() == [11]
    assert selected["rank"].tolist() == list(range(1, 13))

    if hybrid:
        # A hybrid artifact can score optional signals missing from an entire export.
        live_candidates.drop(columns=[feature for feature in OPTIONAL_FEATURES if feature in live_candidates]).to_parquet(
            live_path, index=False
        )
        assert len(rank_candidates(live_path, model_path, gold_dir=gold, trip_id=11)) == 10
        joblib.dump({**artifact, "features": artifact["features"][::-1]}, model_path)
        with pytest.raises(ValueError, match="feature names and ordering"):
            load_ranker(model_path)


def test_fold_specific_paths_do_not_fall_back_to_shared_statistics(tmp_path):
    from ml.ranking.features import feature_paths

    assert feature_paths(tmp_path, 0)['poi_stats'].name == 'feat_poi_stats_fold0.parquet'
    assert feature_paths(tmp_path, 2)['poi_stats'].name == 'feat_poi_stats_fold2.parquet'


def test_inference_uses_saved_model_fold(tmp_path, monkeypatch):
    from ml.ranking import inference

    # An old shared file must not hide a missing file for the model's fold.
    (tmp_path / 'feat_poi_stats.parquet').write_bytes(b'legacy file')
    monkeypatch.setattr(inference, 'load_ranker',
                        lambda _: {'features': [], 'evaluation': {'fold': 2}})
    with pytest.raises(FileNotFoundError, match='feat_poi_stats_fold2.parquet'):
        inference.rank_candidates(tmp_path / 'candidates.parquet', tmp_path / 'model.joblib', gold_dir=tmp_path)


def test_inference_rejects_model_without_feature_fold(tmp_path, monkeypatch):
    from ml.ranking import inference

    monkeypatch.setattr(inference, 'load_ranker', lambda _: {'features': []})
    with pytest.raises(ValueError, match='valid feature fold'):
        inference.rank_candidates(tmp_path / 'candidates.parquet', tmp_path / 'model.joblib', gold_dir=tmp_path)
