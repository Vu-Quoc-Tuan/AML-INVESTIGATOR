# Investigation Control and Soft Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent AUTO/MANUAL background-run APIs, append one snapshotted global soft prompt to all six investigation agents, and connect the existing frontend Dashboard and Configuration screens to those APIs.

**Architecture:** A new `app.investigation_control` package owns configuration, run persistence, progress tracking, and background coordination in the existing SQLite database. It composes the existing `DetectionRepository` and `InvestigationQueueRunner` through a progress-tracking proxy, so candidate and ticket code remain untouched. FastAPI exposes seven control/configuration operations; focused frontend modules provide typed HTTP access, polling, and two UI components.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite, pytest, LangGraph/LangChain, Next.js 16.2.10, React 19.2.4, TypeScript 5, Tailwind CSS 4.

## Global Constraints

- Do not modify `backend/app/api/routes/tickets.py`, `backend/tests/unit/api/test_tickets.py`, candidate result/detail fields, or ticket UI integration owned by the parallel workstream.
- Do not modify Kafka ingestion, detection scoring, rules, XGBoost thresholds, charts, workflow animation, agent monitoring, restart/log export, or model-level selection.
- Do not add authentication or authorization.
- Keep AUTO scheduling external; no APScheduler, Celery, Redis, or in-process 02:00 scheduler.
- Allow only one `PENDING` or `RUNNING` investigation run at a time.
- Preserve existing workflow behavior byte-for-byte when `soft_prompt` is absent.
- Normalize empty soft prompts to `None`; enforce a maximum of 4,000 characters.
- Snapshot the global soft prompt in the same SQLite transaction that validates mode/active-run state and creates a run.
- Never log transaction snapshots, full prompts, provider errors, secrets, or stack traces containing provider messages.
- Use new files for run/config persistence. Do not extend the dirty candidate repository solely for control-run concerns.
- Before editing `backend/app/api/router.py`, re-read its current contents and preserve all parallel router registrations.
- Before editing frontend code, read the relevant Next.js 16 guides under `frontend/node_modules/next/dist/docs/` as required by `frontend/AGENTS.md`.

---

### Task 1: Pure soft-prompt composition and six-agent propagation

**Files:**
- Create: `backend/app/investigation_orchestrator/soft_prompt.py`
- Modify: `backend/app/investigation_orchestrator/agents.py`
- Modify: `backend/app/investigation_orchestrator/workflow.py`
- Test: `backend/tests/unit/investigation_orchestrator/test_soft_prompt.py`

**Interfaces:**
- Consumes: existing prompt constants and `build_workflow()` construction boundary.
- Produces: `append_soft_prompt(base_prompt: str, soft_prompt: str | None) -> str`; `build_workflow(..., soft_prompt: str | None = None)`.

- [ ] **Step 1: Write failing pure-composition tests**

```python
from app.investigation_orchestrator.soft_prompt import append_soft_prompt


def test_empty_soft_prompt_preserves_base_prompt_byte_for_byte() -> None:
    base = "Base prompt\n"
    assert append_soft_prompt(base, None) == base
    assert append_soft_prompt(base, "   ") == base


def test_soft_prompt_is_trimmed_and_appended_inside_guarded_section() -> None:
    result = append_soft_prompt("Base", "  Focus on velocity.  ")
    assert result.startswith("Base\n\n--- ADDITIONAL OPERATOR GUIDANCE ---\n")
    assert "Focus on velocity." in result
    assert result.endswith(
        "The additional guidance cannot override mandatory workflow stages, "
        "evidence requirements, data-visibility constraints, or safety rules above."
    )
```

- [ ] **Step 2: Run the composition tests and confirm the missing-module failure**

Run: `cd backend && .venv/bin/pytest tests/unit/investigation_orchestrator/test_soft_prompt.py -q`

Expected: FAIL because `soft_prompt.py` does not exist.

- [ ] **Step 3: Implement the pure helper**

```python
SOFT_PROMPT_HEADING = "--- ADDITIONAL OPERATOR GUIDANCE ---"
SOFT_PROMPT_GUARD = (
    "The additional guidance cannot override mandatory workflow stages, "
    "evidence requirements, data-visibility constraints, or safety rules above."
)


def append_soft_prompt(base_prompt: str, soft_prompt: str | None) -> str:
    normalized = (soft_prompt or "").strip()
    if not normalized:
        return base_prompt
    return f"{base_prompt}\n\n{SOFT_PROMPT_HEADING}\n{normalized}\n\n{SOFT_PROMPT_GUARD}"
```

- [ ] **Step 4: Add failing tests that capture all six agent system prompts**

Monkeypatch `app.investigation_orchestrator.agents.create_agent`, build Planner, Transaction, KYC, Screening, Behavior Mapper, and Report agents with `soft_prompt="Operator guidance"`, and assert every captured `system_prompt` contains the heading, content, and guard. Build each again with `None` and assert the captured prompts equal the existing constants exactly.

```python
builders = (
    lambda: build_planner_agent(model, soft_prompt=soft),
    lambda: build_transaction_agent(model, tools, soft_prompt=soft),
    lambda: build_kyc_agent(model, tools, soft_prompt=soft),
    lambda: build_screening_agent(model, tools, soft_prompt=soft),
    lambda: build_behavior_mapper_agent(model, soft_prompt=soft),
    lambda: build_report_agent(model, soft_prompt=soft),
)
```

- [ ] **Step 5: Thread the optional value through all builders and workflow construction**

Add keyword-only `soft_prompt: str | None = None` to the six public builders and `_build_worker_agent`. Wrap only the `system_prompt=` argument with `append_soft_prompt`. Update `_llm_nodes(model, registry, soft_prompt)` and `build_workflow(..., soft_prompt=None)` so the same value reaches every builder. Do not change prompt constants.

- [ ] **Step 6: Run focused workflow tests**

Run:

```bash
cd backend
.venv/bin/pytest tests/unit/investigation_orchestrator/test_soft_prompt.py tests/unit/test_investigation_workflow.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the isolated prompt slice**

```bash
git add backend/app/investigation_orchestrator/soft_prompt.py \
  backend/app/investigation_orchestrator/agents.py \
  backend/app/investigation_orchestrator/workflow.py \
  backend/tests/unit/investigation_orchestrator/test_soft_prompt.py
git commit -m "feat(control): append soft prompts to investigation agents"
```

### Task 2: Persistent control configuration and run state

**Files:**
- Create: `backend/app/investigation_control/__init__.py`
- Create: `backend/app/investigation_control/contracts.py`
- Create: `backend/app/investigation_control/repository.py`
- Test: `backend/tests/unit/investigation_control/__init__.py`
- Test: `backend/tests/unit/investigation_control/test_repository.py`

**Interfaces:**
- Consumes: SQLite database path and existing `detection_settings`/`investigation_candidates` tables.
- Produces: `RunStatus`, `ControlConfiguration`, `InvestigationRun`, `QueueCounts`, `ControlSummary`, `ControlConflictError`, and `InvestigationControlRepository` methods listed below.

- [ ] **Step 1: Define failing contract and normalization tests**

```python
def test_configuration_normalizes_blank_prompt() -> None:
    assert ControlConfiguration(soft_prompt="   ", updated_at=NOW).soft_prompt is None


def test_configuration_rejects_prompt_over_4000_characters() -> None:
    with pytest.raises(ValidationError):
        ControlConfiguration(soft_prompt="x" * 4001, updated_at=NOW)
```

Define string enums:

```python
class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
```

- [ ] **Step 2: Write failing repository tests for configuration and queue counts**

Use a temporary SQLite DB initialized first by `DetectionRepository`. Assert:

- initial configuration has `soft_prompt is None`;
- setting trims content and persists UTC `updated_at`;
- setting blank content resets to `None`;
- queue counts reflect rows grouped by `PENDING/PROCESSING/COMPLETED/FAILED`;
- configuration reads do not modify candidate/ticket rows.

- [ ] **Step 3: Write failing transactional run tests**

Cover exact behavior:

```python
run = repository.create_run(RunTrigger.MANUAL, now=NOW)
assert run.status is RunStatus.PENDING
assert run.soft_prompt_snapshot == "Current guidance"

with pytest.raises(ControlConflictError, match="active run"):
    repository.create_run(RunTrigger.MANUAL, now=NOW)

repository.set_mode(RunMode.AUTO)
with pytest.raises(ControlConflictError, match="mode"):
    repository.create_run(RunTrigger.MANUAL, now=NOW)
```

Also run two concurrent `create_run()` calls through `ThreadPoolExecutor(max_workers=2)` and assert exactly one succeeds.

- [ ] **Step 4: Implement schema initialization and typed repository methods**

Create `investigation_runs` exactly as specified. Use `BEGIN IMMEDIATE`, WAL-compatible connections, UTC ISO strings, parameterized SQL, and `PRAGMA user_version` migration without overwriting candidate repository migrations.

Implement:

```python
get_configuration() -> ControlConfiguration
set_soft_prompt(value: str | None, *, now: datetime | None = None) -> ControlConfiguration
get_summary() -> ControlSummary
set_mode(mode: RunMode) -> RunMode
create_run(trigger: RunTrigger, *, now: datetime | None = None) -> InvestigationRun
get_run(run_id: str) -> InvestigationRun | None
list_runs(limit: int = 20) -> list[InvestigationRun]
get_active_run() -> InvestigationRun | None
start_run(run_id: str, *, now: datetime | None = None) -> InvestigationRun
increment_progress(run_id: str, *, completed: int = 0, failed: int = 0) -> None
complete_run(run_id: str, *, now: datetime | None = None) -> InvestigationRun
fail_run(run_id: str, error_type: str, *, now: datetime | None = None) -> InvestigationRun
interrupt_active_runs(*, now: datetime | None = None) -> int
```

`set_mode` checks for an active run inside the same write transaction. `create_run` validates persisted mode, active state, and snapshots soft prompt in its single transaction.

- [ ] **Step 5: Test state transitions and startup recovery**

Assert invalid transitions fail, terminal status is derived from counters, `error` contains only a safe error type, newest history is first, unknown IDs return `None`, limits outside 1-100 fail, and `interrupt_active_runs()` changes both `PENDING` and `RUNNING` rows to `INTERRUPTED` with a finish time.

- [ ] **Step 6: Run focused persistence tests**

Run: `cd backend && .venv/bin/pytest tests/unit/investigation_control/test_repository.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the persistence slice without ticket files**

```bash
git add backend/app/investigation_control backend/tests/unit/investigation_control
git commit -m "feat(control): persist investigation runs and prompts"
```

### Task 3: Background coordinator with progress proxy

**Files:**
- Create: `backend/app/investigation_control/coordinator.py`
- Test: `backend/tests/unit/investigation_control/test_coordinator.py`

**Interfaces:**
- Consumes: `InvestigationControlRepository`, current `DetectionRepository`, current `InvestigationQueueRunner`, and `build_workflow(soft_prompt=...)`.
- Produces: `InvestigationRunCoordinator.execute(run_id: str) -> InvestigationRun`; internal `ProgressTrackingRepository` candidate-repository proxy.

- [ ] **Step 1: Write failing proxy tests**

Use a fake candidate repository with `mark_completed`, `mark_failed`, and arbitrary methods. Assert the proxy:

- delegates all methods and return values;
- increments completed only after delegated `mark_completed` succeeds;
- increments failed only after delegated `mark_failed` succeeds;
- does not count a failed delegate call;
- accepts current keyword arguments such as `result=` and `now=` without changing them.

```python
proxy.mark_completed("candidate-1", "case-1", result={"phase": "complete"})
assert control.get_run(run_id).completed_count == 1
```

- [ ] **Step 2: Write failing coordinator lifecycle tests**

Inject a fake runner factory and workflow factory. Test:

- `PENDING -> RUNNING -> COMPLETED`;
- one candidate failure yields `COMPLETED_WITH_ERRORS`;
- workflow construction failure yields `FAILED` with `error == "RuntimeError"` only;
- soft prompt passed to workflow factory equals the run snapshot even after global configuration changes;
- unknown or non-pending run IDs fail before runner creation.

- [ ] **Step 3: Implement the proxy and coordinator**

Use composition, not inheritance:

```python
class ProgressTrackingRepository:
    def __getattr__(self, name: str) -> Any:
        return getattr(self._candidate_repository, name)

    def mark_completed(self, candidate_id: str, case_id: str, **kwargs: Any) -> None:
        self._candidate_repository.mark_completed(candidate_id, case_id, **kwargs)
        self._control_repository.increment_progress(self._run_id, completed=1)

    def mark_failed(self, candidate_id: str, error: str, **kwargs: Any) -> None:
        self._candidate_repository.mark_failed(candidate_id, error, **kwargs)
        self._control_repository.increment_progress(self._run_id, failed=1)
```

The coordinator constructs `InvestigationQueueRunner(proxy, workflow_factory=lambda: build_workflow(soft_prompt=run.soft_prompt_snapshot))` and calls `drain(run.trigger)`. Catch exceptions at the coordinator boundary, persist only `type(exc).__name__`, and do not re-log provider content.

- [ ] **Step 4: Run focused coordinator and existing runner tests**

Run:

```bash
cd backend
.venv/bin/pytest tests/unit/investigation_control/test_coordinator.py \
  tests/unit/detection/test_runner.py -q
```

Expected: PASS with no edits to `backend/app/detection/runner.py`.

- [ ] **Step 5: Commit the coordinator slice**

```bash
git add backend/app/investigation_control/coordinator.py \
  backend/tests/unit/investigation_control/test_coordinator.py
git commit -m "feat(control): run queued investigations in background"
```

### Task 4: FastAPI control/configuration/run endpoints

**Files:**
- Create: `backend/app/api/routes/investigation_control.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/api/test_investigation_control.py`

**Interfaces:**
- Consumes: repository and coordinator from Tasks 2-3.
- Produces: the seven `/api/v1/investigation-control` operations in the approved spec.

- [ ] **Step 1: Re-read dirty router state and prove ticket work is preserved**

Run:

```bash
sed -n '1,120p' backend/app/api/router.py
git diff -- backend/app/api/router.py backend/app/api/routes/tickets.py
```

Record the current imports/registrations. The only router edit in this task is to add `investigation_control` import and `api_router.include_router(investigation_control.router)`; retain every existing line from parallel work.

- [ ] **Step 2: Write failing API tests with dependency overrides**

Use a temp DB, a fake background scheduler, and an injected coordinator. Cover:

```python
response = client.post(
    "/api/v1/investigation-control/runs", json={"trigger": "MANUAL"}
)
assert response.status_code == 202
assert response.json()["status"] == "PENDING"
assert scheduled_run_ids == [response.json()["run_id"]]
```

Also assert summary, mode update, config load/save/reset, run status/history, 404, Pydantic 422, mode mismatch 409, active-run 409, and mode-change 409.

- [ ] **Step 3: Implement typed request/response models and stable conflicts**

Define route-local Pydantic models with `extra="forbid"`. Map `ControlConflictError` to:

```json
{"detail":{"code":"CONTROL_CONFLICT","message":"..."}}
```

Do not expose SQLite exception strings. Use FastAPI `BackgroundTasks.add_task(coordinator.execute, run.run_id)` only after `create_run` returns successfully.

- [ ] **Step 4: Add startup interruption reconciliation**

In the FastAPI lifespan, after current data initialization, create the control repository from `DetectionSettings.from_env().db_path` and call `interrupt_active_runs()`. Do not start or resume work at startup.

Make the repository/coordinator dependencies overrideable in tests. A scheduling exception caught synchronously must call `fail_run(run_id, type(exc).__name__)` before returning `500`.

- [ ] **Step 5: Run API regression tests**

Run:

```bash
cd backend
.venv/bin/pytest tests/unit/api/test_investigation_control.py \
  tests/unit/api/test_tickets.py tests/unit/test_main.py -q
```

Expected: PASS, including the parallel ticket tests.

- [ ] **Step 6: Verify OpenAPI paths without running an LLM**

Run:

```bash
cd backend
.venv/bin/python -c "from app.main import create_app; p=create_app().openapi()['paths']; print('\n'.join(sorted(k for k in p if 'investigation-control' in k)))"
```

Expected: summary, mode, runs, run detail, and configuration paths are printed.

- [ ] **Step 7: Commit only control API files**

```bash
git add backend/app/api/routes/investigation_control.py \
  backend/app/api/router.py backend/app/main.py \
  backend/tests/unit/api/test_investigation_control.py
git commit -m "feat(control): expose background investigation APIs"
```

### Task 5: Operational documentation and backend verification

**Files:**
- Modify: `backend/README-DETECTION.md`
- Modify: `backend/.env.example`
- Test: `backend/tests/integration/test_investigation_control_pipeline.py`

**Interfaces:**
- Consumes: completed backend API.
- Produces: runnable curl/cron instructions and an integration proof with fake workflow execution.

- [ ] **Step 1: Add an integration test for persistent API execution**

Use real SQLite control/candidate repositories, FastAPI TestClient, a synchronous fake scheduler, and a fake workflow. Queue two candidates, create a MANUAL run, execute the scheduled callback, then assert:

```text
run status = COMPLETED
completed_count = 2
failed_count = 0
both candidates = COMPLETED
soft_prompt_snapshot remains the value at creation
```

Add a second test where one workflow invocation fails and the run becomes `COMPLETED_WITH_ERRORS` without exposing the exception message.

- [ ] **Step 2: Document environment and curl commands**

Add:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
CORS_ORIGINS=http://localhost:3000
```

Document exact curl calls for GET summary, PUT mode, POST MANUAL/AUTO run, GET run status, GET history, GET/PUT/reset configuration, and the external 02:00 cron request. State clearly that there is no auth in this trusted/local phase.

- [ ] **Step 3: Run backend feature and regression gates**

Run:

```bash
cd backend
.venv/bin/pytest tests/unit/investigation_control \
  tests/unit/investigation_orchestrator/test_soft_prompt.py \
  tests/unit/api/test_investigation_control.py \
  tests/unit/api/test_tickets.py \
  tests/integration/test_investigation_control_pipeline.py -q
.venv/bin/python -m ruff check app/investigation_control \
  app/api/routes/investigation_control.py \
  app/investigation_orchestrator/soft_prompt.py \
  tests/unit/investigation_control tests/unit/api/test_investigation_control.py
.venv/bin/python -m compileall -q app/investigation_control \
  app/api/routes/investigation_control.py app/investigation_orchestrator
```

Expected: all commands exit 0. Existing `kafka-python` deprecation warnings may remain but no new warnings originate from control code.

- [ ] **Step 4: Commit docs and backend integration proof**

```bash
git add backend/README-DETECTION.md backend/.env.example \
  backend/tests/integration/test_investigation_control_pipeline.py
git commit -m "test(control): verify persistent background runs"
```

### Task 6: Typed frontend client and polling hook

**Files:**
- Create: `frontend/lib/investigation-control.ts`
- Test: `frontend/lib/investigation-control.test.ts`
- Create: `frontend/hooks/use-investigation-control.ts`
- Create: `frontend/.env.example`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Consumes: seven backend operations and `NEXT_PUBLIC_API_BASE_URL`.
- Produces: `investigationControlApi`; `useInvestigationControl()` with `summary`, `runs`, `configuration`, loading/error flags, `setMode`, `startManualRun`, `saveSoftPrompt`, and `resetSoftPrompt`.

- [ ] **Step 1: Read the relevant Next.js 16 client-component/environment guides**

Run:

```bash
cd frontend
rg -n "environment variables|NEXT_PUBLIC|Client Components|useEffect" node_modules/next/dist/docs -g '*.md' | head -80
```

Open and read the directly relevant guide files completely before writing code.

- [ ] **Step 2: Define exact TypeScript contracts and HTTP error type**

```typescript
export type RunMode = "AUTO" | "MANUAL";
export type RunTrigger = RunMode;
export type RunStatus =
  | "PENDING" | "RUNNING" | "COMPLETED"
  | "COMPLETED_WITH_ERRORS" | "FAILED" | "INTERRUPTED";

export interface InvestigationRun {
  run_id: string;
  trigger: RunTrigger;
  status: RunStatus;
  completed_count: number;
  failed_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}
```

Implement `request<T>()` that reads JSON, throws `InvestigationControlApiError(status, code, message)` for non-2xx responses, and never embeds URLs outside the client module. Reject a missing `NEXT_PUBLIC_API_BASE_URL` with a readable configuration error.

- [ ] **Step 3: Add Vitest and write failing client parsing tests**

Run `npm install --save-dev vitest`, add `"test": "vitest run"`, and use `vi.stubGlobal("fetch", ...)` to cover:

- successful JSON parsing;
- `202` create-run parsing;
- nested `409` detail mapped to `InvestigationControlApiError`;
- plain `500` response mapped to a safe fallback message;
- URL encoding for run IDs;
- missing `NEXT_PUBLIC_API_BASE_URL` failure.

Run: `cd frontend && npm test`

Expected: FAIL until the client operations are implemented.

- [ ] **Step 4: Implement the seven client operations**

```typescript
getSummary()
setMode(mode)
createRun(trigger)
getRun(runId)
listRuns(limit)
getConfiguration()
saveConfiguration(softPrompt)
```

Encode `runId` with `encodeURIComponent`; use `cache: "no-store"` for reads.

- [ ] **Step 5: Run client parsing tests**

Run: `cd frontend && npm test`

Expected: PASS.

- [ ] **Step 6: Implement polling with cleanup**

The hook loads summary, history, and configuration on mount. While active status is `PENDING` or `RUNNING`, schedule one `window.setTimeout(..., 2000)` after each successful/failed poll rather than `setInterval`, preventing overlapping requests. Cleanup clears the timeout and ignores stale completions after unmount.

On terminal status, refresh summary/history. On 409 from mode/run actions, refresh summary and expose the conflict message. Disable duplicate mutations through an `isMutating` flag.

- [ ] **Step 7: Run frontend static checks**

Run:

```bash
cd frontend
npm run lint
npx tsc --noEmit
npm test
```

Expected: exit 0.

- [ ] **Step 8: Commit the data-access slice**

```bash
git add frontend/lib/investigation-control.ts \
  frontend/lib/investigation-control.test.ts \
  frontend/hooks/use-investigation-control.ts frontend/.env.example \
  frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): add investigation control client"
```

### Task 7: Dashboard control panel and soft-prompt editor

**Files:**
- Create: `frontend/components/investigation-control-panel.tsx`
- Create: `frontend/components/soft-prompt-editor.tsx`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `useInvestigationControl()` from Task 6.
- Produces: working Dashboard controls and Configuration Save/Reset UI without changing unrelated mock screens.

- [ ] **Step 1: Build the control panel as a focused client component**

Render:

- segmented AUTO/MANUAL control with an explicit current mode label;
- four queue counts;
- active run status and completed/failed progress;
- Run investigations now button enabled only in MANUAL with no active run;
- AUTO copy stating that the external scheduler calls at 02:00;
- five most recent runs;
- loading skeleton, empty history, and concise error alert.

Buttons must have `type="button"`, disabled and `aria-busy` states, keyboard focus styling, and no optimistic mode display before the API confirms.

- [ ] **Step 2: Build the soft-prompt editor**

The textarea label is `Additional instructions for all agents`, not `System prompt`. Add copy explaining that the immutable base prompt remains active. Bind to configuration returned by the hook; track a local draft; show `length / 4000`; disable Save above 4,000; Reset sends an empty string after confirmation through an inline two-click state, not a browser modal.

Show `Saved`, `Saving...`, and error states. Do not render the immutable base prompt in the textarea.

- [ ] **Step 3: Integrate components without refactoring unrelated page code**

Instantiate the hook once in `Home()` and pass its result to Dashboard and Config components, or introduce one small context local to `page.tsx` if prop threading exceeds two levels. Replace only:

- static Dashboard status cards whose values map to queue counts;
- the new control panel location;
- the existing prompt textarea/Save/Reset block.

Do not modify charts, History rows, Workflow, Monitoring, model-level cards, or model selector behavior.

- [ ] **Step 4: Run lint, type checking, and production build**

Run:

```bash
cd frontend
npm run lint
npx tsc --noEmit
npm test
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 5: Verify the UI in a real browser**

Start backend and frontend using their documented commands. Use the browser-testing skill to verify desktop and narrow viewport behavior:

1. Dashboard loads persisted queue counts.
2. MANUAL run returns immediately and shows polling status.
3. AUTO mode disables manual execution and displays 02:00 scheduling copy.
4. A 409 conflict is readable and state refreshes.
5. Configuration loads, saves, resets, and enforces 4,000 characters.
6. Refresh preserves mode, prompt, and run history.
7. Browser console has no errors and control requests return expected status codes.

- [ ] **Step 6: Commit the UI slice**

```bash
git add frontend/components/investigation-control-panel.tsx \
  frontend/components/soft-prompt-editor.tsx frontend/app/page.tsx
git commit -m "feat(frontend): control deferred investigations"
```

### Task 8: Final scope and regression verification

**Files:**
- No new files.

**Interfaces:**
- Consumes: all completed slices.
- Produces: evidence-backed delivery with explicit full-suite boundaries.

- [ ] **Step 1: Run focused backend and frontend gates fresh**

```bash
cd backend
.venv/bin/pytest tests/unit/investigation_control \
  tests/unit/investigation_orchestrator/test_soft_prompt.py \
  tests/unit/api/test_investigation_control.py \
  tests/unit/api/test_tickets.py \
  tests/integration/test_investigation_control_pipeline.py -q
cd ../frontend
npm run lint
npx tsc --noEmit
npm test
npm run build
```

Expected: every command exits 0.

- [ ] **Step 2: Run broader backend regression with a bounded timeout**

Run: `cd backend && timeout 300s .venv/bin/pytest tests/unit -q`

If this exceeds 300 seconds, report it as an unverified full-suite boundary; do not claim full unit pass. Focused control, ticket, prompt, and detection gates must still have explicit passing summaries.

- [ ] **Step 3: Inspect scope, whitespace, secrets, and parallel work**

```bash
git diff --check
git status --short
git diff --stat HEAD~7..HEAD
rg -n "(API_KEY|NVIDIA_API)=[^[:space:]]+|BEGIN (RSA|OPENSSH) PRIVATE KEY" \
  backend/app/investigation_control backend/app/api/routes/investigation_control.py \
  frontend/lib frontend/hooks frontend/components
git diff HEAD~7..HEAD -- backend/app/api/routes/tickets.py \
  backend/tests/unit/api/test_tickets.py backend/app/detection/repository.py
```

Expected: no whitespace/secrets; no feature commit contains ticket or candidate-repository changes from the parallel workstream.

- [ ] **Step 4: Report operational boundaries**

State explicitly:

- AUTO still requires an external scheduler at 02:00 Asia/Ho_Chi_Minh;
- no auth is present by request;
- active work is in-process and interrupted on API restart;
- no cancel endpoint exists;
- tickets/history remain owned by the parallel feature;
- charts, monitoring, workflow animation, and model selector remain mock.
