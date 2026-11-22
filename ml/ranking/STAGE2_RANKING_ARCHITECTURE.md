# Stage 2: Personalized Ranking — Architecture & Implementation Plan

**Project:** CMPE 256 Final Project — Trip Location Recommender  
**Owner:** Person #3 — Ranking and Explainability  
**Version:** 1.0 — Proposed Architecture  
**Status:** Awaiting repository validation and team interface agreement

---

## 1. Executive Summary

The Trip Location Recommender recommends points of interest (POIs) based on a traveler's destination, travel history, and preferences.

The recommendation system follows a multi-stage architecture:

1. **Stage 1 — Candidate Retrieval:** Generates potentially relevant POIs using popularity, semantic similarity, and optionally Two-Tower retrieval.
2. **Stage 2 — Personalized Ranking:** Reorders candidate POIs based on user preferences, location characteristics, historical behavior, and retrieval scores.
3. **Stage 3 — Travel Agent:** Uses ranked recommendations and grounded POI metadata to generate personalized itineraries and explanations.

Person #3 owns Stage 2, including model training, evaluation, tuning, explainability, and the data handoff to Stage 3.

### Primary objective

Build a reproducible, leakage-safe personalized ranking pipeline that improves Top-10 recommendation quality relative to the existing LightGBM baseline.

### Existing baseline

| Metric | Fold 0 result |
|---|---:|
| NDCG@10 | 0.28460 |
| Recall@10 | 0.36681 |

These results are the initial comparison point. They must be reproduced before claiming improvements.

### Deliverables

- Reusable Stage 2 ranking pipeline
- Trained model artifact and ordered feature schema
- Evaluation report and leaderboard entry
- Hyperparameter tuning experiment
- SHAP-based global and local explanations
- Optional CatBoost comparison and blending
- Stage 3-ready ranked POI payload
- Automated ranking tests
- Documentation and reproducible execution instructions

---

## 2. System Architecture

```text
                USER TRIP REQUEST
                        |
          +-------------+-------------+
          |                           |
     Travel history              Destination
     Preferences                 Travel month
          |                           |
          v                           v
   PERSON #1: FEATURES       PERSON #2: RETRIEVAL
   - POI locality stats      - Popularity candidates
   - User taste profiles     - Semantic candidates
   - History features        - Two-Tower candidates
          |                           |
          +-------------+-------------+
                        |
                        v
             STAGE 2: PERSON #3
              Candidate Validation
                        |
                        v
                Feature Assembly
                        |
                        v
              LightGBM LambdaRank
                        |
              +---------+---------+
              |                   |
          Optuna tuning      CatBoost optional
              |                   |
              +---------+---------+
                        |
                        v
                Ranked POI Scores
                        |
                        v
              NDCG / Recall Metrics
                        |
                        v
                SHAP Explanations
                        |
                        v
               Top 15-20 POI Pool
                        |
                        v
              STAGE 3: TRAVEL AGENT
                        |
                        v
               ITINERARY / FRONTEND
```

### Architectural principle

Separate the ranking pipeline into four concerns:

1. **Data preparation:** Validate and assemble features.
2. **Training:** Fit and tune ranking models.
3. **Inference:** Score candidate POIs using frozen training-time preprocessing and feature ordering.
4. **Evaluation and explainability:** Measure recommendation quality and explain model predictions.

Training code should not be required to execute inference.

---

## 3. Model Design

### 3.1 Primary model — LightGBM LambdaRank

Use LightGBM LambdaRank as the primary ranking algorithm.

This is a learning-to-rank model that learns to order POIs within each trip rather than simply predict a POI's overall popularity.

**Ranking group:** `trip_id`  
**Candidate identity:** `(trip_id, poi_id)`  
**Target:** Whether a POI is relevant to the held-out trip  
**Optimization objective:** Ranking quality, emphasizing Top-10 positions

The preferred initial implementation is:

```python
LGBMRanker(
    objective="lambdarank",
    metric="ndcg",
    eval_at=[10],
    random_state=42
)
```

Actual hyperparameters must be selected through controlled validation, not copied blindly from this illustration.

### 3.2 Model features

| Feature group | Examples | Source |
|---|---|---|
| Retrieval | `stage1_score`, `stage1_rank` | Person #2 |
| Travel context | `dest_month`, destination identity | Shared pipeline |
| User history | `n_history_cities`, `n_history_pois` | Shared pipeline |
| POI characteristics | Popularity, locality statistics | Person #1 |
| User preferences | Historical category affinity | Person #1 |
| Semantic relevance | Semantic retrieval score | Person #2 |
| Collaborative relevance | Two-Tower score | Person #2 |

Important constraints:

- Do not use target labels or future user activity as prediction features.
- Do not use arbitrary numerical encodings of trip or POI identifiers as ranking signals.
- Fit encoders and preprocessing parameters using training data only.
- Preserve exactly the same feature ordering during training and inference.
- Distinguish missing retrieval scores from meaningful low scores.
- Use only candidate-retrieval information that would be available at recommendation time.

### 3.3 Secondary model — CatBoost

Implement CatBoost ranking as a comparison model after the LightGBM pipeline is reliable.

Use a supported CatBoost ranking objective, such as YetiRank, consistent with the project's requirements and installed version.

Evaluate CatBoost independently before attempting score blending.

### 3.4 Model blending

An optional blended model combines LightGBM and CatBoost predictions:

```text
final_score =
    alpha * normalized_lightgbm_score
    + (1 - alpha) * normalized_catboost_score
```

Choose `alpha` using validation data only.

Scores must be normalized appropriately before blending. Compare blended performance against both standalone models, and retain the simpler model if blending provides no reliable benefit.

### 3.5 Hyperparameter optimization

Use Optuna to tune LightGBM.

Candidate parameters include:

- Learning rate
- Number of leaves
- Maximum tree depth
- Minimum samples per leaf
- Feature sampling fraction
- Row sampling fraction
- L1 and L2 regularization

Keep a fixed random seed and record trial parameters, evaluation metrics, and training settings.

Avoid using the final held-out test fold to select hyperparameters.

---

## 4. Data Contracts

All data contracts in this section are proposed integration contracts. Codex must reconcile them against the repository's actual schemas before implementing changes.

### 4.1 Stage 1 → Stage 2

**Input:** Candidate Parquet, with one row per candidate POI per trip.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `trip_id` | String-compatible identifier | Yes | Trip query |
| `poi_id` | String-compatible identifier | Yes | Candidate POI |
| `fold` | Integer | Yes | Evaluation fold |
| `stage1_score` | Float | Yes | Candidate retrieval score |
| `stage1_rank` | Integer | Yes | Retrieval rank |
| `dest_month` | Integer | Yes | Trip month |
| `n_history_cities` | Integer | Yes | Number of historical cities |
| `n_history_pois` | Integer | Yes | Historical POI count |
| Semantic score | Float | Optional | Semantic relevance |
| Two-Tower score | Float | Optional | Collaborative relevance |

The exact semantic and Two-Tower column names must be agreed upon with Person #2.

**Validation requirements:**

- No duplicate `(trip_id, poi_id, fold)` rows
- No invalid trip-to-destination candidate relationships
- No target leakage from held-out trips
- Valid ranking group sizes
- Consistent identifier types across input tables
- Documented missing-value behavior
- Candidate count and coverage reported for each fold

If Stage 1 combines multiple retrieval methods, it must specify how duplicate POIs are merged and how method-specific scores are retained.

### 4.2 Person #1 → Stage 2

Required feature sources include:

- POI-level locality statistics
- User historical category preferences
- Trip context and historical activity features

Expected join relationships:

```text
Candidate.poi_id
       |
       +-- POI locality features

Candidate.trip_id + POI category
       |
       +-- User historical taste features
```

Each feature table must have a documented join key and uniqueness constraint.

For every trip, user-history features must be calculated without using that trip's held-out target activity.

### 4.3 Stage 2 prediction output

Maintain compatibility with the existing evaluator.

**Required columns:**

| Field | Type | Purpose |
|---|---|---|
| `trip_id` | Identifier | Ranking group |
| `poi_id` | Identifier | Candidate POI |
| `score` | Float | Model prediction |

Use a Parquet prediction file for offline evaluation.

Do not silently modify the official evaluator schema.

Additional diagnostic columns may be stored in a separate artifact.

### 4.4 Stage 2 → Stage 3

The Stage 3 travel agent should receive a ranked pool of approximately 15–20 POIs.

Proposed logical payload:

```json
{
  "trip_id": "example_trip",
  "destination": "Tokyo",
  "model_version": "ranker_v1",
  "recommendations": [
    {
      "poi_id": "poi_001",
      "rank": 1,
      "score": 1.27,
      "name": "Example POI",
      "category": "Museum",
      "explanations": [
        {
          "feature": "category_affinity",
          "contribution": 0.42
        }
      ]
    }
  ]
}
```

This is an illustrative schema, not an implemented API.

Actual POI names, categories, locations, and descriptive facts must come from the approved catalog, not from invented text or model predictions.

SHAP contributions explain the model's score; they are not probabilities, causal evidence, or proof that a user will enjoy a POI.

Stage 3 must receive enough grounded metadata to describe POIs accurately.

---

## 5. Evaluation Strategy

### 5.1 Primary metrics

**NDCG@10**

Measures whether relevant POIs are ranked near the top of each trip's recommendations.

This is the primary ranking-quality metric.

**Recall@10**

Measures the fraction of relevant held-out POIs recovered in the Top 10.

Report it alongside NDCG@10 to capture coverage.

### 5.2 Baseline comparison

Compare:

| Model | NDCG@10 | Recall@10 |
|---|---:|---:|
| Current LightGBM fold-0 baseline | 0.28460 | 0.36681 |
| Reproduced baseline | TBD | TBD |
| Tuned LightGBM | TBD | TBD |
| CatBoost | TBD | TBD |
| LightGBM + CatBoost | TBD | TBD |

Do not fabricate improvements.

### 5.3 Validation protocol

Use the existing five user-grouped folds and the repository's official evaluator.

The intended process:

1. Validate fold separation and training-only feature construction.
2. Reproduce fold-0 results.
3. Run ranking evaluation on all five folds.
4. Report mean, standard deviation, and individual fold results.
5. Tune without using the final held-out evaluation data for model selection.
6. Report performance with clear candidate-source and evaluation-split identifiers.

Verify how the existing pipeline distinguishes training, validation, and held-out data before selecting a specific tuning scheme.

### 5.4 Additional diagnostic measurements

Track:

- Candidate retrieval coverage before ranking
- Percentage of trips with at least 10 candidates
- Number of candidate POIs per trip
- Fraction of zero-positive ranking groups
- Missing feature frequencies
- Model training and inference time
- Performance by destination or history-length segment, where sample sizes are sufficient

Recall@10 must be interpreted in relation to Stage 1 candidate coverage. Stage 2 cannot recover relevant POIs absent from its candidate set.

### 5.5 Leakage protection

Check for:

- Held-out user activity appearing in training histories
- Test-trip outcomes influencing popularity features
- Semantic or Two-Tower models trained using held-out targets
- Target labels entering feature tables
- Validation or test folds influencing fitted preprocessing
- Cross-fold data contamination

Retrieval and ranking must use compatible folds and training-data boundaries.

### 5.6 Acceptance criteria

The primary model is accepted when:

- Baseline execution is reproducible
- All defined schema checks pass
- Five-fold evaluation is available
- NDCG@10 and Recall@10 are correctly reported
- Prediction Parquet is compatible with the official evaluator
- Model and feature schema can be reloaded for inference
- No identified train/test leakage remains

Performance improvement is the optimization goal, not a substitute for correctness.

---

## 6. Explainability Architecture

### Global explanations

Compute SHAP-based feature importance to understand which features contribute most strongly to model scores across a representative evaluation sample.

Deliver:

- SHAP summary visualization
- Global feature-importance table
- Interpretation of dominant ranking factors

### Local explanations

For each recommended POI, identify the strongest positive and negative feature contributions.

Example presentation:

> This museum ranked highly partly because the traveler's past trips show interest in museums and the retrieval model considers it relevant to this destination.

This explanation must be supported by actual features and SHAP values. Do not generate unsupported personal preferences or causal claims.

For blended models, explanations must identify which underlying model they describe unless an appropriate blend-level explanation method is implemented.

---

## 7. Implementation Boundaries

### Files Person #3 may modify

Primary scope:

```text
ml/ranking/
```

Potential additional locations, subject to team agreement:

```text
tests/
notebooks/03_stage2_ranking_automl_shap.ipynb
docs/STAGE2_RANKING_ARCHITECTURE.md
reports/
```

### Shared files requiring coordination

```text
ml/data_pipeline.py
ml/evaluate.py
ml/config.py
ml/features/
ml/retrieval/
backend/
frontend/
```

Do not change shared pipeline behavior or official evaluation rules without team approval.

### Person #2 dependency

Request a stable Stage 1 export contract with:

- Retrieval metadata
- Semantic and Two-Tower scores, when available
- Agreed fold definitions
- Train/validation candidate generation
- Duplicate candidate handling rules

### Person #1 dependency

Confirm that locality and taste features have stable schemas and are generated without target leakage.

### Backend integration boundary

Person #3 provides:

- Loadable model artifact
- Feature ordering and preprocessing metadata
- Candidate-scoring function
- Ranked output schema
- Explanation payload builder

Backend owner provides:

- Request handling
- Data access and orchestration
- API routing
- Deployment integration

Person #3 should not implement the entire application backend unless ownership changes.

---

## 8. Proposed Code Architecture

Preserve working existing code and add modular functionality where useful.

```text
ml/
└── ranking/
    ├── __init__.py
    ├── train_ranker.py          # Existing CLI entry point
    ├── contracts.py             # Proposed schema validation
    ├── feature_builder.py       # Proposed feature assembly
    ├── model.py                 # Proposed model operations
    ├── inference.py             # Proposed scoring interface
    ├── tune.py                  # Proposed Optuna workflow
    ├── explain.py               # Proposed SHAP utilities
    ├── blend.py                 # Optional CatBoost blending
    └── stage3_payload.py        # Proposed agent handoff

tests/
    ├── test_ranking_contracts.py
    ├── test_ranking_features.py
    ├── test_ranking_training.py
    ├── test_ranking_inference.py
    ├── test_ranking_evaluation.py
    └── test_ranking_stage3_payload.py
```

These filenames are proposed, not mandatory.

Codex should reuse existing functions instead of duplicating them purely to satisfy this layout.

### Core inference interface

```python
def rank_candidates(
    candidates,
    feature_sources,
    model_artifact,
    top_k=20,
):
    """
    Validate inputs, assemble features,
    score candidates, and return ranked POIs.

    Does not retrain the model.
    """
```

The actual implementation should use explicit type definitions, documented schemas, deterministic tie-breaking, and consistent error handling.

---

## 9. Implementation Roadmap

### Phase 0 — Architecture validation

**Purpose:** Confirm the proposal matches the repository.

Tasks:

- Inspect the current ranking implementation
- Inspect existing notebook experiments
- Identify reusable functions
- Verify data schemas and actual dependencies
- Review the official evaluator
- Confirm file ownership boundaries

**Deliverable:** Accepted architecture and interface contracts.

**Gate:** No unresolved critical schema disagreements.

### Phase 1 — Baseline reproduction

Tasks:

- Obtain or generate required Gold data
- Run existing fold-0 ranking pipeline
- Verify baseline metrics
- Verify prediction schema and model export
- Record exact commands and environment

**Deliverable:** Reproducible baseline evaluation.

**Gate:** Successfully reproduce results or document and resolve discrepancies.

### Phase 2 — Modular ranking pipeline

Tasks:

- Add schema validation
- Modularize feature assembly
- Add inference-only model loading
- Preserve the existing CLI
- Add unit and integration tests
- Confirm deterministic prediction behavior

**Deliverable:** Working, tested Stage 2 pipeline.

**Gate:** Existing behavior remains compatible with official evaluation.

### Phase 3 — Improved ranking model

Tasks:

- Integrate supported Stage 1 signals
- Implement Optuna tuning
- Run five-fold evaluation
- Compare against baseline
- Perform ablation studies for feature groups

**Deliverable:** Tuned LightGBM model and evaluation report.

**Gate:** Reproducible metrics with no evidence of leakage.

### Phase 4 — Explainability

Tasks:

- Generate global SHAP analysis
- Generate per-recommendation explanations
- Test explanation-feature alignment
- Add readable explanation metadata

**Deliverable:** SHAP reports and explainable ranked recommendations.

**Gate:** Each explanation matches the model version and candidate being scored.

### Phase 5 — Optional CatBoost blending

Tasks:

- Train CatBoost ranking model
- Compare with LightGBM
- Tune blend weight
- Evaluate on untouched held-out data
- Retain or reject blending based on results

**Deliverable:** Model comparison and optional blended model.

**Gate:** Any selected model is demonstrably better or more appropriate under the agreed evaluation criteria.

### Phase 6 — Stage 3 handoff

Tasks:

- Produce Top 15–20 ranked POIs
- Join approved catalog metadata
- Attach local SHAP explanations
- Validate output schema
- Demonstrate a sample trip end to end

**Deliverable:** Reusable Stage 3 input builder.

**Gate:** Agent owner can consume the output without inspecting ranking internals.

### Phase 7 — Documentation and PR

Tasks:

- Update the ML playbook as appropriate
- Document reproduction commands
- Document model limitations
- Include evaluation evidence
- Prepare demonstration examples
- Open a pull request for review

**Deliverable:** Review-ready implementation PR.

**Gate:** Tests pass, changes are scoped, and the shared repository has not been modified unexpectedly.

---

## 10. Testing Plan

### Unit tests

Validate:

- Required input columns
- Duplicate candidate detection
- Missing-value handling
- Feature ordering
- Ranking group formation
- Deterministic tie-breaking
- Top-K output behavior
- Model loading

### Integration tests

Validate:

- Stage 1 Parquet → Stage 2 model
- Feature joins → scoring
- Scoring → official evaluator
- Scoring → Stage 3 payload

### Regression tests

Use a small deterministic dataset to compare:

- Known prediction ordering
- Prediction row counts
- Correct `(trip_id, poi_id)` alignment
- Correct fold boundaries
- No change to evaluator-compatible output

Avoid relying exclusively on large model-training jobs for routine test execution.

---

## 11. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Stage 1 schema changes | Version and validate input contracts |
| Semantic / Two-Tower not ready | Keep popularity baseline working |
| Missing Gold data | Add reproducible setup instructions |
| Model leakage | Enforce fold-aware features and testing |
| Overfitting small validation folds | Use grouped cross-validation |
| Excessive model complexity | Preserve a simple working baseline |
| CatBoost incompatible with environment | Keep CatBoost optional |
| SHAP performance overhead | Use bounded explanation batches |
| Backend not ready | Export standalone Stage 3 payload |
| Concurrent team changes | Restrict edits and use reviewable PRs |

---

## 12. Codex Collaboration Rules

Codex must follow these principles:

1. Read this architecture before modifying ranking code.
2. Verify assumptions against actual repository files.
3. Preserve the official evaluator and shared fold definitions.
4. Do not modify another person's owned directory without explicit permission.
5. Implement one phase at a time.
6. Run relevant tests before reporting completion.
7. Distinguish executed tests from tests that could not run.
8. Do not invent evaluation results.
9. Document all changes affecting interfaces or artifacts.
10. Do not push changes or open PRs unless explicitly authorized for the relevant phase.

Use a local feature branch for changes. Opening a PR on a remote hosting service generally requires publishing the branch, so PR authorization must be treated separately from permission to push.

---

## 13. Definition of Done

Person #3's work is complete when:

- [ ] Baseline behavior is reproduced or discrepancies are resolved
- [ ] Stage 1 candidate inputs are validated
- [ ] Locality and preference features join correctly
- [ ] Model trains and exports successfully
- [ ] Model loads and scores without retraining
- [ ] NDCG@10 and Recall@10 are evaluated
- [ ] Five-fold results are documented
- [ ] Official leaderboard format is followed
- [ ] SHAP global and local explanations are available
- [ ] Stage 3-compatible ranked POI output is produced
- [ ] Ranking unit and integration tests pass
- [ ] Documentation is updated
- [ ] Pull request is reviewed before merging

CatBoost blending is a documented advanced deliverable. If incomplete, its status and impact must be stated transparently.

---

## 14. Final Deliverables

The final handoff should include:

1. Ranking source code and tests
2. Model artifact and feature schema
3. Fold-wise evaluation results
4. Leaderboard submission evidence
5. Global SHAP feature-importance visualization
6. Per-POI explanation example
7. Stage 3 payload example
8. Reproduction instructions and limitations
9. Pull request summarizing implementation and verification

**Design philosophy:** A correct, reproducible and explainable LightGBM ranking pipeline is the foundation. Add CatBoost blending and advanced integrations only after this foundation is verified.