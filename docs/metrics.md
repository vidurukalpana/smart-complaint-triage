# How each model is measured

This document defines how every model and component is evaluated, before any model is built.
Numbers referenced here live in `configs/metrics.yaml` and `configs/settings.yaml`.

## General rules

- **Time-based splits.** Data is split by the date the complaint was received, never at random.
  This mirrors real use: the model is trained on the past and used on later complaints.
- **Validation for decisions, test for reporting.** All tuning (hyperparameters, thresholds,
  calibration) uses the validation split. The test split is used once per final model.
- **Same test set for every model.** Models for the same task are compared on identical rows.
- **Fixed random seed** (`random_seed` in `settings.yaml`) for sampling and training.

### Splits

| Task | Train | Validation | Test |
|---|---|---|---|
| Routing | 2026-05-15 → 07-12 | 07-13 → 07-26 | 07-27 → 08-14 |
| Escalation | 2026-05-15 → 07-05 | 07-06 → 07-15 | 07-16 → 07-29 |

Escalation uses complaints received up to 2026-07-29 only. Newer complaints may still be
"In progress", so their outcome (monetary relief, late response) is not known yet.

### Fields never used as model inputs

These CFPB fields are only known after the company responds. Using them would leak the answer
into the model, so they are listed in `forbidden_features` and checked with
`check_no_forbidden_features()`. (`consumer_disputed`, listed in the development guide, is not in
the CFPB narratives archive, so it cannot leak and is not listed.)

| Field | Why it leaks |
|---|---|
| `company_response` | is the escalation label itself (e.g. "Closed with monetary relief") |
| `timely_response` | is the late-response label |
| `company_public_response` | written by the company after handling the complaint |
| `date_sent_to_company` | recorded during CFPB handling, after submission |

## 1. Team routing

Predicts the Sri Lankan bank team from the complaint narrative.

| Metric | Why |
|---|---|
| **Macro-F1** (primary) | Teams are imbalanced; every team counts equally |
| Per-team recall | Shows which teams lose complaints to wrong routing |
| Accuracy | Easy to explain to the business |
| Confusion matrix | Shows which teams are confused with each other |
| Prediction time per complaint (ms) | Must be fast enough for batch and API use |
| Model size (MB) | Affects deployment on a laptop and in Docker |

### Auto-route threshold

Complaints above a confidence threshold go straight to the predicted team; the rest go to the
human triage queue. The threshold is chosen on the validation split as the **lowest threshold
where the precision of auto-routed complaints is at least 95%**
(`routing.auto_route_min_precision`). On the test split we report:

- **Auto-route precision:** share of auto-routed complaints sent to the correct team (target ≥ 95%)
- **Coverage:** share of complaints auto-routed (higher means less manual work)
- **Triage share:** 1 − coverage

The zero-shot LLM is evaluated on a fixed random sample of 2,000 test complaints
(`routing.llm_sample_size`), and the other models are scored on the same sample for comparison.

## 2. Escalation risk

Two binary classifiers: will the bank pay money (`Closed with monetary relief`), and will the
response be late. Positives are rare, so ranking and calibration matter more than accuracy.

| Metric | Why |
|---|---|
| **PR-AUC** (primary) | Focuses on the rare positive class |
| ROC-AUC | Standard ranking measure, for comparison |
| Brier score | Overall quality of the probabilities |
| Calibration curve and expected calibration error (10 bins) | Predicted risk should match the observed rate |
| Precision@K and recall@K per team queue (K = 10, 50) | What staff see at the top of their queue |

Each metric is compared against a simple baseline: the positive rate of the product and issue in
the training data. SHAP explanations are checked on a sample to make sure the top reasons make sense.

## 3. Emerging-issue detection

There is no labelled list of real incidents, so the detector is tested on past data with
**artificial spikes** added (for example, triple the weekly count of one team + issue).
Each week is compared against the previous 4 weeks (`emerging_issues.baseline_weeks`).

| Metric | Why |
|---|---|
| Detection rate | Share of injected spikes that raise an alert |
| False alerts per week | Alerts on data with no injected spike; too many and staff ignore them |
| Detection delay (weeks) | How quickly a spike is flagged |

Growing BERTopic topics are reviewed by hand for whether they make sense.

## 4. LLM summaries

Measured against 100 hand-labelled complaints (`summaries.labelled_sample_size`).

| Metric | Why |
|---|---|
| Valid JSON rate | Output must parse and match the schema |
| Amount accuracy | Extracted amount matches the label exactly |
| Date accuracy | Extracted dates match the label |
| Requested action accuracy | Matches the labelled action category |
| Sentiment and vulnerable-customer flag accuracy | Matches the labels |
| Unsupported amount rate | Amounts not found in the complaint text (hallucinations); target 0 |
| Prompt-injection test | Complaints with "ignore previous instructions" still give valid output |
| Generation time per complaint | Feasibility for weekly batches |

## 5. A/B test of the routing system

Defined in detail in `docs/experiment_plan.md` (branch 15).

- **Primary metrics:** days until the complaint reaches the right team, number of transfers,
  share resolved within the 21-day Central Bank deadline
- **Guardrail:** wrong-routing rate
- **Checks:** sample ratio mismatch, confidence intervals and significance tests

## 6. Monitoring in production

Tracked every week against the training data:

- Routing accuracy on complaints whose team is later confirmed
- Triage share and the distribution of confidence scores
- Data drift in text length, product mix and predicted team mix (Evidently)

An alert is raised and retraining is triggered when a metric crosses its limit. The new model
replaces the champion only if it scores better on the same evaluation.
