---
goal: Register domain-owned Transaction tools through the production orchestration boundary
version: 1.0
date_created: 2026-07-18
last_updated: 2026-07-18
owner: Investigation Orchestrator
status: 'Completed'
tags: [feature, langgraph, transaction, tools, registry]
---

# Introduction

![Status: Completed](https://img.shields.io/badge/status-Completed-brightgreen)

Restore the Transaction output contracts lost during merge, adapt the approved Transaction capabilities to the orchestrator `ToolResult` boundary, and register them explicitly in the production composition root without changing Transaction business logic or enabling an incomplete default workflow.

## 1. Requirements & Constraints

- **REQ-001**: `build_transaction_tools()` must return exactly the seven Transaction tools declared in `docs/architecture.md`.
- **REQ-002**: Every tool artifact must validate as `app.investigation_orchestrator.tool_registry.ToolResult`.
- **REQ-003**: Transaction evidence must preserve `transaction_id`, `evidence_source`, and `data_visibility` as provenance fields.
- **REQ-004**: The production composition root must register Transaction tools only under owner `transaction`.
- **SEC-001**: LLMs must not receive Transaction capabilities outside the approved allowlist.
- **SEC-002**: Adapters must not mutate `InvestigationState`, checkpoints, or the shared case file.
- **CON-001**: Do not change Transaction detection, tracing, graph, or risk algorithms owned by the Transaction domain team.
- **CON-002**: Do not switch default `build_workflow()` to the production registry until the KYC factory exists.
- **CON-003**: Do not commit, push, or stage changes.
- **GUD-001**: Reuse `TransactionDataService`, `StructuredTool`, `ToolRegistry`, and the Screening adapter boundary pattern.
- **PAT-001**: Domain adapters return LangChain `content_and_artifact`, with a JSON string as content and a JSON-safe `ToolResult`-compatible artifact.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Restore Transaction domain contracts and establish failing adapter tests.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Extend `backend/app/schemas/tools.py` with the Transaction output models from parent `dev` while preserving all existing KYC input models. | ✅ | 2026-07-18 |
| TASK-002 | Add `backend/tests/unit/transaction_investigation/test_tool_adapter.py` with tests for the exact allowlist, strict inputs, `ToolResult` validation, provenance mapping, and owner isolation. This task depends on TASK-001 only for test collection. | ✅ | 2026-07-18 |

### Implementation Phase 2

- GOAL-002: Implement the domain-owned Transaction adapter.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-003 | Create `backend/app/transaction_investigation/tool_adapter.py` with strict Pydantic input schemas, a local JSON boundary, deterministic evidence mapping helpers, and `build_transaction_tools(service=None)`. This task depends on TASK-002. | ✅ | 2026-07-18 |
| TASK-004 | Export `build_transaction_tools` from `backend/app/transaction_investigation/__init__.py` without importing orchestrator modules from the domain package. This task depends on TASK-003. | ✅ | 2026-07-18 |

### Implementation Phase 3

- GOAL-003: Add explicit production registration and fail-fast validation.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-005 | Add `ToolConfigurationError` and `ToolRegistry.require_tools()` to `backend/app/investigation_orchestrator/tool_registry.py`; report missing owners without secrets or domain payloads. | ✅ | 2026-07-18 |
| TASK-006 | Create `backend/app/investigation_orchestrator/production_tools.py` to register `build_transaction_tools()` and `build_screening_tools()` explicitly, then fail fast for missing mandatory owners. Do not alter `build_workflow()` in this phase. This task depends on TASK-004 and TASK-005. | ✅ | 2026-07-18 |
| TASK-007 | Add `backend/tests/unit/test_production_tools.py` to verify owner isolation, exact Transaction registration, duplicate-name handling, and the expected missing-KYC fail-fast condition. This task depends on TASK-006. | ✅ | 2026-07-18 |

### Implementation Phase 4

- GOAL-004: Verify the Transaction domain and orchestration boundary.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-008 | Run focused Transaction domain, adapter, ToolRegistry, and production composition tests from `backend/.venv`; record exact pass/fail counts. | ✅ | 2026-07-18 |
| TASK-009 | Run the non-live regression suite while excluding external LLM and RAG scripts; distinguish pre-existing KYC/dependency collection failures from Transaction regressions. | ✅ | 2026-07-18 |
| TASK-010 | Update this plan to `Completed` only if all Transaction-specific checks pass; otherwise leave `In progress` and record the blocking failure in the final handoff. | ✅ | 2026-07-18 |

## 3. Alternatives

- **ALT-001**: Register `TRANSACTION_AGENT_TOOLS` directly. Rejected because those wrappers return raw domain dictionaries rather than the evidence-gated `ToolResult` contract.
- **ALT-002**: Auto-discover decorated tools by scanning packages. Rejected because it weakens owner isolation and makes startup behavior dependent on imports.
- **ALT-003**: Enable the production registry as the default workflow immediately. Rejected because KYC has no compatible factory yet and the approved fail-fast policy would make every default workflow build fail.

## 4. Dependencies

- **DEP-001**: Existing Transaction implementations in `backend/app/transaction_investigation/` and `TransactionDataService`.
- **DEP-002**: Existing LangChain `StructuredTool` and orchestrator `ToolResult`/`ToolRegistry` contracts.
- **DEP-003**: Initialized `DataRepository` for tests that invoke real Transaction domain functions.

## 5. Files

- **FILE-001**: `backend/app/schemas/tools.py` — merged Transaction and KYC contracts.
- **FILE-002**: `backend/app/transaction_investigation/tool_adapter.py` — domain-owned LangChain adapter.
- **FILE-003**: `backend/app/transaction_investigation/__init__.py` — factory export.
- **FILE-004**: `backend/app/investigation_orchestrator/tool_registry.py` — mandatory-owner validation.
- **FILE-005**: `backend/app/investigation_orchestrator/production_tools.py` — explicit composition root.
- **FILE-006**: `backend/tests/unit/transaction_investigation/test_tool_adapter.py` — adapter contract tests.
- **FILE-007**: `backend/tests/unit/test_production_tools.py` — production registration tests.
- **FILE-008**: `docs/superpowers/specs/2026-07-18-production-tool-registration-design.md` — current post-merge design state.

## 6. Testing

- **TEST-001**: Existing Transaction query and scenario tests collect and execute after schema restoration.
- **TEST-002**: Adapter factory returns exactly seven uniquely named `BaseTool` instances.
- **TEST-003**: Successful tool artifacts validate as `ToolResult` and contain tool-derived evidence provenance.
- **TEST-004**: A no-data call returns a safe boundary without invented evidence.
- **TEST-005**: Production composition registers Transaction tools only under owner `transaction` and reports missing `kyc` deterministically.
- **TEST-006**: Existing Screening and orchestrator ToolRegistry tests remain passing.

## 7. Risks & Assumptions

- **RISK-001**: Pattern findings may reference transactions with mixed visibility; the existing orchestrator must continue rejecting findings whose declared visibility does not match all evidence.
- **RISK-002**: Full-suite collection currently has unrelated KYC, FastAPI, and RAG dependency failures; these must not be misreported as Transaction regressions.
- **ASSUMPTION-001**: Transaction IDs are stable source record identifiers and `evidence_source`/`data_visibility` have already passed `DataRepository` validation.
- **ASSUMPTION-002**: KYC registration will be implemented in the next domain-specific phase before default workflow wiring.

## 8. Related Specifications / Further Reading

[Production Tool Registration Design](../docs/superpowers/specs/2026-07-18-production-tool-registration-design.md)

[Project Architecture](../docs/architecture.md)

[Business Rules](../docs/BUSINESS_RULES.md)
