---
goal: Integrate real LLM agents into the Hybrid Supervisor AML workflow
version: 1.0
date_created: 2026-07-18
last_updated: 2026-07-18
owner: AML Investigator Orchestration Team
status: 'Planned'
tags: [feature, langgraph, langchain, llm, agents, aml]
---

# Introduction

![Status: Planned](https://img.shields.io/badge/status-Planned-blue)

Replace the Planner, Transaction, KYC, Screening/Compliance, and Report stubs
with real LLM agents using `glm-5.2-free` through an OpenAI-compatible endpoint.
Preserve deterministic Supervisor routing, merge, evidence validation, and
Human Review. Domain tool logic remains owned and implemented by other team
members.

## 1. Requirements & Constraints

- **REQ-001**: Use `glm-5.2-free` as the default model name and obtain `API_KEY`, `BASE_URL`, and optional `MODEL_NAME` from `backend/.env`.
- **REQ-002**: Build Planner, Transaction, KYC, Screening/Compliance, and Report as LLM-backed agents.
- **REQ-003**: Build specialist agent loops with `langchain.agents.create_agent` and explicitly use `ToolStrategy` for structured responses.
- **REQ-004**: Keep the outer Hybrid Supervisor, merge, Evidence Validator, and Human Review deterministic.
- **REQ-005**: Preserve the existing Transaction/KYC parallel fork-join topology.
- **REQ-006**: Register tools supplied by other team members through an agent-specific Tool Registry allowlist.
- **REQ-007**: Construct final worker evidence only from evidence returned by executed tools; never accept evidence created only in model text.
- **REQ-008**: Return `INCONCLUSIVE` with no findings when a worker has no registered tools or its source is unavailable.
- **REQ-009**: Keep agent message histories, model clients, tool objects, and provider responses out of `InvestigationState`.
- **REQ-010**: Route exhausted provider errors and invalid structured responses to a reviewable error dossier and Human Review.
- **REQ-011**: Use the real configured model for live integration tests; do not implement a fake chat model.
- **REQ-012**: Keep normal unit tests network-free and require explicit selection of tests marked `live_llm`.
- **REQ-013**: Do not implement Transaction, KYC, Screening, RAG, policy, typology, or citation-validation domain logic.
- **REQ-014**: The Report Agent must set `recommended_action` to `HUMAN_REVIEW_REQUIRED` and `automated_compliance_decision` to `false`.
- **SEC-001**: Revoke the credential currently committed in `backend/.env.example` before any live request and never reuse it.
- **SEC-002**: Store the replacement credential only in ignored `backend/.env`; keep `backend/.env.example` secret-free.
- **SEC-003**: Never include credentials in logs, exceptions, checkpoints, test output, snapshots, prompts, or Git commits.
- **SEC-004**: Do not permit an agent to call a tool outside its registered allowlist.
- **SEC-005**: Do not persist model chain-of-thought or private specialist message history.
- **CON-001**: Continue using Python 3.11 or newer and `langgraph>=1.0,<2.0`.
- **CON-002**: Treat the endpoint as OpenAI-compatible but do not assume it supports tool calling or structured output until the live capability gate passes.
- **CON-003**: Do not add PostgreSQL checkpointing, vector stores, API endpoints, or frontend work to this implementation.
- **GUD-001**: Set model temperature to `0`, timeout to `60` seconds, SDK retry count to `2`, and local agent recursion limit to `8`.
- **GUD-002**: Pass only the minimum role-specific context into each agent.
- **GUD-003**: Keep tool-call and model-output validation at deterministic Python boundaries.
- **PAT-001**: Use the outer LangGraph Graph API for orchestration and maintained LangChain agent primitives for local model-tool loops.

## 2. Implementation Steps

### Implementation Phase 1

- **GOAL-001**: Remove credential exposure and prove the selected endpoint has the capabilities required by the design.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Revoke the credential currently present in tracked `backend/.env.example` through the provider account, create a replacement credential, and do not place the replacement in any tracked file. This task must complete before TASK-005. | | |
| TASK-002 | Update `.gitignore` to include `backend/.env` while preserving its existing virtual-environment and cache exclusions. | | |
| TASK-003 | Replace `backend/.env.example` with exactly the empty keys `API_KEY=`, `BASE_URL=`, and `MODEL_NAME=glm-5.2-free`; create local untracked `backend/.env` with the replacement credential and configured endpoint. | | |
| TASK-004 | Add `langchain>=1.0,<2.0`, `langchain-openai>=1.0,<2.0`, `pydantic>=2.0,<3.0`, and `pydantic-settings>=2.0,<3.0` to `backend/requirements.txt`; install the updated runtime and existing development requirements into `backend/.venv`. | | |
| TASK-005 | Add `backend/tests/integration/test_llm_capabilities.py` with live tests for basic chat, one deterministic test-tool call, and `ToolStrategy` schema validation using `glm-5.2-free`; mark every test `live_llm`. If any capability fails, stop implementation after recording a redacted failure and set this plan to `On Hold`. | | |

### Implementation Phase 2

- **GOAL-002**: Implement model configuration, structured contracts, prompts, and tool ownership boundaries.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-006 | Create `backend/app/investigation_orchestrator/model.py` with a cached Pydantic Settings loader for `API_KEY`, `BASE_URL`, and `MODEL_NAME`, defaults from GUD-001, an absolute env-file path rooted at `backend/.env`, redacted validation errors, and `build_chat_model()` returning an unbound `ChatOpenAI`. Depends on TASK-005. | | |
| TASK-007 | Create `backend/app/investigation_orchestrator/agent_schemas.py` with Pydantic models for `PlanStep`, `InvestigationPlanResponse`, `AgentFindingResponse`, `WorkerAnalysisResponse`, and `InvestigationReportResponse`; enforce non-empty evidence IDs on findings and the fixed Human Review fields required by REQ-014. | | |
| TASK-008 | Create `backend/app/investigation_orchestrator/prompts.py` with one versioned system prompt per LLM agent and pure context builders that serialize only the role-specific fields listed in GUD-002. | | |
| TASK-009 | Implement `ToolRegistry` in `backend/app/investigation_orchestrator/tool_registry.py` with the agent keys `transaction`, `kyc`, and `screening`; reject duplicate tool names, reject cross-owner lookup, return tuples instead of mutable lists, and expose no domain implementation. | | |
| TASK-010 | Define and document the required external tool result contract in `tool_registry.py`: a JSON-serializable object with `status`, `data`, `evidence`, `warnings`, and optional `error_code`; each evidence object must contain `evidence_id`, `source_system`, and `source_record_id`. | | |
| TASK-011 | Add deterministic helpers in `backend/app/investigation_orchestrator/agents.py` to parse structured `ToolMessage` content, collect tool-derived evidence, reject duplicate or malformed evidence, and verify every LLM finding references collected evidence. | | |

### Implementation Phase 3

- **GOAL-003**: Build the five LLM agents without implementing domain tools.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-012 | In `agents.py`, implement `build_planner_agent(model)` using `create_agent`, no tools, the Planner prompt, and `ToolStrategy(InvestigationPlanResponse)`. | | |
| TASK-013 | In `agents.py`, implement `build_transaction_agent(model, tools)` with only the Transaction allowlist and `ToolStrategy(WorkerAnalysisResponse)`; return `INCONCLUSIVE` without invoking the model when `tools` is empty. | | |
| TASK-014 | In `agents.py`, implement `build_kyc_agent(model, tools)` with only the KYC allowlist and SHB/external restrictions in its prompt; return `INCONCLUSIVE` without invoking the model when `tools` is empty. | | |
| TASK-015 | In `agents.py`, implement `build_screening_agent(model, tools)` with only the Screening/Compliance allowlist and deterministic post-validation for `INCONCLUSIVE` and external name-only matches; return `INCONCLUSIVE` without invoking the model when `tools` is empty. | | |
| TASK-016 | In `agents.py`, implement `build_report_agent(model)` using no tools and `ToolStrategy(InvestigationReportResponse)`; reject any structured response that violates REQ-014. | | |
| TASK-017 | Add one invocation helper per agent that applies recursion limit `8`, extracts `structured_response`, discards private messages, combines findings with tool-derived evidence, and converts provider/schema failures into serializable error results without exposing credentials. | | |

### Implementation Phase 4

- **GOAL-004**: Replace workflow stubs with LLM wrappers while preserving mandatory orchestration behavior.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-018 | Update `backend/app/investigation_orchestrator/state.py` so `investigation_plan`, `AgentOutput`, errors, and report fields accept the validated serializable structures produced by Phase 3 without adding message-history state. | | |
| TASK-019 | Refactor `backend/app/investigation_orchestrator/nodes.py` to keep `supervisor_node`, `parallel_dispatch_node`, and `merge_and_validate_node` deterministic while replacing Planner, Transaction, KYC, and Screening stubs with thin wrappers around the injected agents. | | |
| TASK-020 | Replace the deterministic stub in `backend/app/investigation_orchestrator/report_agent.py` with a thin LLM Report wrapper that receives only validated case data and validation issues. | | |
| TASK-021 | Update `backend/app/investigation_orchestrator/workflow.py` to build one reusable model instance, obtain immutable tool lists from `ToolRegistry`, construct the five agents once per compiled workflow, and inject their wrapper nodes without storing any dependency in graph state. | | |
| TASK-022 | Preserve the existing static Transaction/KYC fork-join edges, Supervisor `Command` routing, injectable checkpointer, and Human Review interrupt/resume path exactly; add a failed-agent path that still produces a report and reaches Human Review. | | |
| TASK-023 | Update `backend/app/investigation_orchestrator/__init__.py` to export only stable construction contracts: `build_workflow`, `ToolRegistry`, state input types, and `initial_state`; do not export prompts or provider credentials. | | |

### Implementation Phase 5

- **GOAL-005**: Verify business rules, isolation, live model behavior, and end-to-end Human Review.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-024 | Add `backend/tests/unit/test_tool_registry.py` covering allowlists, duplicate names, cross-owner denial, immutable lookup results, malformed tool results, and evidence extraction. | | |
| TASK-025 | Add `backend/tests/unit/test_agent_schemas.py` covering plan schema, evidence-reference requirements, report safety constants, and serialization into outer state. | | |
| TASK-026 | Add `backend/tests/unit/test_agent_context.py` proving each prompt context excludes unrelated state, credentials, model objects, and private agent messages. | | |
| TASK-027 | Refactor `backend/tests/unit/test_investigation_workflow.py` to inject deterministic agent-node fixtures rather than a fake chat model, preserving all existing routing, merge, Evidence Validator, and Human Review assertions without network requests. | | |
| TASK-028 | Add `backend/tests/integration/test_live_llm_agents.py` with real-endpoint tests for Planner, one tool-using Transaction worker with a deterministic test tool, Screening safety behavior, and Report output; mark all tests `live_llm`. | | |
| TASK-029 | Add `backend/tests/integration/test_live_llm_workflow.py` that supplies deterministic test tools through `ToolRegistry`, invokes the complete real-model workflow to the Human Review interrupt, verifies tool-derived provenance, and resumes with `APPROVED`. | | |
| TASK-030 | Add `backend/pytest.ini` registering the `live_llm` marker and configure the default test command to exclude it; document the separate live command in `backend/README.md`. | | |
| TASK-031 | Run `pytest -m "not live_llm"`, then explicitly run the capability and live integration tests with `pytest -m live_llm`, run `python -m compileall app tests`, and run `git diff --check`; record only redacted failures. | | |
| TASK-032 | Confirm `git diff --cached` and `git status --short` contain neither `backend/.env` nor any credential value, then update this plan to `Completed` only if every Phase 5 command passes. | | |

## 3. Alternatives

- **ALT-001**: Build a custom `StateGraph` plus `ToolNode` loop for each worker. Rejected because `create_agent` already provides the required local model-tool loop and structured output handling.
- **ALT-002**: Use one agent with dynamic middleware to switch roles and tool sets. Rejected because Transaction and KYC must run concurrently and separate allowlists are easier to audit.
- **ALT-003**: Make the Supervisor fully LLM-driven. Rejected because mandatory evidence validation and Human Review gates must remain deterministic.

## 4. Dependencies

- **DEP-001**: Python 3.11 or newer.
- **DEP-002**: `langgraph>=1.0,<2.0` for the existing outer workflow, `Command`, checkpointing, and interrupts.
- **DEP-003**: `langchain>=1.0,<2.0` for `create_agent` and `ToolStrategy`.
- **DEP-004**: `langchain-openai>=1.0,<2.0` for `ChatOpenAI` against the configured OpenAI-compatible endpoint.
- **DEP-005**: `pydantic>=2.0,<3.0` and `pydantic-settings>=2.0,<3.0` for structured agent outputs and secret-safe environment settings.
- **DEP-006**: Tools supplied by the Transaction, KYC, and Screening/Compliance owners that conform to the contract declared by TASK-010.
- **DEP-007**: A rotated provider credential and an endpoint account permitted to call `glm-5.2-free`.

## 5. Files

- **FILE-001**: `.gitignore` — ignore `backend/.env` without removing existing exclusions.
- **FILE-002**: `backend/.env.example` — secret-free environment variable template.
- **FILE-003**: `backend/requirements.txt` — LangChain, provider, and validation dependencies.
- **FILE-004**: `backend/app/investigation_orchestrator/model.py` — settings and `ChatOpenAI` construction.
- **FILE-005**: `backend/app/investigation_orchestrator/agent_schemas.py` — structured response contracts.
- **FILE-006**: `backend/app/investigation_orchestrator/prompts.py` — agent prompts and context builders.
- **FILE-007**: `backend/app/investigation_orchestrator/agents.py` — agent builders, invocation, and tool-evidence extraction.
- **FILE-008**: `backend/app/investigation_orchestrator/tool_registry.py` — agent tool ownership and result contract.
- **FILE-009**: `backend/app/investigation_orchestrator/state.py` — serializable outer graph state.
- **FILE-010**: `backend/app/investigation_orchestrator/nodes.py` — deterministic control nodes and LLM worker wrappers.
- **FILE-011**: `backend/app/investigation_orchestrator/report_agent.py` — LLM report wrapper.
- **FILE-012**: `backend/app/investigation_orchestrator/workflow.py` — dependency construction and graph compilation.
- **FILE-013**: `backend/app/investigation_orchestrator/__init__.py` — stable orchestration exports.
- **FILE-014**: `backend/tests/unit/test_tool_registry.py` — tool ownership and evidence tests.
- **FILE-015**: `backend/tests/unit/test_agent_schemas.py` — structured contract tests.
- **FILE-016**: `backend/tests/unit/test_agent_context.py` — role-context isolation tests.
- **FILE-017**: `backend/tests/unit/test_investigation_workflow.py` — network-free outer workflow tests.
- **FILE-018**: `backend/tests/integration/test_llm_capabilities.py` — endpoint capability gate.
- **FILE-019**: `backend/tests/integration/test_live_llm_agents.py` — live specialist agent tests.
- **FILE-020**: `backend/tests/integration/test_live_llm_workflow.py` — live full-workflow test.
- **FILE-021**: `backend/pytest.ini` — live test marker registration and test defaults.
- **FILE-022**: `backend/README.md` — local and live verification commands.

## 6. Testing

- **TEST-001**: Reject missing `API_KEY` or `BASE_URL` without printing either value.
- **TEST-002**: Verify `glm-5.2-free` basic chat against the real configured endpoint.
- **TEST-003**: Verify the real model emits a schema-valid call to one deterministic test tool.
- **TEST-004**: Verify `ToolStrategy` returns a Pydantic-validated structured response.
- **TEST-005**: Verify each agent receives only its registered tool names.
- **TEST-006**: Verify worker evidence is collected from tool results and model-only evidence is discarded.
- **TEST-007**: Verify a worker with no tools returns `INCONCLUSIVE` without inventing findings.
- **TEST-008**: Verify external name-only screening cannot become `CONFIRMED_MATCH`.
- **TEST-009**: Verify screening-source failure remains `INCONCLUSIVE`.
- **TEST-010**: Verify the Report Agent cannot produce an automated compliance decision.
- **TEST-011**: Verify Transaction and KYC still complete before deterministic merge.
- **TEST-012**: Verify provider failure produces a reviewable error dossier and reaches Human Review.
- **TEST-013**: Verify the full live workflow interrupts and resumes with a stable `thread_id`.
- **TEST-014**: Verify no secret or raw model message is present in persisted outer state.

## 7. Risks & Assumptions

- **RISK-001**: The third-party endpoint may support basic chat but not schema-valid tool calling; TASK-005 prevents implementing an incompatible design.
- **RISK-002**: Free-model availability, rate limits, or latency may make live tests unstable; unit tests remain network-free and live failures retain redacted provider context.
- **RISK-003**: The credential currently stored in Git must be considered compromised even after the working-tree file is sanitized; revocation is mandatory.
- **RISK-004**: Tool results supplied by other team members may not conform to TASK-010; the Registry rejects malformed results instead of passing them to an LLM.
- **RISK-005**: A model may cite an evidence ID that did not originate from a tool result; deterministic extraction and the existing Evidence Validator reject it.
- **RISK-006**: Replaying a failed node may repeat read-only tool calls; tools in this scope must not have side effects.
- **RISK-007**: Live model output is non-deterministic even at temperature zero; assertions validate contracts and safety invariants rather than exact prose.
- **ASSUMPTION-001**: `BASE_URL` implements the OpenAI Chat Completions request and response shape required by `ChatOpenAI`.
- **ASSUMPTION-002**: Domain tools are read-only and their owners will supply LangChain-compatible callables or `BaseTool` objects.
- **ASSUMPTION-003**: In-memory checkpointing remains acceptable for MVP development and tests.
- **ASSUMPTION-004**: The current mandatory workflow stage order remains unchanged.

## 8. Related Specifications / Further Reading

- [LLM Agent integration design](../docs/superpowers/specs/2026-07-18-llm-agent-integration-design.md)
- [Existing Hybrid Supervisor design](../docs/superpowers/specs/2026-07-18-hybrid-supervisor-workflow-design.md)
- [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output)
- [LangChain tools and ToolNode](https://docs.langchain.com/oss/python/langchain/tools)
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
