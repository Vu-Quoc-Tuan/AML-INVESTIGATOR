# Live Agent Workflow SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist real multi-agent/tool execution events, stream them to the browser with SSE, and replace Monitoring/system-node UI with one six-agent live workflow screen.

**Architecture:** SQLite owns an append-only ticket event log. Agent nodes and LangChain tool callbacks append sanitized events; the ticket API replays and tails them through SSE. The frontend uses EventSource and renders event history per agent.

**Tech Stack:** FastAPI, SQLite, LangGraph/LangChain callbacks, Next.js/React, TypeScript, Vitest, pytest.

## Global Constraints

- Never expose prompts, model message history, secrets or chain-of-thought.
- A tool error stops the investigation and leaves the candidate retryable as `FAILED`.
- Retry restarts the entire investigation from Planner.
- Display only six LLM agents; no Monitoring page and no orchestration nodes.
- Keep technical status separate from analyst disposition.
- Do not modify Kafka, detection thresholds or auth.
- Do not commit until the complete scoped verification is green.

---

### Task 1: Durable execution event store

**Files:**
- Create: `backend/app/investigation_events/contracts.py`
- Create: `backend/app/investigation_events/repository.py`
- Create: `backend/app/investigation_events/__init__.py`
- Test: `backend/tests/unit/investigation_events/test_repository.py`

**Interfaces:**
- Produces `InvestigationEventType`, `InvestigationEvent`, and `InvestigationEventRepository.append/list_after/latest_for_ticket`.
- Uses the same `DETECTION_DB_PATH` SQLite database and UTC ISO timestamps.

- [ ] Write failing tests for monotonically increasing IDs, ticket isolation, `after_id`, JSON-safe payloads and maximum payload size.
- [ ] Run `.venv/bin/python -m pytest tests/unit/investigation_events/test_repository.py -q` and confirm missing-module failure.
- [ ] Implement an append-only `investigation_events` table and typed serialization.
- [ ] Run the focused tests and confirm pass.

### Task 2: Agent and tool instrumentation

**Files:**
- Create: `backend/app/investigation_events/recorder.py`
- Modify: `backend/app/investigation_orchestrator/agents.py`
- Modify: `backend/app/investigation_orchestrator/nodes.py`
- Modify: `backend/app/investigation_orchestrator/report_agent.py`
- Modify: `backend/app/investigation_orchestrator/workflow.py`
- Test: `backend/tests/unit/investigation_events/test_recorder.py`
- Test: `backend/tests/unit/test_investigation_workflow.py`

**Interfaces:**
- Consumes the repository from Task 1.
- Produces `ExecutionEventRecorder` and `ToolEventCallback` passed into workflow construction.

- [ ] Write failing tests proving tool start/success events contain tool name but no prompt/message history.
- [ ] Write a failing workflow test where a tool error emits failure and prevents later agent execution.
- [ ] Pass RunnableConfig callbacks through nested agent invokes and wrap each six LLM node with explicit start/completed/failed events.
- [ ] Treat ToolMessage error and ToolResult `ERROR` as a raised execution failure after recording the safe error type.
- [ ] Run both focused test modules and confirm pass.

### Task 3: Runner lifecycle and SSE ticket API

**Files:**
- Modify: `backend/app/detection/runner.py`
- Modify: `backend/app/api/routes/tickets.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/unit/detection/test_runner.py`
- Create: `backend/tests/unit/api/test_ticket_events.py`

**Interfaces:**
- `GET /api/v1/tickets/{ticket_id}/events` accepts `Last-Event-ID` and returns `text/event-stream`.
- Terminal events are `INVESTIGATION_COMPLETED` and `INVESTIGATION_FAILED`.

- [ ] Write a failing runner test for lifecycle events and failed candidate retryability.
- [ ] Write a failing SSE serialization/replay test that does not require the hanging TestClient transport.
- [ ] Create one recorder per claimed candidate and inject it into the workflow factory.
- [ ] Implement SSE replay, heartbeat, disconnect handling and terminal close.
- [ ] Append `REVIEW_DECIDED` in the review endpoint.
- [ ] Replace the hard-coded `attempts < 3` response logic with repository configuration.
- [ ] Run focused runner/API tests and an uvicorn/curl smoke test.

### Task 4: Frontend SSE client

**Files:**
- Create: `frontend/lib/investigation-events.ts`
- Create: `frontend/hooks/use-investigation-events.ts`
- Create: `frontend/lib/investigation-events.test.ts`

**Interfaces:**
- Produces typed `InvestigationEvent`, `AgentRuntimeState`, `eventStreamUrl(ticketId)` and the reconnecting hook.
- Consumes `NEXT_PUBLIC_API_BASE_URL` and native `EventSource`.

- [ ] Write failing parser/reducer tests for agent progress, tool failure and terminal outcomes.
- [ ] Implement strict event parsing, per-agent grouping and terminal connection close.
- [ ] Run Vitest and confirm the new tests pass.

### Task 5: Six-agent live Workflow UI

**Files:**
- Modify: `frontend/lib/workflow-catalog.ts`
- Modify: `frontend/lib/workflow-catalog.test.ts`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes Task 4 hook and the ticket ID passed from History after `runTicket`.
- Produces one Workflow page with six agent nodes and a right-side activity/output panel.

- [ ] Change catalog tests to require exactly six nodes and only agent-to-agent presentation edges.
- [ ] Remove `monitoring` from `PageKey`, navigation, content map and component tree.
- [ ] Pass the started ticket ID from History to Workflow.
- [ ] Render agent state from SSE: idle/running/completed/failed; auto-select the newest running agent.
- [ ] Render sanitized tool call/result and final output; never render chain-of-thought.
- [ ] Make technical `FAILED` display as Error, never Reject.
- [ ] Run Vitest, TypeScript and production build.

### Task 6: Scoped regression repair and verification

**Files:**
- Modify: `backend/tests/unit/detection/test_repository.py`
- Modify: `backend/app/investigation_control/coordinator.py`
- Modify: `backend/app/investigation_orchestrator/workflow.py`
- Review only: all remaining dirty files.

**Interfaces:**
- Preserves global soft prompt as fallback when a per-agent prompt is unset.
- Aligns the schema version assertion with the actual migration.

- [ ] Update the stale schema-version assertion after verifying the migration is version 3.
- [ ] Add a test proving per-agent prompt overrides global prompt and null per-agent prompt falls back to the run snapshot.
- [ ] Run backend focused non-live tests, compile, ruff; run frontend test, TypeScript, ESLint and build.
- [ ] Run `git diff --check` and inspect the final scoped diff for unrelated churn.
- [ ] Do not stage or commit deleted historical plan files unless they are explicitly restored or separately approved.
- [ ] Only after all gates pass, present the exact commit scope to the user before committing the combined dirty worktree.

