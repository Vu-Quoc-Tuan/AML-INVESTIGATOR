# Frontend Agent Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the obsolete four-agent mock with an accurate six-agent and five-system-node frontend representation.

**Architecture:** A pure typed catalog is the frontend source for names, roles, categories, and graph transitions. Existing Workflow and Monitoring functions consume the catalog; no new backend API or unrelated page behavior is introduced.

**Tech Stack:** Next.js 16, React 19, TypeScript 5, React Flow, Vitest, ESLint.

## Global Constraints

- Modify only agent topology and monitoring presentation.
- Do not modify backend code, Dashboard, History, tickets, Configuration, or API clients.
- Do not describe deterministic system nodes as LLM agents.
- Do not display fabricated telemetry or working controls for missing APIs.
- Do not commit without explicit user approval.

---

### Task 1: Typed workflow catalog

**Files:**
- Create: `frontend/lib/workflow-catalog.ts`
- Test: `frontend/lib/workflow-catalog.test.ts`

**Interfaces:**
- Produces: `WORKFLOW_NODES`, `WORKFLOW_EDGES`, `LLM_AGENTS`, `WorkflowNodeDefinition`.

- [ ] Write a failing test asserting six `agent` nodes, five `system` nodes, unique IDs, and the Transaction/KYC parallel fork.
- [ ] Run `cd frontend && npm test -- workflow-catalog.test.ts` and confirm failure because the module is missing.
- [ ] Implement the catalog with roles copied from the backend workflow.
- [ ] Run the focused test and confirm it passes.

### Task 2: Accurate Workflow and Monitoring screens

**Files:**
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `WORKFLOW_NODES`, `WORKFLOW_EDGES`, and `LLM_AGENTS`.

- [ ] Replace the four hard-coded graph nodes and three edges with catalog-driven React Flow data.
- [ ] Replace fake recent actions with stable role/stage descriptions.
- [ ] Replace fake monitoring metrics and actions with the six-agent catalog and a clear missing-telemetry message.
- [ ] Preserve every non-Workflow/non-Monitoring section byte-for-byte where practical.

### Task 3: Verification

**Files:**
- No new files.

- [ ] Run `cd frontend && npm test`.
- [ ] Run `cd frontend && npx tsc --noEmit`.
- [ ] Run scoped ESLint for `app/page.tsx` and the catalog files; report unrelated pre-existing lint separately.
- [ ] Run `npm run build` if sandbox/browser credits permit.
- [ ] Inspect `git diff -- frontend/app/page.tsx frontend/lib/workflow-catalog*` and verify no unrelated page areas changed.

