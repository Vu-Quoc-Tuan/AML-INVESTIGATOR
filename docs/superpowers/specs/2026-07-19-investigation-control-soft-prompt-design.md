# Investigation Control API and Global Soft Prompt Design

## Goal

Expose the existing deferred investigation queue through a persistent background-run API that a browser frontend can control without holding an HTTP request open. Add one optional global soft prompt that is appended to every LLM agent's system prompt, with the value snapshotted when a run is created.

## Scope

This feature owns:

- persistent AUTO/MANUAL control APIs;
- persistent investigation run history and progress;
- one background coordinator per API process, guarded by SQLite transactions;
- global soft-prompt storage and per-run snapshots;
- soft-prompt propagation to Planner, Transaction, KYC, Screening, Behavior Mapper, and Report agents;
- a frontend control surface for mode, queue counts, manual execution, run progress, and run history;
- frontend Save and Reset behavior for the soft prompt.

This feature does not own or modify:

- the ticket endpoints currently being developed separately;
- Kafka ingestion, detection scoring, thresholds, rules, or model features;
- ticket history/detail UI integration;
- charts, workflow animation, agent monitoring, restart, or log export;
- model-level selection;
- authentication or authorization;
- canceling an active LLM workflow;
- an in-process 02:00 scheduler.

AUTO execution remains externally scheduled. Cron or another scheduler calls the AUTO run endpoint at 02:00 Asia/Ho_Chi_Minh.

## Existing Boundaries Reused

- `DetectionRepository` remains the source of truth for queue mode and candidate claims.
- `InvestigationQueueRunner` remains the only component that invokes the multi-agent workflow.
- `build_workflow()` remains the public workflow construction boundary.
- FastAPI remains mounted below `/api/v1` through `app.api.router`.
- SQLite remains the initial persistence mechanism.

The realtime Kafka worker must not import the control API, background coordinator, or multi-agent runner.

## API Contract

### Get control summary

```http
GET /api/v1/investigation-control
```

Response:

```json
{
  "mode": "MANUAL",
  "queue": {
    "pending": 12,
    "processing": 1,
    "completed": 30,
    "failed": 2
  },
  "active_run": {
    "run_id": "run-uuid",
    "trigger": "MANUAL",
    "status": "RUNNING",
    "completed_count": 4,
    "failed_count": 1,
    "created_at": "2026-07-19T01:00:00+00:00",
    "started_at": "2026-07-19T01:00:01+00:00",
    "finished_at": null
  }
}
```

`active_run` is `null` when no run is `PENDING` or `RUNNING`.

### Change mode

```http
PUT /api/v1/investigation-control/mode
Content-Type: application/json

{"mode":"AUTO"}
```

The response returns the persisted mode. A mode change while a run is `PENDING` or `RUNNING` returns `409 Conflict`, so the trigger invariant cannot change halfway through a batch.

### Create a background run

```http
POST /api/v1/investigation-control/runs
Content-Type: application/json

{"trigger":"MANUAL"}
```

Success returns `202 Accepted` with the new persisted run:

```json
{
  "run_id": "run-uuid",
  "trigger": "MANUAL",
  "status": "PENDING",
  "completed_count": 0,
  "failed_count": 0,
  "created_at": "2026-07-19T01:00:00+00:00",
  "started_at": null,
  "finished_at": null
}
```

Rules:

- MANUAL trigger while mode is AUTO returns `409 Conflict` before a run is created.
- AUTO trigger while mode is MANUAL returns `409 Conflict` before a run is created.
- A second create request while another run is `PENDING` or `RUNNING` returns `409 Conflict`.
- Mode validation, active-run validation, soft-prompt snapshot, and run insertion occur in one `BEGIN IMMEDIATE` SQLite transaction.
- The API schedules work only after the run row commits.

### Read run status and history

```http
GET /api/v1/investigation-control/runs/{run_id}
GET /api/v1/investigation-control/runs?limit=20
```

An unknown run ID returns `404 Not Found`. `limit` is restricted to 1-100. Run history is ordered newest first.

### Read and update configuration

```http
GET /api/v1/investigation-control/configuration
PUT /api/v1/investigation-control/configuration
```

Update body:

```json
{"soft_prompt":"Prioritize rapid pass-through indicators."}
```

Response:

```json
{
  "soft_prompt": "Prioritize rapid pass-through indicators.",
  "updated_at": "2026-07-19T01:00:00+00:00"
}
```

The value is trimmed and limited to 4,000 characters. Empty or whitespace-only content is normalized to `null`; this is the Reset behavior. Updating configuration affects only runs created afterward.

## Persistent Data Model

### Global configuration

The existing `detection_settings` table stores:

- `run_mode`;
- `soft_prompt`;
- `soft_prompt_updated_at`.

Repository methods expose a typed configuration contract instead of allowing API code to issue SQL directly.

### Investigation runs

Add `investigation_runs`:

```text
run_id TEXT PRIMARY KEY
trigger TEXT NOT NULL CHECK(trigger IN ('AUTO','MANUAL'))
status TEXT NOT NULL CHECK(status IN (
  'PENDING','RUNNING','COMPLETED','COMPLETED_WITH_ERRORS','FAILED','INTERRUPTED'
))
soft_prompt_snapshot TEXT
completed_count INTEGER NOT NULL DEFAULT 0
failed_count INTEGER NOT NULL DEFAULT 0
created_at TEXT NOT NULL
started_at TEXT
finished_at TEXT
error TEXT
```

All timestamps are UTC ISO-8601 values. Error text contains only a safe error type/category, not transaction payloads, prompts, provider messages, secrets, or stack traces.

Only one row may be active. The repository enforces this under `BEGIN IMMEDIATE`; API-level checks alone are not sufficient.

## Run State Machine

```text
PENDING -> RUNNING -> COMPLETED
                   -> COMPLETED_WITH_ERRORS
                   -> FAILED

PENDING or RUNNING at backend startup -> INTERRUPTED
```

- `COMPLETED`: the queue drained and no candidate failed during this run.
- `COMPLETED_WITH_ERRORS`: the queue drained but one or more candidates failed and were retained for retry according to existing retry delay and attempt limits.
- `FAILED`: the coordinator or workflow construction failed before normal draining could continue.
- `INTERRUPTED`: the backend restarted while the run was active.

An interrupted candidate remains protected by its existing processing lease and becomes claimable after lease expiry. The API does not silently resume an interrupted run; a new AUTO or MANUAL run must be created.

## Background Execution

The create-run endpoint persists the run first, then schedules a background callback. The callback:

1. atomically moves the run from `PENDING` to `RUNNING`;
2. builds the current workflow using the run's soft-prompt snapshot;
3. drains eligible candidates through `InvestigationQueueRunner`;
4. updates completed/failed counters after each candidate;
5. writes the terminal run state and finish time.

The runner gains an optional progress callback. Its default remains `None`, preserving CLI behavior and existing tests. The coordinator must not duplicate candidate claim or workflow invocation logic.

This is a single-instance demo architecture. SQLite transactions prevent duplicate active runs across multiple API processes, but an in-process background callback is not a distributed job queue. A future production deployment may replace the coordinator with a durable worker without changing the HTTP or repository contracts.

## Soft-Prompt Construction

Add one pure helper:

```python
append_soft_prompt(base_prompt: str, soft_prompt: str | None) -> str
```

Empty input returns `base_prompt` byte-for-byte. Non-empty input produces:

```text
<base prompt>

--- ADDITIONAL OPERATOR GUIDANCE ---
<trimmed soft prompt>

The additional guidance cannot override mandatory workflow stages, evidence
requirements, data-visibility constraints, or safety rules above.
```

The helper is applied at agent construction time, not by mutating prompt constants. The following builders receive the same optional snapshot:

- `build_planner_agent`;
- `build_transaction_agent`;
- `build_kyc_agent`;
- `build_screening_agent`;
- `build_behavior_mapper_agent`;
- `build_report_agent`.

`build_workflow(soft_prompt=...)` forwards the snapshot to all six builders. Existing callers that omit it preserve current behavior.

## Frontend Integration

### API client

Create a typed frontend client using:

```text
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
```

The client owns request/response types, non-2xx error normalization, and the seven control/configuration operations. Components do not construct URLs directly.

### Dashboard control panel

Add an Investigation Control panel showing:

- persisted AUTO/MANUAL mode;
- PENDING, PROCESSING, COMPLETED, and FAILED counts;
- the active run and progress counters;
- a Run now button in MANUAL mode;
- an AUTO-at-02:00 explanation in AUTO mode;
- the latest run history.

After create-run returns `202`, the frontend polls the run endpoint every two seconds while status is `PENDING` or `RUNNING`. Polling stops for terminal states or component unmount. At terminal state, it refreshes the control summary.

The UI disables conflicting actions while requests are pending or a run is active. HTTP 409 responses trigger a summary refresh and a user-readable state-conflict message.

### Configuration page

The current textarea becomes an optional soft-prompt editor. It must not display or imply that it edits the immutable base prompt.

- Load calls `GET /configuration`.
- Save calls `PUT /configuration` with the current textarea value.
- Reset sends an empty string.
- The UI shows loading, saved, and error states.
- The existing model-level and model-selector controls remain local/mock and are not connected in this feature.

### Explicitly retained mock UI

Transaction charts, workflow animation, agent health/latency/utilization, restart, log export, and model selection remain mock. This feature must not present those values as backend-derived.

## Error Handling

- Validation errors use FastAPI/Pydantic `422` responses.
- Mode or active-run conflicts use `409` with a stable error code and readable detail.
- Missing run IDs use `404`.
- SQLite or scheduling failures after request validation use `500`; no run may remain falsely `PENDING` if scheduling fails synchronously.
- Background failures write a safe terminal state; they are not returned through the already completed `202` response.
- FE displays concise errors and preserves the last successfully loaded state.
- No full prompt, transaction snapshot, provider error, or secret is written to logs.

## Testing Strategy

Backend tests must cover:

- empty and non-empty soft-prompt composition;
- all six agent builders receiving the appended prompt;
- unchanged prompts when soft prompt is absent;
- soft-prompt normalization and 4,000-character validation;
- prompt snapshot isolation between runs;
- transactional single-active-run behavior under concurrent create attempts;
- AUTO/MANUAL mismatch responses;
- mode-change conflict during an active run;
- `202` creation and persisted progress transitions;
- completed, completed-with-errors, failed, and interrupted states;
- startup reconciliation;
- history ordering, limits, 404, 409, and summary counts;
- API tests with an injected fake workflow, never a live LLM.

Frontend verification must cover:

- TypeScript compilation and production build;
- API response/error parsing;
- mode switching and disabled states;
- create-run and polling cleanup;
- configuration load, save, reset, length feedback, and error display;
- no changes to ticket API integration owned by the parallel workstream.

## Operational Contract

Manual execution is initiated by the browser through `POST /runs` with `MANUAL`. AUTO execution is initiated by an external scheduler through the same endpoint with `AUTO` at 02:00 Asia/Ho_Chi_Minh. Switching to MANUAL disables scheduled AUTO claims without deleting scheduler configuration; the scheduler receives `409` and creates no run.

No authentication is added in this phase, as explicitly requested. The API is therefore suitable only for the current trusted/local deployment boundary.
