# Documentation index

Living product docs live in this folder. Feature design/history lives under
`superpowers/`. Operational runbooks live under `backend/`.

## Current product docs

| Doc | Role |
|-----|------|
| [PROJECT.md](./PROJECT.md) | Goals, users, scope, stack overview |
| [architecture.md](./architecture.md) | High-level architecture and data model |
| [BUSINESS_RULES.md](./BUSINESS_RULES.md) | Non-negotiable AML/business constraints |
| [TEST_SCENARIOS.md](./TEST_SCENARIOS.md) | Kịch bản thử nghiệm (phổ biến + phức tạp, map ground truth) |

## Operational runbooks (backend)

| Doc | Role |
|-----|------|
| [../backend/README.md](../backend/README.md) | Env, pytest, live LLM notes |
| [../backend/README-KAFKA.md](../backend/README-KAFKA.md) | Kafka raw → validated pipeline |
| [../backend/README-DETECTION.md](../backend/README-DETECTION.md) | Realtime detection + investigation queue |
| [../backend/synthetic_data/README.md](../backend/synthetic_data/README.md) | Synthetic data generator |

## Feature specs and implementation plans

Dated files under:

- `superpowers/specs/` — design decisions for a feature
- `superpowers/plans/` — step-by-step implementation plans

Treat these as **feature history**. Prefer code + backend runbooks for “what
runs today”. Some early designs still mention a LangGraph Human Review
interrupt; that interrupt was removed from the runtime workflow. Analyst review
remains a product rule (no auto block / SAR / final compliance decision).

Active/recent designs worth reading first:

- `superpowers/specs/2026-07-19-realtime-detection-queue-design.md`
- `superpowers/specs/2026-07-19-investigation-control-soft-prompt-design.md`
- `superpowers/specs/2026-07-18-realtime-kafka-ingestion-design.md`
- `superpowers/specs/2026-07-18-llm-agent-integration-design.md`

## Removed placeholders

Empty scaffold files `api-contract.md`, `langgraph-flow.md`, and
`team-ownership.md` were removed (never filled). Early duplicate plans under
repo-root `plan/` were removed; content lives under `superpowers/` instead.
