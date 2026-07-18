# Realtime Detection Queue Implementation Plan

> **Required subskill:** Execute this plan inline with `executing-plans`; use `verification-before-completion` before reporting completion. Do not delegate because repository instructions require tightly scoped ownership.

**Goal:** Consume validated Kafka transactions, score rules and XGBoost concurrently, block only ML confidence `>= 0.99`, queue rule hits or ML confidence `[0.60, 0.99)`, discard low-risk events, and run queued investigations only through explicit AUTO or MANUAL batch execution.

**Architecture:** A detection worker owns Kafka consumption and two concurrent, side-effect-free scoring branches. A pure aggregator produces one decision. A SQLite repository persists only blocked and queued outcomes and provides transactional lease-based claims. A separate runner adapts candidate snapshots to the existing investigation workflow; it is never called by the realtime worker.

**Tech Stack:** Python 3.11+, Pydantic 2, kafka-python, SQLite, NumPy, XGBoost, pytest, existing LangGraph investigation workflow.

**Global Constraints:** Touch only `app/detection`, detection scripts/tests/model/config/dependencies/docs and the Kafka client factory extension directly required by this flow. Do not refactor multi-agent, legal, screening, KYC, transaction tools, frontend, Docker, or CI/CD. Do not persist `ALLOWED` events. Do not auto-block from rules. Do not run multi-agent realtime. Do not log full transaction payloads. Do not commit runtime SQLite files.

---

## Task 1: Freeze detection contracts, settings, and decision boundaries

**Files:**
- Create: `backend/app/detection/contracts.py`
- Create: `backend/app/detection/config.py`
- Modify: `backend/app/detection/risk_aggregator.py`
- Modify: `backend/app/detection/__init__.py`
- Test: `backend/tests/unit/detection/test_config.py`
- Test: `backend/tests/unit/detection/test_risk_aggregator.py`

**Step 1: Write failing boundary tests**

Cover exact ML boundaries `0.0`, `0.599999`, `0.60`, `0.989999`, `0.99`, `1.0`; rule-only hits; invalid/non-finite confidence; and the invariant that rules never produce `BLOCKED`.

```python
assert aggregate(no_rules, prediction(0.599999), settings).kind is DecisionKind.ALLOWED
assert aggregate(no_rules, prediction(0.60), settings).kind is DecisionKind.QUEUED
assert aggregate(no_rules, prediction(0.99), settings).kind is DecisionKind.BLOCKED
assert aggregate(rule_hit, prediction(0.01), settings).kind is DecisionKind.QUEUED
```

Run: `cd backend && .venv/bin/pytest tests/unit/detection/test_config.py tests/unit/detection/test_risk_aggregator.py -q`

Expected: FAIL because contracts/config/aggregator are not implemented.

**Step 2: Implement typed contracts and validated settings**

Add enums/dataclasses for `DecisionKind`, `CandidateStatus`, `RunMode`, `RunTrigger`, `RuleHit`, `RuleEvaluation`, `FeatureSnapshot`, `ModelPrediction`, `DetectionDecision`, and persisted candidate records. Add `DetectionSettings.from_env()` with:

```text
DETECTION_DB_PATH=backend/data/detection_queue.db
DETECTION_ML_QUEUE_THRESHOLD=0.60
DETECTION_ML_BLOCK_THRESHOLD=0.99
DETECTION_MODEL_PATH=backend/model/xgb_model.json
DETECTION_GROUP_ID=aml-detection-v1
DETECTION_CLIENT_ID=aml-realtime-detection
DETECTION_RUN_MODE=MANUAL
DETECTION_CLAIM_LEASE_SECONDS=1800
DETECTION_MAX_ATTEMPTS=3
```

Validate `0 <= queue < block <= 1`, positive lease/attempt values, and non-empty identifiers/paths.

**Step 3: Implement pure aggregation**

The aggregator returns `BLOCKED` only for a valid ML probability `>= block_threshold`; otherwise `QUEUED` for any rule hit or ML probability `>= queue_threshold`; otherwise `ALLOWED`. Preserve rule identifiers, confidence, model version, and imputation metadata in the decision.

**Step 4: Run focused tests**

Run: `cd backend && .venv/bin/pytest tests/unit/detection/test_config.py tests/unit/detection/test_risk_aggregator.py -q`

Expected: PASS.

**Step 5: Commit the slice**

```bash
git add backend/app/detection/contracts.py backend/app/detection/config.py backend/app/detection/risk_aggregator.py backend/app/detection/__init__.py backend/tests/unit/detection/test_config.py backend/tests/unit/detection/test_risk_aggregator.py
git commit -m "feat(detection): define scoring decisions and thresholds"
```

## Task 2: Implement the lightweight rule branch

**Files:**
- Modify: `backend/app/detection/rules.py`
- Test: `backend/tests/unit/detection/test_rules.py`

**Step 1: Write failing rule tests**

Test four explicit rules with isolated fixtures and missing enrichment:

1. high-risk/watchlisted source or destination;
2. IP or device sharing count above configured limits;
3. cross-border high-value transfer involving a high-risk bank;
4. high-value transfer from a newly opened source account.

Also assert deterministic rule ordering, stable rule IDs, no exception on absent optional fields, and no `BLOCKED` concept in rule output.

**Step 2: Implement `RuleEngine.evaluate(event, enrichment)`**

Use Python predicates only. Keep thresholds in a frozen `RuleSettings` dataclass. Return structured hits containing rule ID, reason, and non-sensitive evidence fields. Never perform DB/network calls.

**Step 3: Verify and commit**

Run: `cd backend && .venv/bin/pytest tests/unit/detection/test_rules.py -q`

Expected: PASS.

```bash
git add backend/app/detection/rules.py backend/tests/unit/detection/test_rules.py
git commit -m "feat(detection): add realtime rule engine"
```

## Task 3: Implement realtime features and the XGBoost adapter

**Files:**
- Modify: `backend/app/detection/features.py`
- Modify: `backend/app/detection/anomaly_model.py`
- Create: `backend/model/xgb_model.json` from `origin/feature/-ML-model`
- Modify: `backend/requirements.txt`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/unit/detection/test_features.py`
- Test: `backend/tests/unit/detection/test_anomaly_model.py`

**Step 1: Write failing feature tests**

Assert exact 38-column order used to train the existing artifact. Test 1h/24h source and destination rolling counts/amounts, cross-border flag, deterministic zero-imputation, imputed feature-name reporting, pruning of old observations, and thread safety under concurrent calls. Use timezone-aware fixed timestamps.

**Step 2: Implement bounded in-memory feature extraction**

Implement per-account deques protected by a lock. Compute fields available from `TransactionEventV1` and optional enrichment. Zero-impute unavailable legacy fields and return their names. Update rolling state exactly once after producing the current-event features, so the event does not count itself.

**Step 3: Write failing model-adapter tests**

Test missing artifact, wrong feature vector length/order, non-finite output, and successful probability extraction using an injected fake booster. A model/configuration error must raise; it must never become low-risk.

**Step 4: Add model artifact and dependencies**

Restore only `backend/model/xgb_model.json` from `origin/feature/-ML-model`. Add compatible `numpy` and `xgboost` runtime dependencies to both dependency manifests. Do not restore training data or old consumer code.

**Step 5: Implement `XGBoostPredictor`**

Load the booster once, build a `DMatrix` with exact feature names, return the suspicious-class probability and a stable model version derived from artifact metadata/hash. Reject probabilities outside `[0, 1]` or non-finite values.

**Step 6: Verify and commit**

Run: `cd backend && .venv/bin/pytest tests/unit/detection/test_features.py tests/unit/detection/test_anomaly_model.py -q`

Expected: PASS.

```bash
git add backend/app/detection/features.py backend/app/detection/anomaly_model.py backend/model/xgb_model.json backend/requirements.txt backend/pyproject.toml backend/tests/unit/detection/test_features.py backend/tests/unit/detection/test_anomaly_model.py
git commit -m "feat(detection): add realtime XGBoost scoring"
```

## Task 4: Build the durable SQLite outcome repository

**Files:**
- Create: `backend/app/detection/repository.py`
- Modify: `.gitignore`
- Modify: `backend/.gitignore`
- Test: `backend/tests/unit/detection/test_repository.py`

**Step 1: Write failing repository tests**

Use a temporary DB. Cover schema initialization, separate `blocked_transactions` and `investigation_candidates`, full canonical snapshot storage, unique `event_id`, replay idempotency, no allowed-record API, initial mode, mode changes, FIFO claims, attempts, leases, expired-lease recovery, completed/failed transitions, retry exhaustion, safe error truncation, and concurrent claims returning different candidates.

Also test a mode switch race: mode verification and claim must occur in the same `BEGIN IMMEDIATE` transaction.

**Step 2: Implement repository and migrations**

Use stdlib `sqlite3`, WAL, foreign keys, `busy_timeout`, UTC ISO timestamps, and parameterized SQL. Initialize schema through versioned `PRAGMA user_version`. For queued/blocked writes, use `BEGIN IMMEDIATE`, check both outcome tables for the `event_id`, then insert into exactly one table. Return the existing outcome on replay without duplicating it.

Implement `claim_next(trigger, now)` so:

- MANUAL trigger raises before claim if persisted mode is AUTO;
- AUTO trigger returns no work if persisted mode is MANUAL;
- eligible `PENDING` or expired `PROCESSING` rows are atomically leased;
- rows at max attempts are not reclaimed.

**Step 3: Ignore runtime DB artifacts**

Ignore `backend/data/detection_queue.db`, its `-wal` and `-shm` files without ignoring source/model fixtures.

**Step 4: Verify and commit**

Run: `cd backend && .venv/bin/pytest tests/unit/detection/test_repository.py -q`

Expected: PASS.

```bash
git add backend/app/detection/repository.py backend/tests/unit/detection/test_repository.py .gitignore backend/.gitignore
git commit -m "feat(detection): persist blocked and queued outcomes"
```

## Task 5: Wire the realtime Kafka detection worker

**Files:**
- Modify: `backend/app/streaming/clients.py`
- Create: `backend/app/detection/worker.py`
- Create: `backend/scripts/run_detection_worker.py`
- Test: `backend/tests/unit/detection/test_worker.py`
- Test: `backend/tests/unit/streaming/test_clients.py`

**Step 1: Write failing worker tests with fakes**

Cover:

- validated-topic subscription with a distinct detection group/client;
- exactly two concurrent futures: rule evaluation and feature extraction plus prediction;
- `BLOCKED` writes only blocked table then commits `offset + 1`;
- `QUEUED` writes only candidate table then commits `offset + 1`;
- `ALLOWED` performs no repository write then commits `offset + 1`;
- malformed canonical event, rule error, feature error, model error, aggregation error, and DB error do not commit;
- replayed queued/blocked event commits after idempotent repository success;
- executor and consumer close cleanly.

**Step 2: Extend consumer construction narrowly**

Add a validated-topic consumer factory or parameterized topic factory while preserving the current raw-ingestion behavior and tests. Keep `enable_auto_commit=False`.

**Step 3: Implement worker orchestration**

Parse `TransactionEventV1`, submit the two branches to `ThreadPoolExecutor(max_workers=2)`, aggregate only after both succeed, persist according to the decision, and manually commit the consumed offset. Log only event/transaction IDs, decision, confidence, rule IDs, partition and offset.

**Step 4: Add executable CLI composition root**

Build settings, repository, rule engine, feature extractor, predictor, consumer and worker in `run_detection_worker.py`. Support graceful SIGINT/SIGTERM shutdown. Do not import or call the multi-agent workflow.

**Step 5: Verify and commit**

Run: `cd backend && .venv/bin/pytest tests/unit/detection/test_worker.py tests/unit/streaming/test_clients.py -q`

Expected: PASS.

```bash
git add backend/app/streaming/clients.py backend/app/detection/worker.py backend/scripts/run_detection_worker.py backend/tests/unit/detection/test_worker.py backend/tests/unit/streaming/test_clients.py
git commit -m "feat(detection): consume and score validated transactions"
```

## Task 6: Add AUTO/MANUAL investigation queue runner

**Files:**
- Create: `backend/app/detection/agent_adapter.py`
- Create: `backend/app/detection/runner.py`
- Create: `backend/scripts/run_pending_investigations.py`
- Create: `backend/scripts/set_investigation_mode.py`
- Test: `backend/tests/unit/detection/test_agent_adapter.py`
- Test: `backend/tests/unit/detection/test_runner.py`

**Step 1: Write failing adapter and runner tests**

Assert candidate snapshot maps to `initial_state(case_id, alert)` without modifying workflow internals. Test one-candidate success, workflow exception, safe error persistence, retry, drain-until-empty, unique LangGraph `thread_id`, MANUAL refusal in AUTO mode, and AUTO no-op in MANUAL mode. Inject a fake workflow; unit tests must not call an LLM or external service.

**Step 2: Implement the narrow agent adapter**

Build an alert containing transaction snapshot, decision, ML result, rule hits, and candidate metadata. Generate stable case IDs from candidate IDs. Do not patch transaction tools or orchestrator state.

**Step 3: Implement batch runner**

Claim one row at a time, invoke the injected/default current `build_workflow()`, mark completed with case ID or failed with a safe message, and continue according to retry semantics. The realtime worker must have no import path to this runner.

**Step 4: Implement operational CLIs**

`run_pending_investigations.py --trigger auto|manual` drains eligible work. `set_investigation_mode.py AUTO|MANUAL` updates persisted mode. AUTO scheduling remains external; cron invokes the runner at 02:00 `Asia/Ho_Chi_Minh`.

**Step 5: Verify and commit**

Run: `cd backend && .venv/bin/pytest tests/unit/detection/test_agent_adapter.py tests/unit/detection/test_runner.py -q`

Expected: PASS.

```bash
git add backend/app/detection/agent_adapter.py backend/app/detection/runner.py backend/scripts/run_pending_investigations.py backend/scripts/set_investigation_mode.py backend/tests/unit/detection/test_agent_adapter.py backend/tests/unit/detection/test_runner.py
git commit -m "feat(detection): run queued multi-agent investigations"
```

## Task 7: Prove the pipeline end to end and document operation

**Files:**
- Create: `backend/tests/integration/test_realtime_detection_pipeline.py`
- Modify: `backend/.env.example`
- Create: `backend/README-DETECTION.md`

**Step 1: Write a local integration test without external services**

Use fake Kafka records/consumer, deterministic predictor, real SQLite temp DB, real rules/features/aggregator, and fake workflow. Exercise all three decisions and prove:

```text
ALLOWED -> no row, committed
QUEUED  -> candidate row, committed, later runner completes it
BLOCKED -> blocked row, committed, never visible to runner
```

Also prove a scoring failure leaves the offset uncommitted.

**Step 2: Document exact environment and run commands**

Update `.env.example` with detection-only variables. Document:

- source topic: `aml.transactions.validated.v1`;
- Kafka brokers come from `KAFKA_BOOTSTRAP_SERVERS`;
- DB location and tables;
- worker command;
- AUTO/MANUAL switch commands;
- manual drain command;
- 02:00 Asia/Ho_Chi_Minh cron example;
- SQLite inspection queries;
- mock producer/relay commands from the existing streaming service;
- restart/cold rolling-feature limitation;
- zero-imputation and uncalibrated 0.99 blocking warning;
- troubleshooting for Kafka, missing model, locked DB and agent failures.

**Step 3: Run focused and full regression verification**

```bash
cd backend
.venv/bin/pytest tests/unit/detection tests/unit/streaming tests/integration/test_realtime_detection_pipeline.py -q
.venv/bin/pytest tests/unit -q
.venv/bin/python -m compileall -q app/detection scripts
```

Expected: all commands exit `0`.

If Docker Kafka is available, run the documented mock producer -> relay -> detection worker smoke path and inspect SQLite. If it is unavailable, report that runtime boundary explicitly; do not claim live Kafka stability from fake tests.

**Step 4: Inspect scope and secrets**

Run:

```bash
git status --short
git diff --stat HEAD~6..HEAD
git diff --check HEAD~6..HEAD
rg -n "API_KEY=.+|NVIDIA_API=.+|BEGIN (RSA|OPENSSH) PRIVATE KEY" backend/app/detection backend/scripts backend/.env.example
```

Expected: only planned files changed; `git diff --check` clean; no secrets.

**Step 5: Commit documentation and integration proof**

```bash
git add backend/tests/integration/test_realtime_detection_pipeline.py backend/.env.example backend/README-DETECTION.md
git commit -m "test(detection): verify realtime queue pipeline"
```

## Final acceptance checklist

- Exact thresholds: `<0.60 ALLOWED`, `[0.60,0.99) QUEUED`, `>=0.99 BLOCKED`.
- Any rule hit queues but never blocks.
- ALLOWED creates no database record.
- BLOCKED and QUEUED are stored separately and idempotently by `event_id`.
- Rule and ML branches actually execute concurrently.
- Kafka auto-commit is disabled and offsets remain uncommitted on any scoring/storage failure.
- Realtime worker cannot invoke multi-agent code.
- Only the batch runner imports the current investigation workflow.
- AUTO/MANUAL gate is transactional with candidate claim.
- Runtime SQLite files and secrets are untracked.
- No changes outside the approved detection boundary and direct wiring/config/docs/tests.
