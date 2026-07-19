# Frontend Agent Topology Design

## Goal

Make the Workflow and Monitoring screens reflect the current backend workflow
without presenting unavailable telemetry as real data.

## Source of truth

`backend/app/investigation_orchestrator/workflow.py` currently contains six LLM
agents: Planner, Transaction, KYC, Screening, Behavior Mapper, and Report. It
also contains five deterministic system nodes: Supervisor, Parallel Dispatch,
Merge & Validate, Legal RAG, and Evidence Validator.

## Design

- Add a typed frontend catalog containing exactly those eleven nodes and the
  normal successful workflow transitions.
- Render all eleven nodes in Workflow, with LLM agents and system nodes using
  distinct labels and visual treatments.
- Show only the six LLM agents in the side catalog and Monitoring screen.
- Replace fabricated health, latency, processed-task, utilization, activity,
  restart, and export-log data with an explicit message that backend telemetry
  APIs do not exist yet.
- Preserve Dashboard, ticket History, Configuration, models, and all existing
  backend API clients unchanged.
- Do not add a backend endpoint in this slice.

## Verification

- Unit-test catalog membership, type counts, and required transitions.
- Run frontend tests, TypeScript, scoped ESLint, and production build when the
  environment permits it.

