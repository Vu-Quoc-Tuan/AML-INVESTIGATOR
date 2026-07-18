# Realtime Detection, Decision, and Investigation Queue Design

**Status:** Approved direction, pending written-spec review
**Date:** 2026-07-19
**Scope:** Connect the validated Kafka transaction stream to rule-based and XGBoost detection, persist only blocked transactions and investigation candidates, and feed candidates to the existing multi-agent workflow through mutually exclusive automatic/manual runners.

## 1. Objective

Build the next backend slice after Kafka ingestion:

```text
aml.transactions.validated.v1
  -> detection worker
       -> RuleEngine --------------------+
       -> RealtimeFeatureExtractor -> XGBoostPredictor
                                        |
                                        v
                                   RiskAggregator
       -> BLOCKED (ML >= 0.99)
       -> QUEUED  (rule hit or ML >= 0.60)
       -> ALLOWED (ML < 0.60 and no rule hit; persist nothing)
```

The multi-agent workflow must never run in the realtime Kafka consumer. It only consumes persisted candidates through an automatic 02:00 runner or a manual runner when automatic mode is disabled.

## 2. Fixed Policy

Thresholds are environment-driven and use these defaults:

```dotenv
DETECTION_REVIEW_THRESHOLD=0.60
DETECTION_BLOCK_THRESHOLD=0.99
DETECTION_TIMEZONE=Asia/Ho_Chi_Minh
DETECTION_AUTO_RUN_HOUR=2
```

The aggregator evaluates outcomes in this exact order:

1. If valid XGBoost confidence is at least `DETECTION_BLOCK_THRESHOLD`, return `BLOCKED`.
2. Otherwise, if any rule hits or XGBoost confidence is at least `DETECTION_REVIEW_THRESHOLD`, return `QUEUED`.
3. Otherwise return `ALLOWED` and persist nothing.

Rules do not directly auto-block in this phase. They only enqueue a candidate. A blocked transaction is stored for simulation/audit and is never submitted to the multi-agent runner.

`ALLOWED` transactions are not written to the candidate database, blocked table, or a detection-audit table. They may still exist in Kafka according to Kafka retention, and the realtime feature process may keep bounded in-memory rolling state; that state is not a detection decision record.

## 3. Scope Boundaries

### Included

- Consume canonical `TransactionEventV1` messages from `aml.transactions.validated.v1`.
- Execute a simple Python RuleEngine and XGBoost branch concurrently per event.
- Reuse selected rule conditions, model artifact, feature names, and compatible feature formulas from the old Kafka/ML commits.
- Aggregate branch results using the fixed policy above.
- Persist blocked transactions and investigation candidates in a dedicated SQLite database behind a repository interface.
- Idempotency by `event_id`.
- Automatic and manual candidate runners with mutually exclusive mode semantics.
- Adapt a candidate row into input for the current multi-agent workflow.
- Tests and a runnable local demo using the existing Kafka mock publisher.

### Excluded

- Merging the old Kafka consumer or its `transactions` topic.
- Realtime multi-agent execution.
- Direct integration with a real payment authorization system.
- Actual account freezing, fund reversal, SAR/STR submission, or customer notification.
- Refactoring the current multi-agent/legal-routing internals.
- Frontend controls.
- Production PostgreSQL migration, distributed locks, HA scheduling, or multi-broker deployment.

## 4. Reuse Assessment

### Reuse selectively

From commit `33b8a55` and `origin/feature/-ML-model`:

- the four baseline rule ideas;
- the ordered 38-feature contract;
- the XGBoost JSON model artifact;
- model loading and `predict_proba` behavior;
- compatible static and rolling feature formulas.

### Do not merge directly

- the old Kafka consumer, because it uses topic `transactions`, auto-commit, sequential rule/ML execution, and precomputed features in each message;
- the committed SQLite binary and generated consumer log;
- the old ticket API/repository as the queue contract;
- the older multi-agent branch, because the current branch already contains a newer workflow and the old branch restores obsolete HITL contracts.

The current multi-agent graph is integrated through its public `build_workflow()` and `initial_state()` contracts. This phase does not attempt to correct unrelated multi-agent/legal issues.

## 5. Components

### 5.1 DetectionSettings

Owns Kafka input topic/group, model path, database path, review/block thresholds, timezone, automatic run hour, candidate retry limit, and feature-window bounds. It validates:

- `0 <= review_threshold < block_threshold <= 1`;
- auto hour is `0..23`;
- timezone exists;
- paths and required model metadata are available before the worker consumes records.

### 5.2 RuleEngine

Input: canonical transaction plus explicitly available enrichment values.
Output: a list of structured `RuleHit` records, not a single free-text string.

Initial rules are adapted from the old implementation:

- high-risk owner/profile;
- abnormal IP/device sharing velocity;
- high-value cross-border transfer involving a high-risk bank;
- high-value transfer from a newly opened account.

Each hit contains `rule_id`, `summary`, `severity`, and the non-secret observed values used by the condition. Missing inputs produce no hit and are listed in rule metadata; malformed values do not silently become suspicious values.

### 5.3 RealtimeFeatureExtractor

Produces an ordered `FeatureSnapshotV1` matching the reused XGBoost model. It combines:

- fields from `TransactionEventV1`;
- bounded static enrichment from the existing repository when an entity/account is known;
- per-process rolling 1-hour/24-hour state for source/destination activity;
- explicit numeric defaults for fields unavailable in the current Kafka contract.

The snapshot records `imputed_features` and the exact feature-order version. The MVP accepts documented zero imputation to remain compatible with the old model, but the result is simulation-grade and must not be represented as a calibrated production blocking model.

Rolling state is bounded and in-memory for this phase. Restarting the detection worker starts a cold window; this limitation is exposed in logs and model metadata. Persisting all allowed transactions solely to rebuild rolling windows is explicitly excluded because allowed decisions must not be stored in the queue database.

### 5.4 XGBoostPredictor

Loads the model once at process startup, verifies the expected feature count/order, and returns:

- suspicious-class confidence;
- model version/hash;
- feature contract version;
- imputed feature names.

Missing/corrupt model or feature-shape mismatch is a processing failure, never an implicit `ALLOWED` decision.

### 5.5 RiskAggregator

Pure deterministic function receiving `RuleEvaluation` and `ModelPrediction`. It returns one `DetectionDecision`:

- `BLOCKED` with reason `ML_BLOCK_THRESHOLD`;
- `QUEUED` with reason `RULE_HIT`, `ML_REVIEW_THRESHOLD`, or `RULE_AND_ML`;
- `ALLOWED` with reason `NO_SUSPICIOUS_SIGNAL`.

It does not access Kafka, SQLite, the model, or the multi-agent workflow.

### 5.6 DetectionRepository

Repository interface with an initial SQLite implementation at:

```text
backend/data/detection_queue.db
```

The database file is runtime data and must not be committed. The repository owns schema initialization, idempotent inserts, mode changes, candidate claiming, completion/failure updates, retry accounting, and recovery of expired processing leases.

It can later be replaced by PostgreSQL without changing detection or multi-agent components.

### 5.7 DetectionWorker

Consumes `aml.transactions.validated.v1` with auto-commit disabled. For each record:

1. validate `TransactionEventV1` again at the service boundary;
2. submit RuleEngine and feature-plus-model branches concurrently;
3. aggregate both results;
4. persist `BLOCKED` or `QUEUED`, or persist nothing for `ALLOWED`;
5. commit the source Kafka offset only after the selected database action succeeds.

If the process crashes after a database commit but before Kafka offset commit, replay is safe because `event_id` is unique and repository writes are idempotent.

Rule/model exceptions do not become `ALLOWED`. The worker leaves the Kafka offset uncommitted and exits with a clear metadata-only error so an operator can fix the model/configuration and restart it.

## 6. Persistence Model

### blocked_transactions

| Field | Purpose |
|---|---|
| `block_id` | Stable generated identifier |
| `event_id` | Unique Kafka event identity |
| `transaction_id` | Banking transaction identity |
| `transaction_payload_json` | Canonical transaction snapshot |
| `ml_confidence` | Suspicious-class probability |
| `model_version` | Model artifact identity |
| `rule_hits_json` | Structured rule results |
| `decision` | Always `BLOCKED` |
| `blocked_at` | UTC decision time |
| `response_status` | `SIMULATED_DELIVERED` for this phase |

Blocked rows have no candidate status and can never be claimed by an investigation runner.

### investigation_candidates

| Field | Purpose |
|---|---|
| `candidate_id` | Stable generated identifier |
| `event_id` | Unique Kafka event identity |
| `transaction_id` | Banking transaction identity |
| `transaction_payload_json` | Canonical transaction snapshot for agent input |
| `ml_confidence` | Suspicious-class probability |
| `model_version` | Model artifact identity |
| `rule_hits_json` | Structured rule hits |
| `trigger_reason` | `RULE_HIT`, `ML_REVIEW_THRESHOLD`, or `RULE_AND_ML` |
| `status` | `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED` |
| `created_at` | UTC enqueue time |
| `lease_until` | Recovery boundary for abandoned work |
| `attempt_count` | Number of claims |
| `last_error` | Safe error class/message without secrets |
| `case_id` | Multi-agent case identity after claim |
| `completed_at` | UTC terminal time |

Unique constraints on `event_id` prevent replay duplicates. A transaction may generate multiple upstream events only if they use different event IDs; transaction-level deduplication is not inferred.

### runner_settings

A singleton row stores `run_mode` as `AUTO` or `MANUAL`, plus `updated_at`.

- `AUTO`: only an automatic trigger may claim candidates.
- `MANUAL`: only an explicit manual trigger may claim candidates.
- A manual invocation while mode is `AUTO` fails before claiming anything.
- An automatic invocation while mode is `MANUAL` exits successfully without claiming anything.

## 7. Candidate-to-Agent Boundary

The runner transforms one claimed row into:

```json
{
  "case_id": "CASE-CANDIDATE-000001",
  "alert": {
    "candidate_id": "CANDIDATE-000001",
    "transaction_id": "TX-001",
    "transaction_event": {},
    "detection": {
      "ml_confidence": 0.83,
      "model_version": "...",
      "rule_hits": [],
      "trigger_reason": "ML_REVIEW_THRESHOLD"
    }
  }
}
```

The complete canonical transaction snapshot is retained because a Kafka transaction may not exist in the generated repository used by current tools. The initial integration passes this snapshot in the alert and preserves it as candidate evidence. Where the existing agent requires repository lookup, a narrowly scoped candidate-transaction adapter supplies the stored snapshot; the general transaction repository is not rewritten.

On success, the runner stores the generated `case_id` and marks the candidate `COMPLETED`. On failure, it increments attempts and returns the row to `PENDING` until the configured retry limit, after which it becomes `FAILED`. One failing candidate does not prevent later candidates from running.

## 8. Automatic and Manual Execution

For the fastest reliable implementation, scheduling is separated from business logic:

- `run_pending_investigations.py --trigger auto` is invoked daily at 02:00 Asia/Ho_Chi_Minh by cron, CI scheduler, or the deployment platform. It first checks `run_mode=AUTO`, then runs until no claimable candidates remain.
- `run_pending_investigations.py --trigger manual` is invoked by an operator. It only runs when `run_mode=MANUAL`, then runs until the queue is empty or an optional limit is reached.
- `set_investigation_mode.py auto|manual` changes the singleton setting.

This avoids an always-running in-process scheduler and makes missed-run recovery straightforward: invoke the same auto command again. The runner claims one row at a time in this phase because the current multi-agent graph is heavyweight and its correctness is more important than parallel case throughput.

## 9. Alternatives Considered

### A. SQLite repository plus externally scheduled runner — selected

Fastest local/demo path, easy status queries, deterministic tests, no new infrastructure, and clean migration boundary. It is limited to one host and modest write concurrency.

### B. PostgreSQL queue with row locking

Best production direction and supports multiple workers through `FOR UPDATE SKIP LOCKED`, but requires schema migrations, deployment configuration, and integration work outside this narrow phase.

### C. Kafka candidate and blocked topics only

Good streaming decoupling but poor fit for manual querying, candidate lifecycle, retries, mode control, and “run until queue empty” without an additional durable state store. It does not remove the need for a database.

## 10. Failure and Safety Invariants

- `ALLOWED` decisions create no database row.
- A rule hit with ML below `0.60` is still `QUEUED`.
- Rules never auto-block in this phase.
- Only a valid ML confidence at or above `0.99` is `BLOCKED`.
- Blocked rows are never visible to candidate claim queries.
- Multi-agent is never called from the Kafka detection worker.
- Manual and automatic claims are mutually exclusive by persisted run mode.
- A Kafka offset is never committed before the required SQLite transaction commits.
- Duplicate Kafka delivery cannot create duplicate blocked/candidate rows.
- Model/rule failure cannot silently allow a transaction.
- Logs contain IDs, scores, rule IDs, statuses, and safe error types; they do not dump full transaction payloads.
- No real blocking, freezing, reversal, reporting, or customer notification is claimed by the simulation.

## 11. Verification

Unit tests cover:

- thresholds and invalid settings;
- each initial rule and missing input behavior;
- exact feature order and rolling-window behavior;
- model load/shape failures;
- all aggregator truth-table combinations;
- no persistence for allowed decisions;
- blocked/candidate separation;
- event replay idempotency;
- commit-after-persistence ordering;
- no offset commit on detection/persistence failure;
- AUTO/MANUAL mutual exclusion;
- candidate claim, lease recovery, retry, failure, and completion;
- candidate-to-agent input mapping.

An end-to-end local smoke test covers:

1. start Kafka and detection worker;
2. publish events through the existing mock producer;
3. force one allowed, queued, and blocked outcome through injectable test predictor/rules;
4. verify allowed creates no row;
5. verify blocked is isolated from agent claims;
6. verify queued candidate is processed only by the permitted trigger mode;
7. verify the multi-agent runner records completion or a bounded failure without invoking it realtime.

## 12. Implementation Order

1. Contracts, settings, and pure aggregator.
2. RuleEngine and feature/model adapters with tests.
3. SQLite repository and idempotent persistence.
4. Kafka detection worker and offset semantics.
5. Candidate-to-agent adapter and AUTO/MANUAL runner.
6. Local scripts, environment examples, documentation, and focused end-to-end smoke test.
