---
goal: Implement the runnable Hybrid Supervisor LangGraph workflow skeleton
version: 1.0
date_created: 2026-07-18
last_updated: 2026-07-18
owner: AML Investigator Team
status: 'Completed'
tags: [feature, langgraph, orchestration, aml]
---

# Introduction

![Status: Completed](https://img.shields.io/badge/status-Completed-brightgreen)

Implement a runnable, testable Hybrid Supervisor workflow with `Command`
handoffs, a fixed Transaction/KYC fork-join, deterministic evidence validation,
stub agent outputs, and resumable Human Review.

## 1. Requirements & Constraints

- **REQ-001**: Implement all workflow production code under `backend/app/investigation_orchestrator`.
- **REQ-002**: Use LangGraph `StateGraph` and `Command` for dynamic Supervisor handoffs.
- **REQ-003**: Execute Transaction and KYC stub nodes in parallel and wait for both before merge.
- **REQ-004**: Keep worker output in staging state; only Orchestrator-owned nodes may update the canonical Shared Case File.
- **REQ-005**: Run deterministic evidence validation before report generation.
- **REQ-006**: Pause at Human Review and resume with LangGraph `Command(resume=...)` and a stable `thread_id`.
- **REQ-007**: Return `INCONCLUSIVE` when screening is unavailable.
- **CON-001**: Do not implement real LLM calls, prompts, tools, RAG, transaction algorithms, or KYC algorithms.
- **CON-002**: Keep state serializable and do not store Pandas, NetworkX, model, or database objects.
- **SEC-001**: Do not implement account blocking, SAR/STR submission, or autonomous compliance decisions.
- **GUD-001**: Use an in-memory checkpointer only as the MVP/test default and allow callers to inject another checkpointer.
- **PAT-001**: Use deterministic Python routing for mandatory gates and reserve the planner node as the future LLM extension point.

## 2. Implementation Steps

### Implementation Phase 1

- **GOAL-001**: Define the dependency and serializable state contracts required by parallel LangGraph execution.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Add `langgraph>=1.0,<2.0` to `backend/requirements.txt` without adding an LLM provider dependency. | ✅ | 2026-07-18 |
| TASK-002 | Implement state literals, typed dictionaries, dictionary merge reducer, and append-only log reducer in `backend/app/investigation_orchestrator/state.py`. | ✅ | 2026-07-18 |

### Implementation Phase 2

- **GOAL-002**: Implement all workflow nodes and graph topology.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-003 | Implement deterministic Supervisor, stub planner, dispatch, Transaction stub, KYC stub, Screening stub, and Orchestrator merge node in `backend/app/investigation_orchestrator/nodes.py`. | ✅ | 2026-07-18 |
| TASK-004 | Implement evidence validation and the Evidence Validator node in `backend/app/investigation_orchestrator/evidence_validator.py`. | ✅ | 2026-07-18 |
| TASK-005 | Implement the deterministic stub dossier node in `backend/app/investigation_orchestrator/report_agent.py`. | ✅ | 2026-07-18 |
| TASK-006 | Implement review payload validation and the interrupt/resume node in `backend/app/investigation_orchestrator/human_review.py`. | ✅ | 2026-07-18 |
| TASK-007 | Build and compile the graph with injectable checkpointer support in `backend/app/investigation_orchestrator/workflow.py`. | ✅ | 2026-07-18 |
| TASK-008 | Export the state and graph builder public API from `backend/app/investigation_orchestrator/__init__.py`. | ✅ | 2026-07-18 |

### Implementation Phase 3

- **GOAL-003**: Verify routing, business rules, parallel merge, and resumable review behavior.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-009 | Add focused unit tests in `backend/tests/unit/test_investigation_workflow.py`. | ✅ | 2026-07-18 |
| TASK-010 | Install declared dependencies if missing, run the focused pytest module, run Python compilation, and run `git diff --check`. | ✅ | 2026-07-18 |
| TASK-011 | Update this plan status and completion cells only after all verification commands pass. | ✅ | 2026-07-18 |

## 3. Alternatives

- **ALT-001**: Use a fully static parallel graph. Rejected because reviewer-driven rework and future investigation planning require centralized dynamic routing.
- **ALT-002**: Model every agent as a nested subgraph using `Command.PARENT`. Rejected because stub agents do not yet need private state or internal loops.
- **ALT-003**: Use a fully LLM-driven Supervisor. Rejected because mandatory evidence and Human Review gates must be deterministic.

## 4. Dependencies

- **DEP-001**: Python 3.11 or newer.
- **DEP-002**: `langgraph>=1.0,<2.0` for `StateGraph`, `Command`, `interrupt`, and checkpointing.
- **DEP-003**: pytest for unit test execution.

## 5. Files

- **FILE-001**: `backend/requirements.txt` — runtime dependency declaration.
- **FILE-002**: `backend/app/investigation_orchestrator/state.py` — graph state and reducers.
- **FILE-003**: `backend/app/investigation_orchestrator/nodes.py` — Supervisor and stub worker nodes.
- **FILE-004**: `backend/app/investigation_orchestrator/evidence_validator.py` — deterministic business-rule validation.
- **FILE-005**: `backend/app/investigation_orchestrator/report_agent.py` — stub dossier generation.
- **FILE-006**: `backend/app/investigation_orchestrator/human_review.py` — interrupt and resume handling.
- **FILE-007**: `backend/app/investigation_orchestrator/workflow.py` — graph construction.
- **FILE-008**: `backend/app/investigation_orchestrator/__init__.py` — public exports.
- **FILE-009**: `backend/tests/unit/test_investigation_workflow.py` — workflow tests.
- **FILE-010**: `backend/requirements-dev.txt` — pytest dependency declaration.

## 6. Testing

- **TEST-001**: Invoke the graph and assert it interrupts at Human Review after both parallel outputs are merged.
- **TEST-002**: Resume an interrupted graph with `APPROVED` and assert terminal case status `APPROVED`.
- **TEST-003**: Run with screening unavailable and assert status `INCONCLUSIVE`.
- **TEST-004**: Validate malformed findings and assert they are excluded while issues are retained.
- **TEST-005**: Assert handoff history contains the mandatory stages in order.
- **TEST-006**: Compile all modified Python modules with `compileall`.

## 7. Risks & Assumptions

- **RISK-001**: LangGraph interrupt/resume behavior requires a stable `thread_id`; tests and API examples must always supply one.
- **RISK-002**: Parallel branches updating the same state key can raise concurrent update errors unless the dictionary merge reducer is applied correctly.
- **RISK-003**: In-memory checkpoints are process-local and must not be used as production persistence.
- **ASSUMPTION-001**: The current repository files are scaffolds, so no existing workflow behavior must be preserved.
- **ASSUMPTION-002**: Stub outputs are representative contracts, not final AML analytical logic.

## 8. Related Specifications / Further Reading

- [Hybrid Supervisor workflow design](../docs/superpowers/specs/2026-07-18-hybrid-supervisor-workflow-design.md)
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
