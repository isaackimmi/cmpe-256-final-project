# Stage 2 personalized ranking

`train_ranker.py` fits LightGBM LambdaRank with one query per trip. It preserves the Stage 1 candidate pool, learns from the official Gold targets, and scores every validation candidate for `ml.evaluate`. `inference.py` reloads the model to produce a per-trip Top 10, or a larger itinerary pool through `--top-k`.

## Prepare fold 0

Use a matching TripWorld Gold export and Person #2's all-fold `candidates_hybrid_top100_fold0.parquet`. Generated `data/` files are gitignored. The ranker reads these Gold tables in addition to the candidate file.

| Table | Role |
| --- | --- |
| `trips_multicity.parquet` | Canonical trip, traveler, destination, fold, context, and target count |
| `cv_folds.parquet` | Official user-to-fold assignments |
| `trip_targets_exploded.parquet` | Binary relevance by `(trip_id, fold, poi_id)` |
| `pois_clean.parquet` | Recommendable POIs, destination, category, and display name |
| `feat_poi_stats.parquet` | POI statistics generated with fold 0 held out |
| `feat_user_locality_taste.parquet` | Historical category preferences by `(trip_id, venue_schema)` |

To generate the tables from scratch, run these commands from the repository root with the core `ml/requirements.txt` dependencies installed. The raw download needs access to Hugging Face and its file download host. Use the same dataset revision and Gold snapshot across Stage 1 and Stage 2.

```bash
HF_HUB_DISABLE_XET=1 .venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="CRUISEResearchGroup/TripWorld",
    repo_type="dataset",
    local_dir="data/tripworld",
    allow_patterns=[
        "pois.parquet", "metadata/metadata_all.parquet",
        "region_labels.parquet", "travel_behaviors.parquet",
    ],
)
PY
.venv/bin/python -m ml.data_pipeline
.venv/bin/python -m pytest -q tests/test_ml_spine.py
.venv/bin/python -m ml.features.build_locality_features --val-fold 0
```

Hybrid retrieval also needs the BGE POI embeddings (`poi_embeddings.npy` and `poi_embedding_ids.parquet`), the matching `backend/artifacts/two_tower_fold0.pt` checkpoint, and the exploded trip history from the shared pipeline. Reuse matching team assets when available. The following commands prepare and run Person #2's exporter.

```bash
UV_CACHE_DIR=/tmp/tripworld-uv-cache uv pip install --python .venv/bin/python \
    torch sentence-transformers matplotlib seaborn
.venv/bin/python -c 'from ml.retrieval.semantic_retriever import encode_pois; encode_pois()'
.venv/bin/python -m ml.retrieval.hybrid_retriever --val-fold 0 --top-k 100
```

Use the checked-in fold-0 Two-Tower checkpoint only with the matching Gold/embedding inputs. A fresh checkpoint can be trained with `python -m ml.retrieval.two_tower --val-fold 0` with the same environment. Omit `--val-only` from the hybrid export so Stage 2 can fit on the other folds.

## Train, evaluate, and show a Top 10

```bash
.venv/bin/python -m ml.ranking.train_ranker \
    --candidates data/gold/candidates_hybrid_top100_fold0.parquet \
    --val-fold 0 --name lgbm_hybrid_v1

.venv/bin/python -m ml.evaluate \
    --preds data/preds/lgbm_hybrid_v1_fold0.parquet \
    --name lgbm_hybrid_v1 --author person3 --fold 0 --no-log

trip_id=$(.venv/bin/python - <<'PY'
import duckdb

trip = duckdb.sql("""
    SELECT trip_id FROM 'data/preds/lgbm_hybrid_v1_fold0.parquet'
    GROUP BY trip_id HAVING COUNT(*) >= 10 ORDER BY trip_id LIMIT 1
""").fetchone()
if trip is None:
    raise SystemExit("No validation trip has ten candidates.")
print(trip[0])
PY
) && .venv/bin/python -m ml.ranking.inference \
    --model backend/artifacts/lgbm_hybrid_v1_fold0.joblib \
    --candidates data/gold/candidates_hybrid_top100_fold0.parquet \
    --trip-id "$trip_id" --top-k 10
```

The model artifact includes the ordered feature list, preprocessing, schema versions, training settings, and split and candidate coverage. Load joblib artifacts from trusted sources. Inference uses the catalog and both feature tables. It returns rank, score, model version, POI ID, name, category, and destination. For equal scores it sorts by POI ID, as the official evaluator does.

For the popularity fallback, generate `candidates_popularity_top100_fold0.parquet` with `.venv/bin/python -m ml.retrieval.baseline_popularity --val-fold 0 --top-k 100` and pass that file to the same ranker with a distinct experiment name. The hybrid train command reports missing inputs if its candidate file is absent.

## Feature and fold contract

- **23 baseline features.** Retrieval score and rank, destination month, two history counts, 11 POI statistics, and seven user-category features. The ordered names are in `features.py` and in each saved artifact.
- **Up to five additional features.** Person #2's hybrid exporter writes `sem_sim_mean`, `sem_sim_max`, `sem_sim_top3`, and `two_tower_score`. Stage 2 derives `sem_stage1a_score` as `0.5 * sem_sim_mean + 0.5 * sem_sim_top3` when both components are present and checks a supplied blend against them. Hybrid `stage1_score` is reciprocal rank fusion. The Stage 1 top-three value averages the available similarities when history has fewer than three embedded POIs.
- **Missing values.** The ranker leaves optional retrieval nulls as missing for LightGBM and keeps numeric zeros, including zeros emitted by Stage 1 for some trips without usable embeddings. It uses the starter defaults for missing locality and taste features. Popularity exports train with the baseline feature list.
- **Fold checks.** The ranker checks candidate and target folds against the shared user grouping, compares the tourist counts in Person #1's table with targets outside the holdout, and validates candidate identity and destination. It samples up to 40,000 whole training trips by default and fits only groups with a positive/negative pair. Its fixed tree budget keeps the outer fold out of model selection. Candidate recall and the official evaluator include held-out trips without hits or candidates.
- **Upstream provenance.** The hybrid code excludes the selected outer fold from its popularity counts and Two-Tower fit. It scores training trips with that same fitted tower, so some training retrieval scores are in-sample. Fold safety also depends on the catalog's global check-in/user counts and the timing of the home visits in TripWorld's `c_h` field. Confirm those sources with the data owners and obtain nested out-of-fold training exports before using the stack for tuned comparisons.

Run `python -m pytest -q tests/test_stage2_ranking.py` in the project environment for the isolated hybrid and popularity integration checks. These exercise model training, reload, deterministic Top-K, prediction compatibility, and the official evaluator without requiring the real TripWorld export.
