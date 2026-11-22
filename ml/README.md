# TripWorld 3-Person Modeling Playbook

This folder implements the **1 Frozen Spine + 3 Plug-In Folders + 1 Shared Scoreboard** workflow so all 3 teammates can improve the cross-city recommender simultaneously with zero merge conflicts.

---

## 1. One-Time Setup (All 3 Teammates)

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r ml/requirements.txt

# Person 2 (Embeddings/FAISS/Two-Tower) & Person 3 (CatBoost/Optuna/SHAP) also run:
uv pip install --python .venv/bin/python -r ml/requirements-neural.txt
```

Download the core 421 MB TripWorld files into `data/tripworld/` (gitignored), then build the **Shared Spine** once:

```bash
.venv/bin/python -m ml.data_pipeline
.venv/bin/pytest tests/test_ml_spine.py
```

---

## 2. Google Colab Notebooks (1 per Teammate — With Visualizations)

Once pushed to `main`, each teammate can open their notebook directly in Google Colab (Cell 1 auto-clones the repo, installs dependencies, and downloads TripWorld):

| Teammate | Colab Notebook | Runtime | Charts Generated (`reports/figures/`) |
| :--- | :--- | :--- | :--- |
| **Person 1** (KDD, Data Eng, Locality, HPC ETL) | [`notebooks/tripworld_kdd.ipynb`](../notebooks/tripworld_kdd.ipynb) — [Open in Colab](https://colab.research.google.com/github/isaackimmi/cmpe-256-final-project/blob/main/notebooks/tripworld_kdd.ipynb) | CPU | Geography & trip lengths, Home→Travel lift & noise, Opportunity lift & tourist ratio, Pandas vs. DuckDB HPC speedup |
| **Person 2** (Stage 1: Embeddings, FAISS, Two-Tower) | [`notebooks/02_stage1_retrieval_embeddings_twotower.ipynb`](../notebooks/02_stage1_retrieval_embeddings_twotower.ipynb) — [Open in Colab](https://colab.research.google.com/github/isaackimmi/cmpe-256-final-project/blob/main/notebooks/02_stage1_retrieval_embeddings_twotower.ipynb) | **T4 / L4 GPU** | GPU vs. CPU encoding HPC benchmark, 2D PCA cross-city embedding clusters (London + Madrid), Two-Tower InfoNCE loss curve |
| **Person 3** (Stage 2: LightGBM, Optuna, SHAP, Agent) | [`notebooks/03_stage2_ranking_automl_shap.ipynb`](../notebooks/03_stage2_ranking_automl_shap.ipynb) — [Open in Colab](https://colab.research.google.com/github/isaackimmi/cmpe-256-final-project/blob/main/notebooks/03_stage2_ranking_automl_shap.ipynb) | CPU | Optuna AutoML history, Leaderboard comparison, Global SHAP beeswarm, Local museum SHAP waterfall, Active Learning feedback lift |

## 3. Folder Ownership (Zero Merge Conflicts)

| Teammate | Branch | Folder They Own | North Star Metric | Outputs |
| :--- | :--- | :--- | :--- | :--- |
| **Person 1** (Data & Locality Clues) | `feat/p1-locality` | `ml/features/` | Downstream `NDCG@10` lift | `feat_city_supply.parquet`, `feat_poi_stats_foldN.parquet`, `feat_user_locality_taste.parquet` |
| **Person 2** (Stage 1 Top-100) | `feat/p2-retrieval` | `ml/retrieval/` | **`Recall@100`** | `candidates_*_top100_fold0.parquet`, `poi_embeddings.npy` |
| **Person 3** (Stage 2 Top-10 + SHAP) | `feat/p3-ranking` | `ml/ranking/` | **`NDCG@10` & `Recall@10`** | `data/preds/*.parquet`, `backend/artifacts/*.joblib`, `reports/leaderboard.csv` |

POI statistics use `feat_poi_stats_foldN.parquet`; build and load the same `--val-fold N`. City supply and user taste remain shared.

**Golden Rules:**
1. Never edit `ml/data_pipeline.py` or `ml/evaluate.py` without team sign-off—everyone must score on the exact same `cv_folds.parquet`.
2. Every experiment outputs `(trip_id, poi_id, score)` to `data/preds/` and logs its official score via `ml/evaluate.py` into `reports/leaderboard.csv`.

---

## 3. Run the Full Working Pipeline Right Now

```bash
# 1. Shared Spine (Bronze -> Silver -> Gold + Pandera + User-Grouped 5-Fold CV)
.venv/bin/python -m ml.data_pipeline

# 2. Person 1 — Locality & Opportunity-Normalized Features
.venv/bin/python -m ml.features.build_locality_features --val-fold 0

# 3. Baseline Stage 1 Popularity Retriever + Official Score
.venv/bin/python -m ml.retrieval.baseline_popularity --val-fold 0 --top-k 100
.venv/bin/python -m ml.evaluate \
    --preds data/preds/baseline_popularity_fold0.parquet \
    --name "baseline_popularity_v1" --author "spine" --fold 0 \
    --notes "Destination tourist popularity among recommendable POIs"

# 4. Person 3 — Stage 2 LightGBM LambdaRank + Official Score
.venv/bin/python -m ml.ranking.train_ranker \
    --candidates data/gold/candidates_popularity_top100_fold0.parquet \
    --val-fold 0 --name "lgbm_locality_v1"
.venv/bin/python -m ml.evaluate \
    --preds data/preds/lgbm_locality_v1_fold0.parquet \
    --name "lgbm_locality_v1" --author "person3" --fold 0 \
    --notes "LightGBM LambdaRank + Person 1 opportunity-normalized locality features"
```

---

## 4. Next Upgrades for Each Teammate

* **Person 1 (`ml/features/`):** Add H3 spatial density, season/hemisphere × coastal/mountain affordances, cross-city category transition matrix, and Pandas vs. DuckDB/Spark HPC ETL timing charts.
* **Person 2 (`ml/retrieval/`):** Run `semantic_retriever.py` (Sentence-Transformer + FAISS + multi-interest `sem_sim_max`/`sem_sim_top3`), then upgrade to a PyTorch Two-Tower neural retriever (logging GPU vs. CPU HPC charts) and export `candidates_top100` for Person 3.
* **Person 3 (`ml/ranking/`):** Plug in Person 2's candidates, add Optuna AutoML + CatBoost YetiRank blending, compute SHAP global + per-recommendation explanations, and build the Stage 3 AI Travel Agent prototype.
