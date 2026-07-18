# LLM Agent Integration Design

## 1. Scope

Replace the deterministic Planner, Transaction, KYC, Screening, and Report
stubs in the existing Hybrid Supervisor workflow with real LLM-backed agents.
The selected model is `glm-5.2-free`, accessed through an OpenAI-compatible
Chat Completions endpoint configured by environment variables.

This work owns agent orchestration, prompts, structured output, tool
registration, and graph integration. It does not implement transaction, KYC,
screening, typology, policy retrieval, or citation-validation tool logic. Those
tools are supplied by other team members and injected through the Tool
Registry.

## 2. Selected Architecture

The outer investigation workflow remains a LangGraph `StateGraph`. Mandatory
stage transitions remain deterministic and continue to use `Command` handoffs.
Each LLM worker is built with LangChain `create_agent`, which supplies the
standard model-tool loop and structured response handling without adding a
second custom graph implementation.

```text
Deterministic Hybrid Supervisor
    -> LLM Planner
    -> parallel LLM Transaction Agent + LLM KYC Agent
    -> deterministic merge
    -> LLM Screening/Compliance Agent
    -> deterministic Evidence Validator
    -> LLM Report Agent
    -> deterministic Human Review interrupt
```

Supervisor routing, evidence validation, Shared Case File mutation, and Human
Review must not be delegated to an LLM. The LLM Planner may enrich the
investigation plan, but it cannot remove mandatory workflow stages or bypass
the Supervisor's Python preconditions.

## 3. Alternatives Considered

### Raw `ToolNode` loops inside every worker

Building a separate `StateGraph` with an LLM node, `ToolNode`, and conditional
edges for each worker offers maximum control. It is rejected for the first
implementation because it duplicates the standard loop already provided by
`create_agent` and increases the number of reducers, routes, and failure paths
we must maintain.

### One dynamic agent with middleware

A single agent could switch prompts and tool sets according to the current
phase. It is rejected because Transaction and KYC must execute in parallel and
because separate tool allowlists are easier to audit when each worker is a
distinct agent.

### Selected: outer custom workflow plus `create_agent` workers

This keeps the existing explicit AML workflow while delegating only the local
LLM-tool loop to a maintained framework primitive. It also preserves clear
ownership boundaries and allows each worker to be tested independently.

## 4. Model Configuration and Credential Safety

`ChatOpenAI` from `langchain-openai` will be configured with:

- `model`: environment variable `MODEL_NAME`, default `glm-5.2-free`.
- `api_key`: required environment variable `API_KEY`.
- `base_url`: required environment variable `BASE_URL`.
- `temperature`: `0`.
- `timeout`: `60` seconds.
- `max_retries`: `2`.

The third-party endpoint must pass a live capability gate before agent
implementation proceeds:

1. A basic chat request returns an assistant message.
2. A registered test tool is selected and receives schema-valid arguments.
3. `create_agent` returns a response validated through `ToolStrategy`.

Failure of chat or tool calling blocks the implementation because those are
required capabilities. Failure of `ToolStrategy` also blocks structured worker
integration; the system must not silently fall back to unvalidated free-form
JSON.

The repository currently contains a credential in the tracked
`backend/.env.example` file. That key must be revoked before any live request.
The example file will contain empty values only, the replacement credential
will live in untracked `backend/.env`, and `.gitignore` will explicitly ignore
that file. Credentials must never appear in logs, exceptions, checkpoints,
test snapshots, or commits.

## 5. Agent Components

### LLM Planner

The Planner receives the case ID and alert. It returns a structured plan with
the mandatory stages plus case-specific investigative focus. The deterministic
Supervisor remains the authority on execution order.

### Transaction Agent

The Transaction Agent receives the alert and only the seven registered
Transaction tools. It must not query KYC, ownership, screening, or policy
tools. Its findings must reference evidence IDs returned by tool calls and must
include visibility for transaction-pattern findings.

### KYC Agent

The KYC Agent receives the alert and only the six registered KYC/Entity tools.
Its prompt explicitly prohibits inferring KYC or UBO data for external
counterparties. Tool-layer enforcement remains the domain tool owner's
responsibility; the prompt is a second guard, not the primary control.

### Screening and Compliance Agent

This agent runs after the Transaction/KYC merge and receives the staged Shared
Case File plus only the four registered Screening/Compliance tools. A failed
or unavailable source must produce `INCONCLUSIVE`, never `NO_MATCH`. An
external name-only result cannot become `CONFIRMED_MATCH`.

### Report Agent

The Report Agent receives only the validated Shared Case File and validation
summary. It has no domain tools. It creates a structured dossier draft and
must always set `automated_compliance_decision` to `false` and
`recommended_action` to `HUMAN_REVIEW_REQUIRED`.

## 6. Tool Boundary and Evidence Provenance

`ToolRegistry` owns agent-specific allowlists. It accepts tools supplied by the
other team members and returns an immutable tool list for one named agent. The
Registry does not implement or modify domain logic.

Every integrated domain tool must return a JSON-serializable object containing
its domain data and an `evidence` list. Each evidence item must include
`evidence_id`, `source_system`, and `source_record_id`; transaction patterns
must also include `visibility_level`.

Worker structured responses contain findings and metadata, but evidence
payloads are collected deterministically from successful `ToolMessage`
results. The wrapper node discards any evidence payload invented in model text.
The final `AgentOutput` combines LLM findings with tool-derived evidence. The
existing Evidence Validator then rejects findings that reference evidence not
present in that collected set.

When an agent has no registered tools, its wrapper returns an `INCONCLUSIVE`
output with no findings instead of asking the model to invent an investigation.

## 7. State and Context Isolation

The outer `InvestigationState` remains the durable workflow state. Agent-local
message histories, model clients, tool objects, and raw provider responses are
not written into it.

Each wrapper constructs the smallest relevant input:

- Planner: `case_id` and `alert`.
- Transaction and KYC: `case_id`, `alert`, and the current investigation plan.
- Screening: merged findings and evidence references.
- Report: validated findings, evidence references, and validation issues.

The wrapper keeps tool-call messages private, extracts the structured response
and evidence, and returns only a serializable partial state update. This avoids
checkpoint bloat and prevents one specialist from receiving another
specialist's private reasoning trace.

## 8. Error Handling

- Missing model configuration fails at workflow construction with a redacted,
  actionable configuration error.
- Authentication and authorization failures stop the live capability gate;
  credentials are never included in the error text.
- Provider timeouts and transient failures use at most two SDK retries. An
  exhausted call creates a workflow error and routes the partial dossier to
  Human Review.
- Tool input validation errors are returned to the local agent loop for one
  correction attempt under the agent recursion limit.
- Tool execution or source-availability failures produce `INCONCLUSIVE` and
  remain visible in warnings/errors.
- Invalid structured output is not merged. It creates a failed agent output
  and proceeds to a reviewable error dossier rather than crashing the graph.
- Each local agent invocation uses a recursion limit of eight graph steps to
  prevent uncontrolled tool loops.

## 9. Testing Strategy

No fake chat model will be implemented.

Pure unit tests cover configuration validation, prompt construction, schemas,
Tool Registry ownership, tool-evidence extraction, deterministic Supervisor
routing, merge behavior, and Evidence Validator rules without making network
requests.

Live integration tests use the configured `glm-5.2-free` endpoint. They cover
basic chat, one test-tool call, structured Planner output, one worker output,
Report output, and the complete workflow through the Human Review interrupt.
Test tools are small deterministic fixtures used only to prove agent-tool
integration; they are not implementations of AML domain logic.

Live tests are marked `live_llm` and require explicit execution. Normal unit
test runs remain deterministic and must not consume API quota.

## 10. File Layout

- `model.py`: environment settings and `ChatOpenAI` construction.
- `agent_schemas.py`: Pydantic structured response contracts.
- `prompts.py`: versioned system prompts and minimal context builders.
- `agents.py`: `create_agent` builders and agent invocation helpers.
- `tool_registry.py`: tool ownership and immutable allowlists.
- `nodes.py`: deterministic Supervisor/merge plus LLM worker wrappers.
- `report_agent.py`: LLM report wrapper.
- `workflow.py`: dependency injection and graph compilation.
- `state.py`: serializable outer state contracts.
- `backend/tests/unit`: deterministic tests without model calls.
- `backend/tests/integration`: explicitly marked live model tests.

## 11. Exclusions

- Domain tool algorithms and data repositories.
- RAG/vector-store implementation.
- Production PostgreSQL checkpoint setup.
- Autonomous compliance decisions, account blocking, and SAR/STR submission.
- Persisting chain-of-thought or raw agent message history in the Shared Case
  File.
