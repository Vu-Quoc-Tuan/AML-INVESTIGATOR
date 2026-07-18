# KYC, Document Intelligence, Entity Resolution and UBO Design

## Goal

Implement the backend-owned capabilities for Person 3 of the AML investigation
workflow. The subsystem answers who owns an SHB account, whether KYC evidence
is complete and consistent, who ultimately owns an SHB company, and whether
observed behavior supplied by Person 2 is compatible with the declared KYC
profile.

The implementation is deterministic and evidence-first. It does not use an LLM
to calculate identity matches, document validity, ownership percentages, UBOs,
or profile deviations.

## SHB Observation Boundary

- Only SHB customers, companies, and accounts receive full KYC, document,
  ownership, representative, device, or IP analysis.
- An external counterparty is represented only by payment-message fields:
  external account ID, masked account, bank, country, counterparty name, type,
  visibility, and metadata source.
- Full-KYC or UBO tools called with an external account ID return
  `ENTITY_SCOPE_VIOLATION` and `LIMITED_EXTERNAL_IDENTITY`.
- Entity resolution may compare an external record, but a match identifies the
  observed payment-message record, not the real-world person or company.
- The subsystem never reads or exposes ground truth.

## Selected Architecture

Use small deterministic domain engines behind the Shared DataRepository domain
services:

```text
Shared DataRepository typed queries
                 │
                 ▼
        backend data services
                 │
                 ▼
┌──────────────────────────────────────────────┐
│ KYC domain engines                           │
│ ├── KycSnapshotService                       │
│ ├── DocumentIntelligenceService              │
│ ├── EntityResolutionService                  │
│ ├── OwnershipUboService                      │
│ ├── ProfileDeviationService                  │
│ └── ContradictionService                     │
└──────────────────────────────────────────────┘
                 │
                 ▼
        backend-owned tool adapters
                 │
                 ▼
   Orchestrator evidence validation + atomic append
                 │
                 ▼
        Shared Case File / Evidence Ledger
```

Agents never receive a repository, Pandas object, NetworkX object, or mutable
Shared Case File object. Tool adapters return Pydantic-validated JSON-safe
results.

## Files and Responsibilities

- `backend/app/schemas/kyc_entity.py`: Person 3 input/output contracts.
- `backend/app/schemas/evidence.py`: evidence reference and evidence record
  contracts shared by investigation components.
- `backend/app/schemas/state.py`: minimal Shared Case File sections and
  revision metadata.
- `backend/app/kyc_entity/config.py`: immutable thresholds, required-document
  policy, identity weights, and severity bands.
- `backend/app/kyc_entity/exceptions.py`: entity scope, evidence contract,
  document, and ownership traversal errors.
- `backend/app/kyc_entity/normalization.py`: pure identity normalization.
- `backend/app/kyc_entity/kyc_service.py`: customer and company snapshots.
- `backend/app/kyc_entity/document_intelligence.py`: extracted-field,
  validity, completeness, and document-comparison rules.
- `backend/app/kyc_entity/entity_resolution.py`: deterministic candidate
  scoring and conflict detection; no repository mutation.
- `backend/app/kyc_entity/ownership_ubo.py`: bounded ownership traversal,
  cumulative ownership, UBO calculation, and ownership gaps.
- `backend/app/kyc_entity/profile_deviation.py`: declared-versus-observed
  comparison using Person 2 features.
- `backend/app/kyc_entity/contradiction_detection.py`: cross-source KYC
  contradiction and missing-evidence rules.
- `backend/app/kyc_entity/facade.py`: tool-facing orchestration of the small
  domain services without duplicating their rules.
- `backend/app/investigation_orchestrator/evidence_ledger.py`: idempotent
  evidence append and conflict detection.
- `backend/app/investigation_orchestrator/evidence_validator.py`: validate all
  evidence references before mutation.
- `backend/app/investigation_orchestrator/state.py`: atomic Person 3
  contribution append.
- `backend/app/investigation_orchestrator/case_store.py`: revision-checked,
  process-local Shared Case File store for the MVP.
- `backend/app/investigation_orchestrator/tool_registry.py`: backend-owned
  Person 3 tool adapters bound to the current case context.

## Repository and Data-Service Extensions

The DataRepository remains a Data Access Layer. Add only bounded typed queries:

```python
accounts_for_entity(entity_id: str) -> pd.DataFrame
address_by_id(address_id: str) -> pd.Series | None
kyc_document_by_id(document_id: str) -> pd.Series | None
entities_by_strong_identifier(
    identifier_type: str,
    identifier_value: str,
) -> pd.DataFrame
build_ownership_neighborhood(
    company_id: str,
    as_of_date: str | date | datetime,
    max_depth: int,
) -> nx.DiGraph
```

Every result is a defensive copy. The ownership neighborhood is rooted and
bounded; no tool or service serializes the full active ownership graph.

Corresponding backend services return only JSON-safe dictionaries/lists.
Identity normalization and candidate scoring remain in the business layer,
not the repository.

## Core Contracts

### Observed transaction features

Person 3 accepts computed transaction features from Person 2:

```json
{
  "entity_id": "COMP-000008",
  "window_start": "2025-12-20T10:00:00Z",
  "window_end": "2025-12-20T10:05:00Z",
  "account_ids": ["ACCT-SHB-002382"],
  "external_counterparty_ids": ["EXT-ACC-HR-001"],
  "metrics": {
    "total_inflow": 5000000000,
    "total_outflow": 4960000000,
    "transaction_count": 11,
    "cross_border_observed": true,
    "observed_countries": ["VN", "XX"]
  },
  "metric_evidence_ids": {
    "total_inflow": ["EV-TX-IN-001"],
    "total_outflow": ["EV-TX-OUT-001"],
    "cross_border_observed": ["EV-TX-XB-001"],
    "observed_countries": ["EV-TX-XB-001"]
  }
}
```

Person 3 does not reread transactions to recompute these metrics. Every metric
used in a finding must have at least one Person 2 evidence ID. The contract
`entity_id` must match the comparison subject, every `account_id` must be an
internal SHB account owned by that entity, and external IDs are used only for
the visibility summary.

### Evidence IDs

Person 3 source evidence IDs are deterministic:

```text
EV-ENTITY-{entity_id}
EV-KYC-{kyc_profile_id}
EV-DOC-{document_id}
EV-OWN-{ownership_id}
EV-REL-{relationship_id}
```

Transaction evidence IDs remain owned by Person 2. Derived findings reference
source evidence; they do not replace source evidence.

An exact duplicate evidence append is idempotent. Reusing an evidence ID with
different content is an `EvidenceConflictError`.

## KYC Snapshot Rules

`get_customer_kyc_snapshot(customer_id)` returns customer master data, address,
SHB accounts, profile expectations, KYC review dates, source of funds/wealth,
documents, completeness status, and `FULL_INTERNAL` visibility.

`resolve_account_owner(account_id)` resolves an internal SHB account to its
canonical customer/company owner and returns the corresponding bounded
snapshot. It rejects external account IDs and does not use fuzzy matching to
override core-banking ownership.

`get_company_profile(company_id)` returns company master data, accounts,
registered address, industry, turnover and flow expectations, cross-border
expectations, representative, direct shareholders, KYC documents, ownership
coverage/status, and `FULL_INTERNAL` visibility.

Retrieval does not calculate indirect UBOs. It reports missing profile or
master records explicitly rather than fabricating defaults.

## Document Intelligence Rules

Default required-document policy:

```text
CUSTOMER: NATIONAL_ID or PASSPORT
COMPANY: BUSINESS_LICENSE and UBO_DECLARATION
```

The policy is configurable. MVP uses existing `extracted_fields`; it performs
no OCR.

Validity classifications are `VALID`, `EXPIRED`, `NOT_YET_VALID`,
`UNVERIFIED`, and `INVALID_DATES`. Every expired document creates a finding.
However, a required type is not missing when another verified, nonexpired
document satisfies the same requirement.

Canonical comparisons:

| Document | Document value | Canonical field |
|---|---|---|
| `NATIONAL_ID`/`PASSPORT` | `full_name` | customer `full_name` |
| `NATIONAL_ID`/`PASSPORT` | `date_of_birth` | customer `date_of_birth` |
| `NATIONAL_ID` | `document_number` | customer `national_id` |
| `NATIONAL_ID`/`PASSPORT` | `nationality` | customer `nationality` |
| `BUSINESS_LICENSE` | `legal_name` | company `legal_name` |
| `BUSINESS_LICENSE` | `registration_number` | company `registration_number` |
| `BUSINESS_LICENSE` | `industry_code` | company `industry_code` |

Names are normalized before comparison. Missing extracted fields create
`DOCUMENT_FIELD_MISSING`; two conflicting present values create a contradiction
with both evidence IDs.

## Entity Resolution Rules

Resolution is logical and non-mutating. It returns ranked candidates and a
decision; it never rewrites entity IDs or repository rows.

Normalization covers Unicode/diacritics, whitespace, punctuation, aliases,
ISO dates, strong identifiers, phone digits/country code, lowercase email, and
address tokens. Display values remain unchanged.

Configurable default weights:

```text
strong identifier: 0.55
name or alias:      0.20
date of birth:      0.10
phone:              0.05
email:              0.05
address:            0.05
```

Decision thresholds are `MATCH >= 0.85`, `POSSIBLE_MATCH >= 0.35`, otherwise
`NO_MATCH`. A present conflicting national ID, passport, or registration
number forces `CONTRADICTION` regardless of soft-field score. A name-only match
never auto-resolves.

For external records, exact external account ID or masked account plus bank may
identify the same observed record, but output stays
`LIMITED_EXTERNAL_IDENTITY`; no KYC or UBO assertion follows.

## Ownership and UBO Rules

The repository stores `owner -> owned company`. The investigation output is
root-oriented as `company -> direct owner -> indirect owner`, while retaining
the original ownership ID and direction metadata.

For each path:

```text
cumulative percentage = product(direct percentages / 100) * 100
```

Verified contributions from independent paths to the same internal customer
are summed. The traversal stops at `max_depth`, a cycle, a missing upstream
owner, an unresolved-chain relationship, or an unverified edge.

`ownership_threshold=0.25` means 25 percent; output percentages are in the
range 0–100. A confirmed UBO requires:

- terminal node is an internal SHB customer;
- summed verified contribution meets the threshold;
- every contributing edge is verified;
- every contributing edge has valid supporting evidence;
- no broken/cyclic/unresolved segment is used in the percentage.

Unverified ownership is never used to promote a candidate over the UBO
threshold. It creates `UNVERIFIED_OWNERSHIP` and an ownership gap.

Ownership gaps include incomplete direct coverage, unverified edges, missing
support documents, missing upstream owners, unresolved-chain relationships,
max-depth truncation, and cycles. Repository integrity still rejects active
ownership totals over 100 percent; the pure UBO engine also validates supplied
graph fixtures defensively.

## Profile Mismatch Rules

Compare declared profile fields only with Person 2 metrics carrying evidence:

- `INFLOW_DEVIATION`;
- `OUTFLOW_DEVIATION`;
- `TURNOVER_DEVIATION`;
- `TRANSACTION_COUNT_DEVIATION`;
- `CROSS_BORDER_EXPECTATION_MISMATCH`;
- `UNEXPECTED_COUNTRY`.

For windows of at most 31 days, compare the absolute observed value with the
monthly declaration. A short burst is not prorated downward. For longer
windows, normalize the observed value to a 30-day rate.

Default ratio severity:

```text
ratio >= 10: CRITICAL
ratio >= 5:  HIGH
ratio >= 2:  MEDIUM
```

Observed cross-border activity when declared `false` is at least `HIGH`.
Every profile mismatch references at least one KYC evidence ID and the
metric-specific Person 2 evidence IDs. Missing metric evidence causes input
validation failure rather than an unsupported finding.

## Contradiction and Missing-Evidence Rules

Contradictions require two present, conflicting facts and distinct
`evidence_a`/`evidence_b` references. Additional supporting evidence may be
carried in `additional_evidence_ids`. Supported contradictions are master-versus-document,
document-versus-document, company-declaration-versus-KYC-profile, duplicate
strong identifiers across internal entities, and declared-UBO-versus-verified
ownership only when the document contains identifiable UBO data.

Absence is represented as missing evidence, not contradiction. Relationship
labels alone do not prove a UBO-document contradiction.

## Tool Boundary

Provide these backend-owned adapters:

```text
resolve_account_owner
get_customer_kyc_snapshot
get_company_profile
get_kyc_documents
extract_document_fields
check_document_validity
compare_kyc_fields
compare_profile_with_observed_behavior
normalize_identity
resolve_entity
build_ownership_graph
calculate_ubo
find_ownership_gaps
detect_kyc_contradictions
flag_unverified_ubo
```

The Orchestrator binds the current `case_id`; the LLM does not choose or mutate
it. Each adapter invokes a domain service, validates evidence references, and
atomically appends one `KycCaseContribution` to the Shared Case File before
returning the serialized result.

## Shared Case File Output

Person 3 contributes these append-only sections:

```text
normalized_entities
kyc_findings
profile_mismatches
ownership_graphs
identified_ubos
ownership_gaps
missing_documents
contradictions
evidence
visibility_summary
```

Finding and evidence IDs are deterministic so retries are idempotent. A tool
call with an invalid evidence reference appends nothing. State revision
increments only after a complete successful append.

Every appendable result has a stable ID: normalized entity resolution ID,
finding ID, mismatch ID, ownership graph ID, UBO result ID, gap ID, missing
document ID, contradiction ID, and evidence ID. Retries deduplicate every
section, not only evidence.

## Investigation Time Semantics

Date-sensitive investigation rules default to the Orchestrator's case
`as_of_date`. This applies to KYC completeness, active ownership, and UBO
traversal. `check_document_validity(document_ids, as_of_date)` additionally
supports an explicit historical validity query and records that date in its
result. Domain code never uses the server wall clock implicitly.

## Error Handling

- `EntityNotFoundError`: unknown entity/document/account.
- `EntityScopeViolationError`: external entity requested through internal-only
  KYC or UBO tool.
- `EvidenceContractError`: required source evidence is absent.
- `EvidenceConflictError`: an evidence ID is reused with different content.
- `OwnershipTraversalError`: invalid threshold/depth or structurally invalid
  supplied graph.
- Pydantic validation errors: malformed tool inputs.

Tool adapters convert domain exceptions into stable structured error codes and
do not partially mutate case state.

## Testing

Tests cover:

- complete customer/company snapshots and external scope rejection;
- expired document, valid replacement, missing document, invalid dates,
  missing extracted fields, and normalized field comparison;
- same-name/different-identifier contradiction, alias match, strong-ID match,
  name-only non-match, and limited external resolution;
- direct UBO, indirect cumulative UBO, multiple-path summation, threshold
  boundary, incomplete coverage, unverified edge, broken chain, max depth,
  cycle, and over-100 defensive validation;
- turnover, inflow/outflow, transaction-count, cross-border, and unexpected
  country mismatches with two-sided evidence;
- rejection when Person 2 metric evidence is absent;
- contradiction requiring two evidence records;
- idempotent case append, evidence conflict, invalid-reference rollback, and
  revision increment;
- main scenario integration for `COMP-000008`: verified KYC/UBO, expired old
  license plus valid replacement, and high turnover deviation;
- no ground-truth access and no Pandas/NetworkX objects in tool output.

## Scope Boundaries

This feature does not implement OCR, fuzzy embeddings, vector databases,
probabilistic record linkage, production document storage, LLM adjudication,
transaction feature calculation, sanctions screening, report drafting,
database persistence, or asynchronous workflow execution.
