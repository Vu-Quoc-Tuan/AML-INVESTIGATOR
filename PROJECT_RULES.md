# AML-INVESTIGATOR — Project Rules

## 1. System Overview

A multi-agent system that automates the investigation process after an AML alert is generated. The system combines transaction analysis, relationship graphs, KYC profiles, UBO (Ultimate Beneficial Ownership), sanctions/PEP screening, AML typology libraries, and internal policies to build an evidence-backed investigation dossier before forwarding it to an AML analyst for approval.

> [!IMPORTANT]
> The system **does not replace** human analysts. It automates the collection, verification, linking, and presentation of evidence so that analysts can make decisions **faster**, **more consistently**, and with **full auditability**.

---

## 2. Objectives

| #  | Objective                                                                          |
| -- | ---------------------------------------------------------------------------------- |
| G1 | Reduce time from alert to review-ready dossier.                                    |
| G2 | Minimize manual effort in tracing transactions and retrieving KYC context.          |
| G3 | Reduce false positives through entity resolution and attribute-level screening.    |
| G4 | Improve explainability via evidence references and feature contribution details.   |
| G5 | Standardize reasoning and reporting across analysts.                               |
| G6 | Keep final decision authority with humans.                                         |

---

## 3. MVP Scope

| Scope                       | Description                                                    |
| --------------------------- | -------------------------------------------------------------- |
| Alert Intake                | Receive alerts from simulator or detection engine.             |
| Transaction Patterns        | Fan-in, fan-out, rapid pass-through, basic cycle detection.    |
| Transaction Graph           | 1–3 hop traversal.                                             |
| KYC                         | KYC profile retrieval and profile mismatch detection.          |
| Ownership                   | Ownership graph and basic UBO resolution.                      |
| Screening                   | Attribute-level sanctions/PEP/watchlist screening.             |
| RAG                         | Typology RAG, policy retrieval, citation validation.           |
| Output                      | Evidence ledger, report draft, HITL (Human-In-The-Loop).       |

---

## 4. Tech Stack

| Layer            | Technology                                          |
| ---------------- | --------------------------------------------------- |
| Database         | PostgreSQL                                          |
| Data Storage     | JSON / CSV, Local Object Storage                    |
| Detection Engine | Python, Pandas / Polars, Scikit-learn / XGBoost     |
| Graph            | NetworkX                                            |
| Agent            | LangGraph + FastAPI                                 |
| RAG              | pgvector or Qdrant                                  |
| Backend          | FastAPI + Pydantic                                  |
| Frontend         | Next.js + React + React Flow / Cytoscape.js         |
| Streaming        | SSE (FastAPI `StreamingResponse`)                   |
| Observability    | Langfuse + OpenTelemetry                            |
| Deployment       | Docker (covered in Integration / DevOps)            |

---

## 5. System Architecture

### Data Flow

1. **Data Layer** — source systems providing: Transactions, KYC, Company, Watchlist, Knowledge Base.
2. **Detection Layer** — processes data through Feature Engine + Rule Engine + ML Model + Graph Analytics.
3. **Risk Aggregator** — combines outputs from all detection layers into a **Final Risk Score**.
4. **AML Alert** — generated when risk score exceeds threshold or a hard rule is triggered.
5. **Case Orchestrator** — receives the alert and dispatches work to parallel agents:
   - **Transaction Agent** — analyzes transaction patterns and money flow.
   - **KYC Agent** — retrieves and evaluates KYC profiles for mismatches.
   - **Screening Agent** — performs sanctions / PEP / watchlist screening.
6. **Shared Case File** — collects and consolidates all agent outputs.
7. **Evidence Validator** — validates evidence integrity and completeness.
8. **Investigation Report** — generated from validated evidence and findings.
9. **AML Reviewer (HITL)** — human analyst reviews the report and makes the **Final Decision**.

---

## 6. Business Rules

The system is divided into two main business phases: **Detection** and **Investigation**.

### 6.1 Detection

During the Detection phase, the system continuously monitors incoming transactions and maintains features across multiple time windows (1 min, 5 min, 10 min, 1 hour, 24 hours, and 30 days). Features include:

- Number of sending accounts.
- Total transaction value.
- Transfer velocity.
- Pass-through ratio.
- Account age.
- Country risk level of the receiving jurisdiction.
- Deviation from KYC profile.
- Graph relationships: common funding source, shared device, shared IP.

The Detection Engine evaluates features through **three processing layers**:

1. **Rule Engine**
2. **Anomaly Detection Model**
3. **Graph Risk Analysis**

Results from all three layers are aggregated by the **Risk Aggregator** to produce a **Final Risk Score**. An alert is generated only when:

- The risk score exceeds a defined threshold, **or**
- A hard rule is triggered (e.g., confirmed sanctions match).

> [!CAUTION]
> The Detection Engine's **sole responsibility** is to determine that a transaction exhibits sufficient anomalous indicators to warrant investigation. The Detection Engine **MUST NOT** conclude that a customer is engaged in money laundering or make any legal determination.

### 6.2 Investigation

Once an Alert is created, the system transitions to the Investigation phase. The **Case Orchestrator** initializes an Investigation Case and coordinates specialized agents to analyze:

- Transactions.
- KYC profiles.
- Entity relationships.
- Screening results.
- AML typologies.

#### Evidence & Finding Rules

- Agents may only create a **Finding** based on **Evidence** with a clearly traceable origin.
- Each Finding **MUST** reference at least one `evidence_id`.
- Findings without valid evidence **WILL NOT** be included in the investigation report.
- Evidence is stored using an **append-only** mechanism — it cannot be edited or deleted to ensure full auditability.

### 6.3 Detailed Business Rules

#### BR-01. Alert Explanation

Each Alert **MUST** contain complete explanatory information including `triggered_rules`, `feature_values`, and `explanation`. The system **MUST NOT** return only a `risk_score` value — it must explicitly identify the factors contributing to the risk score to ensure **Explainability**.

#### BR-02. Multi-rule Trigger

An Investigation Case may be triggered by **multiple Rule Detectors simultaneously**. The `Final Risk Score` is aggregated from Rule Engine, Anomaly Model, Graph Risk, and KYC Deviation rather than relying on a single detector. This helps reduce false positives and improves detection of complex money laundering behaviors.

#### BR-03. LLM Boundary

All business computations such as transaction features, graph metrics, matching scores, and risk aggregation are performed by the backend or Machine Learning models.

> [!WARNING]
> - The LLM **MUST NOT** perform calculations or access the database directly.
> - AI is only permitted to invoke pre-defined **Backend Tools** with full schema, timeout, allowlist, and audit trail.

#### BR-04. Fail-safe on Data Unavailability

When a critical data source such as Watchlist or Screening Service is **unavailable**, the system **MUST NOT** conclude `NO_MATCH`. Instead, the status must be set to:

- `INCONCLUSIVE`, or
- `MANUAL_REVIEW_REQUIRED`

to prevent **false negatives**.

#### BR-05. Context-aware Risk Adjustment

The system must **reduce the risk score** for cases with valid business context, such as:

- Collection agencies.
- Merchants.
- Educational institutions.
- Fan-in patterns confirmed as normal business operations.

to minimize **false positives**.

#### BR-06. Human-In-The-Loop Decision

After completing the investigation, the system **only** generates a report and provides a recommendation:

| Recommendation                | Meaning                                                |
| ----------------------------- | ------------------------------------------------------ |
| `ESCALATE_FOR_SAR_REVIEW`    | Recommend escalation for SAR (Suspicious Activity Report) review. |
| `CLEARED_WITH_RATIONALE`     | Recommend clearing the case with documented rationale. |
| `NEED_MORE_EVIDENCE`         | Request additional evidence collection.                |

> [!IMPORTANT]
> The final business and compliance decision is **always made by the AML Reviewer** (human).

---

## 7. Database

The system uses **PostgreSQL** as the primary database for storing all business data and investigation state.

### 7.1 Data Groups

| Group                  | Contents                                                                                                               |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **Master Data**        | Customers, companies, accounts, KYC profiles, KYC documents, entity relationships, watchlists, AML typology library.  |
| **Transaction Data**   | Transactions, computed features, alerts, risk scoring results.                                                         |
| **Investigation Data** | Cases, tasks, findings, evidence, screening results, typology matches, timeline, reports, reviewer decisions.          |
| **Audit Data**         | Agent execution history, tool execution logs, state transitions, all user actions.                                     |

### 7.2 Data Relationships

- **Customer** → owns one or more **Account**.
  - **Account** → contains one or more **Transaction**.
    - **Transaction** → may trigger one or more **Alert**.
      - **Alert** → may initiate an investigation **Case**.
        - **Case** contains:
          - **Findings** — suspicious indicators identified by agents.
          - **Evidence** — supporting data linked to findings.
          - **Timeline** — chronological record of agent actions.
          - **Report** — final investigation report.
          - **Human Review** — reviewer decision and comments.

> [!NOTE]
> All Evidence references its original record via `source_system` and `source_record_id`, ensuring that every conclusion can be traced back to its source data.

---

## 8. Backend

The backend is built with **FastAPI** following a **service-oriented architecture** and serves as the **sole intermediary** between AI Agents and the database.

### 8.1 Core Responsibilities

- Receive Alerts from the Detection Engine.
- Initialize Investigation Cases.
- Orchestrate LangGraph workflows.
- Provide Tool APIs for Agents.
- Query data from PostgreSQL.
- Perform business computations.
- Validate input/output schemas.
- Manage the Shared Case File and store Evidence.

### 8.2 Agent Tool APIs

| Service                    | Description                                      |
| -------------------------- | ------------------------------------------------ |
| Transaction Service        | Query transactions, compute features.            |
| KYC Service                | Retrieve KYC profiles, detect profile mismatches.|
| Graph Service              | Build relationship graphs, compute graph metrics.|
| Screening Service          | Look up sanctions / PEP / watchlist entries.     |
| Policy Retrieval Service   | Retrieve AML policies, typology RAG.             |

> [!WARNING]
> AI Agents **MUST NOT** access the database directly. All data retrieval must go through Backend Tools with full schema, timeout, allowlist, and audit mechanisms.

### 8.3 Frontend REST APIs

- Alert Management
- Case Management
- Investigation Workflow
- Evidence Ledger
- Report Review
- Human Review

### 8.4 Streaming

The system uses **Server-Sent Events (SSE)** via `FastAPI StreamingResponse` to stream agent execution status in real-time to the user interface.

---

## 9. Frontend

The frontend is built with **Next.js**, **React**, and visualization libraries such as **React Flow** or **Cytoscape.js** to provide an intuitive investigation interface for AML Reviewers.

### 9.1 Main Screens

| Screen                      | Description                                                                                                            |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **Alert Queue**             | List of alerts with risk levels and detection rationale.                                                               |
| **Investigation Workspace** | Money flow graph, entity relationships, KYC information, agent execution timeline, collected evidence list.            |
| **Findings & Typology**     | Suspicious indicators, screening results, profile mismatches, detected AML typologies with related policies.           |
| **Report Review**           | Investigation report, version history, reviewer comments, actions: Escalate / Request More Evidence / Clear / Return for Revision. |

> [!NOTE]
> The frontend **does not process AML business logic**. It only displays data and sends user actions to the Backend via REST API and SSE. All computations, workflow orchestration, and data validation are performed on the Backend to ensure system consistency and security.
