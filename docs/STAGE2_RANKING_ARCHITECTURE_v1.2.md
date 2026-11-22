# Stage 2 Personalized Ranking — Architecture & Implementation Plan

**Project:** CMPE 256 Final Project — Trip Location Recommender  
**Owner:** Person #3 — Personalized Ranking and Explainability  
**Version:** 1.2 — Hybrid Parquet Implementation Kickoff  
**Status:** Stage 2 ranker implemented and fixture-tested.

**Proposed repository path:** `docs/STAGE2_RANKING_ARCHITECTURE.md`

Person #2's exporter writes `data/gold/candidates_hybrid_top100_fold0.parquet`. That file and its matching Gold tables are absent from this checkout. The real benchmark and Parquet audit remain pending.

See the [Stage 2 runbook](../ml/ranking/README.md) for the implemented contract, data preparation, and fold-0 training, evaluation, and inference commands.

---

## 1. Project Objective and Responsibility

The Trip Location Recommender recommends points of interest (POIs) using a traveler's destination, past travel history, preferences, and POI characteristics.

Person #3 owns **Stage 2 Personalized Ranking**.

The principal responsibility is to:

1. Receive approximately 100 candidate POIs from Person #2's retrieval system.
2. Combine semantic similarity, traveler history, locality features, and candidate retrieval signals.
3. Use learning-to-rank models to score each candidate.
4. Sort candidates by predicted relevance.
5. Return the best 10 locations for user-facing recommendations.
6. Produce ranking metrics, model explanations, and a reusable output for Stage 3.

The number of candidates may vary depending on retrieval coverage. The ranker must support variable candidate counts rather than assuming exactly 100.

### Scope clarification

- **Person #1:** User-history, locality, and preference features.
- **Person #2:** Candidate retrieval, including multi-interest semantic scoring and potential Two-Tower retrieval.
- **Person #3:** Personalized candidate reranking, model training, evaluation, tuning, and explainability.
- **Stage 3 owner:** Personalized itinerary generation and recommendation presentation.

Person #3 does not own the semantic embedding generation or Person #2's Stage 1A scoring formula.

### Immediate implementation path: use the existing ranker

Person #2 supplied this command, which should be run from the repository root using the project's environment:

```bash
.venv/bin/python -m ml.ranking.train_ranker \
    --candidates data/gold/candidates_hybrid_top100_fold0.parquet \
    --val-fold 0 --name lgbm_hybrid_v1
```

This command **requests** a LightGBM training/evaluation run using the hybrid candidate file; it does not prove that the file exists, its columns are compatible, or that the required Gold labels and feature tables are present. First inspect those prerequisites and the CLI's real behavior. If all prerequisites are present, run it, save its outputs, and identify gaps before refactoring.

**Immediate milestone (MVP):** run the hybrid fold-0 ranking pipeline successfully, generate a loadable model, evaluator-compatible predictions, measured NDCG@10 / Recall@10, and a correctly ordered Top-10 example. Do not wait for CatBoost, five-fold optimization, SHAP, frontend integration, or all teammate pipelines to be finished before attempting this milestone.

---

## 2. Full Recommendation Architecture

```text
USER REQUEST
   |
   |-- Travel destination
   |-- Travel history
   |-- Travel month
   |-- User preferences, if available
   |
   v
STAGE 1 — CANDIDATE RETRIEVAL (PERSON #2)
   |
   |-- Popularity retrieval
   |-- Multi-interest semantic retrieval
   |     |-- sem_sim_mean
   |     |-- sem_sim_max
   |     |-- sem_sim_top3
   |     +-- Stage 1A weighted score
   |
   |-- Optional Two-Tower retrieval
   |
   v
CANDIDATE POOL (~100 POIs)
   |
   +------------------------------+
   |                              |
   v                              v
PERSON #1 FEATURES          STAGE 1 SIGNALS
- POI locality              - Retrieval rank
- Category preferences      - Retrieval score
- Visit history             - Semantic similarities
- POI popularity            - Optional Two-Tower score
   |                              |
   +---------------+--------------+
                   |
                   v
STAGE 2 — RANKING (PERSON #3)
                   |
                   v
          Candidate Validation
                   |
                   v
          Feature Engineering
                   |
                   v
          LightGBM LambdaRank
                   |
          +--------+--------+
          |                 |
     Optuna tuning     Optional CatBoost
          |                 |
          +--------+--------+
                   |
                   v
          Personalized POI Scores
                   |
                   v
          Descending Score Ranking
                   |
          +--------+---------+
          |                  |
          v                  v
      TOP 10 POIs       TOP 15–20 POIs
      User-facing       Optional Stage 3 pool
          |                  |
          +--------+---------+
                   |
                   v
          Stage 3 Travel Agent
                   |
                   v
          Personalized Itinerary
```

### Key design decision

Stage 2 is a ranking system, not another independent candidate-retrieval system.

It should score and reorder the candidate set produced by Stage 1, rather than silently replacing or expanding that set.

---

## 3. Person #2 Multi-Interest Scoring Integration

### 3.1 Problem addressed by Stage 1A

Representing user history as one averaged embedding may obscure distinct user interests.

For example, a traveler who enjoys museums and beaches may have a combined representation that does not closely match either category.

Person #2 addresses this by comparing each candidate POI against individual POIs in the user's travel history.

### 3.2 Semantic features

**`sem_sim_mean`**

Represents overall similarity between a candidate and the user's historical interests, according to Person #2's implementation.

**`sem_sim_max`**

The highest similarity between the candidate and any individual previously visited POI.

**`sem_sim_top3`**

The average of the three highest historical POI similarities.

For a traveler with fewer than three valid historical POIs, the feature definition must specify the actual behavior.

**`sem_stage1a_score` — proposed field name**

The weighted semantic score:

```python
sem_stage1a_score = (
    0.5 * sem_sim_mean
    + 0.5 * sem_sim_top3
)
```

This formula is owned by Person #2 and should not be modified by Person #3.

### 3.3 Stage 2 usage

Rather than using only the weighted Stage 1A score, the ranker should test all underlying semantic features.

Proposed feature set:

```python
semantic_features = [
    "sem_sim_mean",
    "sem_sim_max",
    "sem_sim_top3",
    "sem_stage1a_score",
]
```

`sem_stage1a_score` is a proposed integration name that must be confirmed with Person #2.

`stage1_score` should remain the canonical retrieval score in the existing input contract unless the team explicitly changes its meaning.

These two scores must not be assumed equivalent: the combined Stage 1 retrieval score may incorporate popularity, semantic, and Two-Tower signals.

### 3.4 Why use all four signals?

A manually weighted formula treats every traveler similarly.

LightGBM can learn nonlinear ranking relationships, such as:

- Strong single-interest similarity may matter for users with diverse interests.
- Average similarity may matter more for users with consistent preferences.
- Local popularity may matter more when user history is sparse.
- Semantic similarity may become more useful when combined with POI category preferences.

These are hypotheses to evaluate, not assumptions that the model has already learned.

Because the weighted score is derived from two other features, ablation experiments should determine whether retaining all four is useful.

---

## 4. Data Contracts

### 4.1 Stage 1 → Stage 2 Candidate Contract

Candidate data must identify the trip, candidate POI, fold, and retrieval context.

**Important:** This is a proposed schema, not a verified description of the new hybrid Parquet. Codex must inspect its real columns and dtypes. Fields missing from the actual file must be sourced from existing Gold feature tables or treated as optional according to the verified ranker, not fabricated. `sem_stage1a_score` remains a proposed name.

| Column | Required? | Purpose |
|---|---|---|
| `trip_id` | Yes | Ranking query identifier |
| `poi_id` | Yes | Candidate identifier |
| `fold` | Yes | Evaluation fold |
| `stage1_score` | Yes | Canonical retrieval score |
| `stage1_rank` | Yes | Original retrieval rank |
| `dest_month` | Yes | Travel month |
| `n_history_cities` | Yes | Historical city count |
| `n_history_pois` | Yes | Historical POI count |
| `sem_sim_mean` | Semantic mode | Overall similarity |
| `sem_sim_max` | Semantic mode | Strongest interest match |
| `sem_sim_top3` | Semantic mode | Top-three similarity |
| `sem_stage1a_score` | Semantic mode | Weighted semantic score |
| Two-Tower score | Optional | Collaborative relevance |

**Contract rules:**

1. A candidate is uniquely identified by `(fold, trip_id, poi_id)`.
2. Input identifiers must match the shared catalog and target schemas.
3. All candidates in a ranking group must refer to the same trip context.
4. Stage 1 must not use future or held-out trip outcomes to construct user-history features.
5. Stage 2 must support missing optional semantic and Two-Tower features through a documented fallback.
6. Actual input field names and types must be validated against Person #2's export.

### 4.2 Semantic feature validation

Verify that:

- Semantic features are numeric and finite where present.
- Similarity values match their documented calculation method.
- A candidate's score corresponds to its correct POI and trip.
- The weighted Stage 1A score agrees with its component scores within floating-point tolerance.
- Candidate retrieval scores are not joined to the wrong fold.
- Users with no prior history receive consistent missing-history treatment.
- Users with one or two prior POIs are handled correctly.
- Duplicate candidates from multiple retrieval methods are merged consistently.

Do not substitute arbitrary zero values for missing semantic features without defining whether zero is a meaningful similarity score.

### 4.3 Person #1 Feature Contract

The ranker consumes POI-level and traveler-history features, including:

- POI locality statistics
- Historical traveler category affinities
- POI popularity features
- Trip-level history characteristics

Feature tables must have stable join keys.

No feature may incorporate information from the recommendation target's future activity.

### 4.4 Stage 2 Prediction Contract

The official offline evaluator expects:

```text
trip_id
poi_id
score
```

The ranker must export an evaluator-compatible prediction Parquet.

Predictions should include every eligible validation candidate before the evaluator applies its Top-10 cutoff.

Additional diagnostic columns may be exported separately.

### 4.5 Stage 3 Handoff Contract

Stage 2 produces a ranked response containing:

- Trip identifier
- Model version
- Ranked POI identifier
- Model score
- POI metadata from the approved catalog
- Explanation features and contributions, where available

Return the **Top 10** for user-facing recommendations.

The Stage 3 integration can request **Top 15–20** as a larger itinerary-planning pool. This does not change the Top-10 evaluation objective.

Use a configurable `top_k` rather than hardcoding one list length throughout the pipeline.

---

## 5. Ranking Model Architecture

### 5.1 Primary model: LightGBM LambdaRank

LightGBM LambdaRank is the primary Stage 2 model.

It learns to rank candidate POIs within each `trip_id` using available relevance labels.

The training data must be grouped by trip.

The model input combines:

```text
Candidate metadata
       +
Semantic retrieval features
       +
User-history features
       +
Locality / POI features
       +
Optional Two-Tower score
       |
       v
LightGBM LambdaRank
       |
       v
Candidate relevance score
```

### 5.2 Feature groups

**Group A — Baseline retrieval**

- `stage1_score`
- `stage1_rank`

**Group B — Multi-interest semantic relevance**

- `sem_sim_mean`
- `sem_sim_max`
- `sem_sim_top3`
- `sem_stage1a_score`

**Group C — Travel-history context**

- `n_history_cities`
- `n_history_pois`
- `dest_month`

**Group D — POI and preference features**

- Locality
- Popularity
- User category affinity
- Other approved Person #1 features

**Group E — Optional collaborative signals**

- Two-Tower retrieval score
- Documented hybrid retrieval signals

Feature names outside the existing schema are proposals until verified.

### 5.3 Training and inference separation

Training responsibilities:

1. Assemble labeled candidate groups.
2. Fit preprocessing using training data only.
3. Train LightGBM.
4. Evaluate on held-out data.
5. Export model and feature metadata.

Inference responsibilities:

1. Receive candidates and feature inputs.
2. Validate required fields.
3. Apply frozen preprocessing.
4. Load model.
5. Score candidates without retraining.
6. Sort descending by score.
7. Return configurable Top-K output.

Use deterministic tie-breaking, such as by canonical POI identifier.

### 5.4 Model artifact

Export:

- LightGBM model
- Ordered feature schema
- Required preprocessing information
- Model version
- Training configuration
- Applicable candidate-schema version
- Evaluation metadata

An exported model must be loadable without executing the training notebook.

---

## 6. Evaluation Strategy

### 6.1 Primary metrics

**NDCG@10**

Evaluates whether relevant POIs appear near the top of the ranked recommendations.

**Recall@10**

Evaluates how many relevant held-out POIs appear within the Top 10.

### 6.2 Existing baseline

| Metric | Recorded fold-0 result |
|---|---:|
| NDCG@10 | 0.28460 |
| Recall@10 | 0.36681 |

These baseline measurements must be reproduced and verified.

### 6.3 Required experiments

Conduct the following comparisons:

| Experiment | Candidate pool | Ranking features |
|---|---|---|
| E0 | Existing popularity candidates | Existing baseline |
| E1 | Same popularity candidates | Baseline + available semantic features |
| E2 | New multi-interest candidates | Baseline features |
| E3 | New multi-interest candidates | Baseline + multi-interest features |
| E4 | New multi-interest candidates | Tuned complete feature set |
| E5 | New multi-interest candidates | Optional CatBoost / blend |

E1 is only possible if Person #2 can produce valid semantic scores for the same candidate POIs.

The purpose is to separate:

- Improvements due to better candidate retrieval
- Improvements due to better ranking features
- Improvements due to hyperparameter tuning

A metric increase caused by a different candidate pool must not automatically be attributed to the ranking model.

### 6.4 Semantic feature ablation

Compare:

1. Baseline features only
2. Baseline + weighted Stage 1A score
3. Baseline + three individual semantic features
4. Baseline + all semantic features

Retain or remove features based on held-out evaluation results and model simplicity.

### 6.5 Cross-validation

Reuse the repository's five user-grouped folds.

Report:

- NDCG@10 per fold
- Recall@10 per fold
- Mean across folds
- Standard deviation
- Stage 1 candidate coverage
- Number of evaluable trips

Use a leakage-safe model-selection protocol, reserving appropriate held-out data for final evaluation.

Do not use a final test fold repeatedly to select Optuna parameters or blend weights.

### 6.6 Retrieval ceiling

Stage 2 cannot rank a relevant POI that Stage 1 failed to retrieve.

Measure retrieval coverage separately from ranking performance.

If the relevant POI does not appear among the 100 candidates, even a perfect ranker cannot recommend it.

### 6.7 Leakage prevention

Verify that:

- Historical user POIs precede the target trip.
- Held-out target POIs are not included in the user's history.
- Popularity statistics are calculated from permitted training observations.
- Semantic and Two-Tower candidate generation respects fold boundaries.
- Target labels are never prediction features.
- Feature preprocessing does not learn from the held-out evaluation set.

Static POI descriptions may be used as catalog metadata, provided they do not contain prohibited target-derived information.

---

## 7. Explainability

### 7.1 Global SHAP

Generate global SHAP analysis for the fitted ranking model.

Evaluate the importance of:

- Retrieval scores
- Overall semantic similarity
- Strongest-interest semantic similarity
- Top-three semantic similarity
- Locality and popularity
- User history and category preferences

SHAP should describe how features affect model scores, not establish causation.

### 7.2 Local SHAP

For each recommended POI, provide selected model-score contributions.

Example of a possible explanation:

> This POI ranked highly partly because of a strong similarity to a location in the traveler's history and a favorable category-preference score.

Only generate such an explanation when the actual model inputs and contributions support it.

### 7.3 Stage 3 explanation compatibility

The Stage 3 output should include:

- Feature identifiers
- SHAP values
- Model version
- Grounded POI metadata

Do not present arbitrary model scores as predicted probabilities.

---

## 8. Proposed Code Organization

Preserve existing working modules. The following structure is a target for modularization, not a requirement to create every file.

```text
ml/
└── ranking/
    ├── __init__.py
    ├── train_ranker.py
    ├── contracts.py
    ├── feature_builder.py
    ├── model.py
    ├── inference.py
    ├── tune.py
    ├── explain.py
    ├── blend.py
    └── stage3_payload.py

tests/
    ├── test_ranking_contracts.py
    ├── test_ranking_features.py
    ├── test_ranking_training.py
    ├── test_ranking_inference.py
    ├── test_ranking_evaluation.py
    └── test_ranking_stage3_payload.py
```

The existing `train_ranker.py` CLI should remain operational unless a coordinated interface change is approved.

---

## 9. Implementation Sequence

**Updated execution rule:** Codex may begin implementation now, but must make a fast, read-only input audit its first operation. If the hybrid file or training labels are missing, stop the training attempt, identify the exact generation/dependency command from repository code, and implement isolated, fixture-based ranking tests while the data handoff is resolved. Never invent labels or claim a successful training run that did not occur.

### Phase 0A — Hybrid input readiness check (start here)

- Locate `data/gold/candidates_hybrid_top100_fold0.parquet` and verify it is readable.
- Inspect schema, dtypes, total rows, unique trips, candidate rows per trip, fold distribution, duplicate `(fold, trip_id, poi_id)` keys, and missing values in ranking fields. Use a few sample rows only if safe.
- Confirm whether `sem_sim_mean`, `sem_sim_max`, `sem_sim_top3`, weighted Stage 1A score, and any Two-Tower score are actually present; record **actual** names and meanings.
- Trace `ml.ranking.train_ranker` to discover its real CLI arguments, training data construction, label source, feature joins, and output paths.
- Verify that fold-0 validation candidates and all training candidate groups are generated without held-out target leakage; check how the other folds contribute to training.
- Confirm the required Gold POI, taste/locality, targets, trip, and split files are available or have reproducible generation commands.
- Write a concise readiness summary and continue if the requirements are met. Missing optional semantic components are not blockers if a documented fallback works.

**Acceptance:** Verified real schema, reproducible data dependencies, and a clear go/no-go decision for hybrid training.

### Phase 0B — First executable Stage 2 milestone

- Run the shared hybrid training command unchanged first, if possible.
- Record the exit status, real output artifacts, feature list, fold-0 results, and any warnings/errors.
- Fix strictly ranking-owned errors in `ml/ranking/` and add tests; do not change retrieval, official evaluator, or shared folds without approval.
- Generate Top-10 example recommendations by sorting model predictions **within each `trip_id`** (not across the entire dataset).
- Save the model and prediction file and verify that the official evaluator can consume the predictions.
- If the command already succeeds, retain its behavior and improve through targeted modules/tests rather than replacing the code.

**Acceptance:** Trained hybrid model and measured outputs, or a precisely documented external data blocker plus tested ranking components.


### Phase 0 — Validate architecture and integration contracts

- Inspect Person #2's implementation.
- Identify how semantic scores are computed and exported.
- Determine whether multi-interest features are available for both training and validation candidates.
- Verify actual column names and join keys.
- Confirm how multiple candidate sources are merged.
- Verify model and evaluator compatibility.

**Acceptance:** Agreed data contracts with no unresolved critical schema mismatches.

### Phase 1 — Reproduce existing baseline

- Prepare Gold data.
- Run existing popularity-based ranking.
- Reproduce fold-0 metrics.
- Validate prediction and model artifacts.
- Add baseline regression checks.

**Acceptance:** Reproducible, documented baseline.

### Phase 2 — Multi-interest feature integration

- Implement semantic feature validation.
- Join Person #2's semantic scores onto the correct candidate rows.
- Preserve popularity-only fallback.
- Handle missing semantic signals.
- Add unit tests for the semantic data contract.
- Confirm correct training/validation fold alignment.

**Acceptance:** Ranking supports the proposed semantic features without breaking baseline compatibility.

### Phase 3 — Modular ranking and inference

- Separate feature assembly from training.
- Implement reusable model loading and inference.
- Enforce consistent feature ordering.
- Support configurable `top_k`.
- Add ranking and inference tests.

**Acceptance:** Saved model scores and ranks candidates without retraining.

### Phase 4 — Evaluation and optimization

- Evaluate new multi-interest candidate pools.
- Conduct semantic ablation studies.
- Run five-fold evaluation.
- Add Optuna tuning.
- Compare with existing baseline.

**Acceptance:** Verified evaluation report with candidate-source and model-version details.

### Phase 5 — SHAP explainability

- Generate global SHAP analysis.
- Generate local recommendation explanations.
- Validate explanation alignment.
- Produce explanation artifacts.

**Acceptance:** Explained recommendations use actual model features and contributions.

### Phase 6 — CatBoost and blending

- Implement CatBoost ranking comparison.
- Evaluate standalone CatBoost.
- Optionally blend its outputs with LightGBM.
- Compare performance against the primary model.

**Acceptance:** Documented reproducible comparison; retain blending only if justified.

### Phase 7 — Stage 3 handoff

- Produce final Top-10 recommendation lists.
- Support optional Top-15/20 itinerary pools.
- Attach POI metadata and explanations.
- Validate the handoff schema.
- Demonstrate one trip through retrieval and ranking.

**Acceptance:** Stage 3 owner can consume ranked output independently.

### Phase 8 — Final verification and PR

- Run applicable tests.
- Update reproducibility instructions.
- Document evaluation results and limitations.
- Update official leaderboard according to team rules.
- Prepare a scoped PR for review.

**Acceptance:** Review-ready changes without unauthorized modifications to shared modules.

---

## 10. Teammate Integration Questions

### Questions for Person #2

1. Does `candidates_hybrid_top100_fold0.parquet` export all three semantic features for each candidate, or are some scores only used internally?
2. What is the exact exported field name for the weighted Stage 1A score?
3. Is `stage1_score` the Stage 1A semantic score or a combined retrieval score?
4. Are fold-safe hybrid candidate sets and semantic scores available for **training as well as fold-0 validation**? If not, how are training candidate groups built?
5. How are candidates merged across popularity, semantic, and Two-Tower retrieval?
6. What happens when a traveler has fewer than three historical POIs?
7. What candidate-count and destination filters are enforced?

### Questions for Person #1

1. What are the final feature columns and join keys?
2. Are user-history features computed independently for every evaluation fold?
3. Are categorical preferences available for every trip?
4. How are unknown or missing feature values represented?

### Questions for Stage 3 owner

1. Should Stage 2 return exactly 10 recommendations or provide a larger 15–20 POI pool?
2. What POI metadata and explanation fields are needed?
3. Is Stage 3 expecting Parquet, JSON, or a Python service interface?
4. Which component owns the live API orchestration?

---

## 11. Implementation Guardrails

1. Do not alter Person #2's semantic scoring formula without agreement.
2. Do not change the official evaluation methodology.
3. Keep retrieval and ranking responsibilities separate.
4. Do not use target-derived information as model features.
5. Keep the existing popularity baseline operational.
6. Use fold-aware data preparation.
7. Validate all new semantic columns before use.
8. Preserve reproducible training and inference.
9. Report measured results only.
10. Obtain authorization before changing shared directories or pushing remote branches.

Opening a pull request requires a remotely accessible branch. A PR workflow must therefore receive explicit authorization for the necessary branch push.

---

## 12. Definition of Done

- [ ] Hybrid candidate Parquet and required Gold dependencies inspected
- [ ] Hybrid fold-0 CLI executed, or exact data blocker documented
- [ ] Existing LightGBM baseline reproduced
- [ ] Stage 1 candidate data contract verified
- [ ] Person #2 semantic features correctly integrated
- [ ] Person #1 locality and preference features joined
- [ ] Ranking pipeline trains and exports a model
- [ ] Saved model runs inference without retraining
- [ ] Top-10 ranking output verified
- [ ] Configurable Top-K supported
- [ ] Official NDCG@10 and Recall@10 computed
- [ ] Five-fold evaluation completed
- [ ] Semantic feature ablation completed
- [ ] Optuna optimization completed
- [ ] Global and local SHAP reports generated
- [ ] CatBoost/blending evaluated or explicitly documented as incomplete
- [ ] Stage 3 handoff validated
- [ ] Relevant automated tests pass
- [ ] Final README and reproduction instructions updated
- [ ] Pull request submitted for team review

---

## 13. Codex Execution Brief — First Coding Session

**Authorized scope for a local implementation session:** `ml/ranking/`, ranking-specific tests, and ranking documentation. No remote pushes, merges, or pull requests; do not modify shared retrieval, features, evaluator, backend, or frontend without explicit approval.

**First result to deliver:** A working, reproducible `lgbm_hybrid_v1` fold-0 run using `data/gold/candidates_hybrid_top100_fold0.parquet`, or an evidence-based blocker report if the required data is unavailable. Output a model, prediction Parquet with `(trip_id, poi_id, score)`, NDCG@10, Recall@10, and one Top-10 example sorted within a trip, plus tests and commands. Benchmark numbers must be measured rather than copied from the previous popularity run.

**Work order:**

1. Read this plan and `ml/ranking/train_ranker.py` and discover the real existing paths and requirements.
2. Inspect the hybrid Parquet **if present**. Summarize schema, fold distribution, group sizes, duplicates, nulls, and semantic / Two-Tower feature availability.
3. Identify where relevance labels and all feature inputs are loaded; never use validation outcomes as model features.
4. Run the provided CLI as-is. Capture errors and measured artifacts.
5. Make minimal, backward-compatible improvements needed for reliable hybrid ranking; keep a popularity-only path functional.
6. Add small fixture-based tests and rerun the real training/evaluation if the data is available.
7. Report completed changes, file paths, test evidence, metrics, remaining dependencies, and a next-phase recommendation.

**No mandatory upload to ChatGPT:** If Codex has access to this repository and its Gold data, it can inspect the `.parquet` directly. An upload of the Parquet (or a schema/sample summary) is only for an independent second review. Do not commit large generated data to Git unless the team explicitly agreed on that data-management practice.

### Suggested minimal Parquet inspection

From the repo root in the active `.venv`, Codex can use pandas if the required Parquet engine is installed:

```python
from pathlib import Path
import pandas as pd

path = Path('data/gold/candidates_hybrid_top100_fold0.parquet')
assert path.is_file(), f'Missing hybrid candidates: {path}'
df = pd.read_parquet(path)
print('shape:', df.shape)
print('columns and dtypes:', df.dtypes.to_dict())
print('null counts:', df.isna().sum().to_dict())
print('sample:', df.head(3).to_dict(orient='records'))
if 'trip_id' in df.columns:
    print('trip count:', df['trip_id'].nunique())
    print('candidates per trip:', df.groupby('trip_id').size().describe().to_dict())
if 'fold' in df.columns:
    print('fold counts:', df['fold'].value_counts(dropna=False).to_dict())
if {'trip_id', 'poi_id', 'fold'}.issubset(df.columns):
    print('duplicate keys:', int(df.duplicated(['fold','trip_id','poi_id']).sum()))
```

The inspection does not replace review of the ranker code, label sources, and train/validation boundaries. Do not print or share unnecessary personal trip details.

---

## 14. Final Architecture Principle

**Person #2 identifies plausible locations. Person #3 learns which of those locations should rank highest for the traveler.**

The ranking model should use Person #2's multi-interest semantic signals alongside locality, popularity, history, and preference features to produce a personalized Top-10 list.

A reliable, reproducible LightGBM implementation is the primary deliverable. Tuning, explainability, blending, and Stage 3 integration build on that foundation.
