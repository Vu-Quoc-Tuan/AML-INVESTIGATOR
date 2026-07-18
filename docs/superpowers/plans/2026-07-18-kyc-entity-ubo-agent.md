# KYC, Document Intelligence, Entity Resolution and UBO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Person 3 as deterministic, evidence-first KYC, document, entity-resolution, ownership/UBO, and profile-deviation capabilities that append validated JSON-safe contributions to the Shared Case File.

**Architecture:** Extend the Shared DataRepository only with bounded typed access, then implement small pure/domain services for each Person 3 responsibility. Backend-owned tool adapters run those services inside the current Orchestrator case context; evidence validation and Shared Case File append are atomic and idempotent.

**Tech Stack:** Python 3.11+, Pydantic 2, Pandas 2+, NetworkX 3+, pytest.

## Global Constraints

- Only SHB customers, companies, and accounts receive full KYC or UBO analysis.
- External counterparties remain `LIMITED_EXTERNAL_IDENTITY` and never receive inferred KYC/UBO data.
- Person 3 consumes `ObservedTransactionFeatures` from Person 2 and never recomputes transaction metrics.
- Every profile mismatch must reference KYC evidence and metric-specific transaction evidence.
- Every contradiction must reference at least two present conflicting evidence records.
- Unverified or broken ownership paths never produce confirmed UBO contribution.
- Repository remains a Data Access Layer; it contains no KYC/UBO business rules.
- Tool outputs contain no Pandas, NetworkX, repository, or mutable case-state objects.
- Ground truth is never loaded or referenced.
- No OCR, vector database, embeddings, LLM adjudication, or database persistence is introduced.
- Work in the current tree and do not commit unless the user explicitly requests a commit.

---

### Task 1: Person 3 Contracts, Configuration, and Domain Errors

**Files:**
- Create: `backend/app/schemas/kyc_entity.py`
- Modify: `backend/app/schemas/evidence.py`
- Create: `backend/app/kyc_entity/config.py`
- Create: `backend/app/kyc_entity/exceptions.py`
- Modify: `backend/app/kyc_entity/__init__.py`
- Test: `backend/tests/unit/kyc_entity/test_contracts.py`

**Interfaces:**
- Produces: `ObservedTransactionFeatures`, `KycEvidence`, `NormalizedEntity`, `KycFinding`, `ProfileMismatch`, `OwnershipNode`, `OwnershipEdge`, `OwnershipGraphResult`, `IdentifiedUbo`, `OwnershipGap`, `MissingDocument`, `Contradiction`, `VisibilitySummary`, `KycCaseContribution`, `KycEntityConfig`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_observed_metric_requires_metric_evidence():
    with pytest.raises(ValidationError):
        ObservedTransactionFeatures(
            entity_id="COMP-000008",
            window_start="2025-12-20T10:00:00Z",
            window_end="2025-12-20T10:05:00Z",
            account_ids=["ACCT-SHB-002382"],
            external_counterparty_ids=[],
            metrics={"total_inflow": 5_000_000_000},
            metric_evidence_ids={},
        )


def test_contradiction_requires_two_distinct_evidence_ids():
    with pytest.raises(ValidationError):
        Contradiction(
            contradiction_id="CONTRA-1",
            type="DOCUMENT_FIELD_MISMATCH",
            field="full_name",
            declared="A",
            observed="B",
            evidence_a="EV-DOC-1",
            evidence_b="EV-DOC-1",
        )
```

- [ ] **Step 2: Run the tests and confirm missing contracts fail**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_contracts.py -q`

Expected: collection/import failure because `app.schemas.kyc_entity` does not exist.

- [ ] **Step 3: Implement strict Pydantic models**

Use this central shape:

```python
class ObservedTransactionFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    window_start: datetime
    window_end: datetime
    account_ids: list[str]
    external_counterparty_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | bool | list[str]]
    metric_evidence_ids: dict[str, list[str]]

    @model_validator(mode="after")
    def validate_metric_evidence(self):
        if self.window_end < self.window_start:
            raise ValueError("window_end must not precede window_start")
        missing = [
            metric for metric in self.metrics
            if not self.metric_evidence_ids.get(metric)
        ]
        if missing:
            raise ValueError(f"metrics missing evidence: {sorted(missing)}")
        return self
```

`KycCaseContribution` contains append-only lists for the output sections in the
spec and defaults each list with `Field(default_factory=list)`. Every item model
defines its stable deterministic ID used for section-level retry deduplication.

- [ ] **Step 4: Implement immutable configuration and exceptions**

```python
@dataclass(frozen=True, slots=True)
class KycEntityConfig:
    ownership_threshold: float = 0.25
    max_ownership_depth: int = 3
    identity_match_threshold: float = 0.85
    identity_possible_threshold: float = 0.35
    deviation_medium_ratio: float = 2.0
    deviation_high_ratio: float = 5.0
    deviation_critical_ratio: float = 10.0
    required_documents: Mapping[str, Sequence[frozenset[str]]] = field(
        default_factory=lambda: {
            "CUSTOMER": (frozenset({"NATIONAL_ID", "PASSPORT"}),),
            "COMPANY": (
                frozenset({"BUSINESS_LICENSE"}),
                frozenset({"UBO_DECLARATION"}),
            ),
        }
    )
```

Add `EntityNotFoundError`, `EntityScopeViolationError`,
`EvidenceContractError`, `EvidenceConflictError`, and
`OwnershipTraversalError`.

- [ ] **Step 5: Run contract tests**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_contracts.py -q`

Expected: all Task 1 tests pass.

### Task 2: Bounded Repository and Data-Service Extensions

**Files:**
- Modify: `backend/app/data/repository.py`
- Modify: `backend/app/services/entity_data_service.py`
- Modify: `backend/app/services/ownership_data_service.py`
- Test: `backend/tests/unit/data/test_kyc_repository_queries.py`

**Interfaces:**
- Produces: `DataRepository.accounts_for_entity`, `address_by_id`, `kyc_document_by_id`, `entities_by_strong_identifier`, `build_ownership_neighborhood`; JSON-safe service equivalents.
- Consumes: existing cached DataRepository lifecycle and serialization helpers.

- [ ] **Step 1: Write failing typed-query tests**

```python
def test_accounts_for_entity_returns_only_owner_accounts(repository):
    rows = repository.accounts_for_entity("COMP-000008")
    assert set(rows["owner_entity_id"]) == {"COMP-000008"}
    rows.loc[:, "status"] = "MUTATED"
    assert "MUTATED" not in set(repository.accounts_for_entity("COMP-000008")["status"])


def test_ownership_neighborhood_is_rooted_and_depth_bounded(repository):
    graph = repository.build_ownership_neighborhood(
        "COMP-000005", as_of_date="2025-12-31", max_depth=2
    )
    assert graph.graph["root_company_id"] == "COMP-000005"
    assert graph.graph["max_depth"] == 2
    assert nx.single_source_shortest_path_length(graph, "COMP-000005", cutoff=2)
```

- [ ] **Step 2: Confirm tests fail on missing methods**

Run: `cd backend && .venv/bin/pytest tests/unit/data/test_kyc_repository_queries.py -q`

Expected: `AttributeError` for the new typed methods.

- [ ] **Step 3: Add defensive typed row queries**

Implement:

```python
def accounts_for_entity(self, entity_id: str) -> pd.DataFrame:
    return self._rows_equal("accounts", "owner_entity_id", entity_id)

def address_by_id(self, address_id: str) -> pd.Series | None:
    return self._series_by_id("addresses", "address_id", address_id)

def kyc_document_by_id(self, document_id: str) -> pd.Series | None:
    return self._series_by_id("kyc_documents", "document_id", document_id)
```

`entities_by_strong_identifier()` supports only `NATIONAL_ID` and
`REGISTRATION_NUMBER`; unknown identifier types raise `ValueError`. It returns
bounded matching customer/company rows with an added `entity_type` field.

- [ ] **Step 4: Add bounded root-oriented ownership neighborhood**

Build from the fresh active ownership graph without exposing it. Starting at
the root company, traverse incoming `owner -> company` edges and emit a new
`company -> owner` `nx.DiGraph`. Reject `max_depth < 1`; include graph metadata
`root_company_id`, `as_of_date`, `max_depth`, and cycle flags.

- [ ] **Step 5: Add JSON-safe service methods**

```python
class EntityDataService:
    def accounts_for_entity(self, entity_id: str) -> list[dict[str, object]]:
        return frame_to_records(
            get_initialized_data_repository().accounts_for_entity(entity_id)
        )

    def address(self, address_id: str) -> dict[str, object] | None:
        return series_to_dict(
            get_initialized_data_repository().address_by_id(address_id)
        )

    def kyc_document(self, document_id: str) -> dict[str, object] | None:
        return series_to_dict(
            get_initialized_data_repository().kyc_document_by_id(document_id)
        )

    def entities_by_strong_identifier(
        self, identifier_type: str, identifier_value: str
    ) -> list[dict[str, object]]:
        return frame_to_records(
            get_initialized_data_repository().entities_by_strong_identifier(
                identifier_type, identifier_value
            )
        )

class OwnershipDataService:
    def ownership_neighborhood(
        self, company_id: str, as_of_date: str | date | datetime, max_depth: int
    ) -> dict[str, object]:
        return graph_to_dict(
            get_initialized_data_repository().build_ownership_neighborhood(
                company_id, as_of_date, max_depth
            )
        )
```

- [ ] **Step 6: Run existing and new data-layer tests**

Run: `cd backend && .venv/bin/pytest tests/unit/data -q`

Expected: all data-layer tests pass; no full graph or generic DataFrame getter is introduced.

### Task 3: Evidence Ledger and Atomic Shared Case File Append

**Files:**
- Modify: `backend/app/schemas/state.py`
- Modify: `backend/app/investigation_orchestrator/evidence_ledger.py`
- Modify: `backend/app/investigation_orchestrator/evidence_validator.py`
- Modify: `backend/app/investigation_orchestrator/state.py`
- Create: `backend/app/investigation_orchestrator/case_store.py`
- Test: `backend/tests/unit/investigation_orchestrator/test_kyc_case_append.py`

**Interfaces:**
- Produces: `SharedCaseFile`, `EvidenceLedger.append_many`, `validate_contribution_evidence`, `append_kyc_contribution`, `CaseStateStore`, and `InMemoryCaseStateStore`.
- Consumes: `KycCaseContribution` and `KycEvidence` from Task 1.

- [ ] **Step 1: Write atomicity and idempotency tests**

```python
def test_exact_evidence_retry_is_idempotent(empty_case):
    contribution = contribution_with_evidence("EV-KYC-1")
    once = append_kyc_contribution(empty_case, contribution)
    twice = append_kyc_contribution(once, contribution)
    assert len(twice.evidence) == 1
    assert twice.revision == 1


def test_invalid_reference_rolls_back_entire_append(empty_case):
    contribution = contribution_referencing("EV-MISSING")
    with pytest.raises(EvidenceContractError):
        append_kyc_contribution(empty_case, contribution)
    assert empty_case.revision == 0
    assert empty_case.kyc_findings == []
```

- [ ] **Step 2: Confirm tests fail against empty Orchestrator modules**

Run: `cd backend && .venv/bin/pytest tests/unit/investigation_orchestrator/test_kyc_case_append.py -q`

Expected: import failure for Shared Case File functions.

- [ ] **Step 3: Implement append-only state**

```python
class SharedCaseFile(BaseModel):
    case_id: str
    revision: int = 0
    normalized_entities: list[NormalizedEntity] = Field(default_factory=list)
    kyc_findings: list[KycFinding] = Field(default_factory=list)
    profile_mismatches: list[ProfileMismatch] = Field(default_factory=list)
    ownership_graphs: list[OwnershipGraphResult] = Field(default_factory=list)
    identified_ubos: list[IdentifiedUbo] = Field(default_factory=list)
    ownership_gaps: list[OwnershipGap] = Field(default_factory=list)
    missing_documents: list[MissingDocument] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    evidence: list[KycEvidence] = Field(default_factory=list)
    visibility_summary: VisibilitySummary = Field(default_factory=VisibilitySummary)
```

- [ ] **Step 4: Validate before copying/appending**

Collect all `evidence_ids` referenced by findings, mismatches, UBOs, and gaps,
plus every contradiction's `evidence_a`, `evidence_b`, and
`additional_evidence_ids`. The allowed set is existing ledger IDs plus incoming evidence
IDs. Reject missing IDs and conflicting duplicate content before constructing a
new state object. Deduplicate every section by its stable deterministic ID and
merge visibility lists as sorted unique IDs.

- [ ] **Step 5: Implement a revision-checked MVP case store**

`CaseStateStore` defines `get(case_id)` and
`replace(case_id, expected_revision, new_state)`. `InMemoryCaseStateStore` uses
a lock, returns deep copies, and rejects stale revisions. This is process-local
orchestration state, not database persistence.

- [ ] **Step 6: Run Orchestrator append tests**

Run: `cd backend && .venv/bin/pytest tests/unit/investigation_orchestrator/test_kyc_case_append.py -q`

Expected: exact retries are no-ops, conflicts fail, invalid references roll back, and successful novel contributions increment revision once.

### Task 4: Internal KYC Snapshots and External Scope Enforcement

**Files:**
- Modify: `backend/app/kyc_entity/kyc_service.py`
- Test: `backend/tests/unit/kyc_entity/test_kyc_service.py`

**Interfaces:**
- Produces: `KycSnapshotService.resolve_account_owner(account_id, as_of_date)`, `get_customer_kyc_snapshot(customer_id, as_of_date)`, and `get_company_profile(company_id, as_of_date)`.
- Consumes: `EntityDataService`, `OwnershipDataService`, Task 1 contracts/config.

- [ ] **Step 1: Write customer, company, and external-scope tests**

```python
def test_company_profile_contains_declared_and_direct_ownership(services):
    result = services.get_company_profile("COMP-000008", date(2025, 12, 20))
    assert result.entity["expected_monthly_turnover"] == 300_000_000
    assert result.kyc_profile["expected_monthly_inflow"] == 300_000_000
    assert result.representative["customer_id"] == "CUST-001690"
    assert sum(owner["ownership_percentage"] for owner in result.direct_owners) == 100.0


def test_external_account_cannot_receive_full_kyc_snapshot(services):
    with pytest.raises(EntityScopeViolationError):
        services.get_customer_kyc_snapshot("EXT-ACC-000001", date(2025, 12, 20))


def test_internal_account_resolves_canonical_company_owner(services):
    result = services.resolve_account_owner("ACCT-SHB-002382", date(2025, 12, 20))
    assert result.owner_entity_id == "COMP-000008"
    assert result.owner_entity_type == "COMPANY"
```

- [ ] **Step 2: Confirm failures before implementation**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_kyc_service.py -q`

Expected: missing `KycSnapshotService` methods.

- [ ] **Step 3: Implement customer snapshot assembly**

Resolve customer, address, accounts, KYC profile, and documents through data
services. Emit source evidence for entity/profile/documents. Unknown internal ID
raises `EntityNotFoundError`; `EXT-ACC-*` raises `EntityScopeViolationError`.

Implement `resolve_account_owner()` by exact account lookup followed by exact
`owner_entity_id` retrieval. Fuzzy identity matching never changes the owner
recorded by SHB core banking.

- [ ] **Step 4: Implement company profile assembly**

Resolve company, address, accounts, profile, representative, direct ownership
records, documents, and ownership coverage. Retrieval reports missing pieces;
it does not run indirect UBO traversal.

- [ ] **Step 5: Run snapshot tests**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_kyc_service.py -q`

Expected: internal snapshots are complete and external IDs are rejected.

### Task 5: Document Intelligence MVP

**Files:**
- Modify: `backend/app/kyc_entity/document_intelligence.py`
- Test: `backend/tests/unit/kyc_entity/test_document_intelligence.py`

**Interfaces:**
- Produces: `extract_document_fields`, `check_document_validity`, `compare_kyc_fields`, `find_missing_documents` methods on `DocumentIntelligenceService`.
- Consumes: snapshot service, entity data service, Task 1 contracts/config.

- [ ] **Step 1: Write document rule tests**

```python
def test_expired_license_with_valid_replacement_is_not_missing(service):
    result = service.compare_kyc_fields("COMP-000008", as_of_date=date(2025, 12, 20))
    assert any(f.type == "DOCUMENT_EXPIRED" and "DOC-002015" in f.evidence_ids for f in result.findings)
    assert not any(m.type == "BUSINESS_LICENSE" for m in result.missing_documents)


def test_same_name_but_different_document_identifier_is_contradiction(service):
    result = service.compare_documents(entity_fixture_with_conflicting_ids())
    contradiction = next(c for c in result.contradictions if c.field == "national_id")
    assert contradiction.evidence_a != contradiction.evidence_b
```

- [ ] **Step 2: Confirm tests fail before rules exist**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_document_intelligence.py -q`

Expected: missing methods or empty results.

- [ ] **Step 3: Implement extraction and validity classification**

Return stored `extracted_fields` with document evidence. Classify dates/status
as `VALID`, `EXPIRED`, `NOT_YET_VALID`, `UNVERIFIED`, or `INVALID_DATES` using
the caller's `as_of_date`.

- [ ] **Step 4: Implement required-document satisfaction**

For each configured alternative group, consider it satisfied when at least one
document type in the group is verified, issued, and nonexpired. Findings for
other expired documents remain present.

- [ ] **Step 5: Implement canonical and cross-document comparison**

Use normalized names/dates/identifiers. Present disagreement creates a
two-evidence contradiction; absent fields create `DOCUMENT_FIELD_MISSING` and
do not create contradictions.

- [ ] **Step 6: Run document tests**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_document_intelligence.py -q`

Expected: all validity, replacement, extraction, and contradiction cases pass.

### Task 6: Deterministic Identity Normalization and Resolution

**Files:**
- Create: `backend/app/kyc_entity/normalization.py`
- Modify: `backend/app/kyc_entity/entity_resolution.py`
- Test: `backend/tests/unit/kyc_entity/test_entity_resolution.py`

**Interfaces:**
- Produces: `normalize_identity(raw_identity) -> NormalizedIdentity` and `resolve_entity(input_entity, candidate_entities) -> EntityResolutionResult`.
- Consumes: identity weights/thresholds from `KycEntityConfig`.

- [ ] **Step 1: Write normalization and resolution tests**

```python
def test_alias_plus_dob_and_phone_resolves_candidate(resolver):
    input_entity = {"full_name": "NGUYEN VAN AN", "date_of_birth": "1990-01-01", "phone": "+84901234567"}
    candidate = {"entity_id": "CUST-1", "full_name": "Nguyễn Văn Bình", "aliases": ["Nguyen Van An"], "date_of_birth": "1990-01-01", "phone": "0901234567"}
    result = resolver.resolve_entity(input_entity, [candidate])
    assert result.candidates[0].decision in {"MATCH", "POSSIBLE_MATCH"}


def test_same_name_with_conflicting_national_id_never_merges(resolver):
    result = resolver.resolve_entity(
        {"full_name": "Tran Van A", "national_id": "111"},
        [{"entity_id": "CUST-2", "full_name": "Trần Văn A", "national_id": "222"}],
    )
    assert result.candidates[0].decision == "CONTRADICTION"
```

- [ ] **Step 2: Confirm tests fail before implementation**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_entity_resolution.py -q`

Expected: missing normalizer/resolver behavior.

- [ ] **Step 3: Implement pure normalization**

Normalize names with NFKD/diacritic removal for comparison, preserve display
name, normalize aliases as a set, dates as ISO strings, phone as digits with VN
country normalization, email lowercase, identifiers uppercase/alphanumeric,
and addresses as sorted tokens.

- [ ] **Step 4: Implement weighted scoring with hard conflicts**

Use weights from Task 1. A present conflicting strong identifier returns
`CONTRADICTION` before soft scoring. Name-only score is capped below
`POSSIBLE_MATCH`. Return per-field explanations and deterministic ordering by
descending score then entity ID.

- [ ] **Step 5: Implement external resolution semantics**

Exact external account ID or masked account plus bank can return
`EXTERNAL_ACCOUNT_RECORD_MATCH`, but the candidate output must retain
`LIMITED_EXTERNAL_IDENTITY` and `ubo_eligible=false`.

- [ ] **Step 6: Run identity tests**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_entity_resolution.py -q`

Expected: alias, strong-ID, contradiction, name-only, ordering, and limited-external tests pass.

### Task 7: Ownership Graph Traversal and UBO Calculation

**Files:**
- Modify: `backend/app/kyc_entity/ownership_ubo.py`
- Test: `backend/tests/unit/kyc_entity/test_ownership_ubo.py`

**Interfaces:**
- Produces: `build_ownership_graph(company_id, as_of_date, max_depth)`, `calculate_ubo`, `find_ownership_gaps`, and `flag_unverified_ubo` on `OwnershipUboService`.
- Consumes: bounded ownership neighborhood, entity/document services, config, evidence contracts.

- [ ] **Step 1: Write direct, indirect, and multiple-path tests**

```python
def test_indirect_ubo_multiplies_path_percentages(engine):
    graph = ownership_fixture([
        ("TARGET", "COMP-A", 50.0, True),
        ("COMP-A", "CUST-A", 60.0, True),
    ])
    result = engine.calculate_ubo(graph, ownership_threshold=0.25)
    assert result.identified_ubos[0].ubo_id == "CUST-A"
    assert result.identified_ubos[0].ownership_percentage == 30.0


def test_unverified_path_does_not_create_confirmed_ubo(engine):
    graph = ownership_fixture([("TARGET", "CUST-A", 80.0, False)])
    result = engine.calculate_ubo(graph, ownership_threshold=0.25)
    assert result.identified_ubos == []
    assert any(g.type == "UNVERIFIED_OWNERSHIP" for g in result.ownership_gaps)
```

- [ ] **Step 2: Add failure tests for cycles, max depth, broken chain, incomplete coverage, and over 100 percent**

The cycle test must terminate and emit `OWNERSHIP_CYCLE`; the over-100 pure
fixture must raise `OwnershipTraversalError` even though production repository
would reject that dataset at startup.

- [ ] **Step 3: Confirm ownership tests fail**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_ownership_ubo.py -q`

Expected: missing traversal/calculation methods.

- [ ] **Step 4: Build evidence-rich root-oriented graph**

Call `OwnershipDataService.ownership_neighborhood()` using the bound case
`as_of_date`, enrich nodes with bounded
entity identity, and enrich every edge with ownership/document evidence. Stop
external IDs with `EntityScopeViolationError`.

- [ ] **Step 5: Implement path-safe cumulative calculation**

Use path-local visited sets. Multiply direct percentages along each verified
path, sum independent verified contributions by terminal customer, and retain
each contributing path. Validate `0 < threshold <= 1` and `max_depth >= 1`.

- [ ] **Step 6: Implement ownership-gap rules**

Emit gaps for coverage below 100, unverified edge, missing document, company
owner without upstream owners, unresolved relationship, depth cutoff, and
cycle. `flag_unverified_ubo` returns findings referencing ownership evidence.

- [ ] **Step 7: Run ownership tests**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_ownership_ubo.py -q`

Expected: all direct/indirect/multiple-path/threshold/gap tests pass.

### Task 8: Declared Profile versus Person 2 Observed Features

**Files:**
- Modify: `backend/app/kyc_entity/profile_deviation.py`
- Test: `backend/tests/unit/kyc_entity/test_profile_deviation.py`

**Interfaces:**
- Produces: `ProfileDeviationService.compare_profile_with_observed_behavior(entity_id, observed_transaction_features, as_of_date)`.
- Consumes: Task 1 observed contract, KYC snapshot service, evidence model/config.

- [ ] **Step 1: Write two-sided evidence tests**

```python
def test_turnover_deviation_has_kyc_and_transaction_evidence(service):
    observed = observed_features(
        entity_id="COMP-000008",
        total_inflow=5_000_000_000,
        evidence_id="EV-TX-IN-001",
    )
    result = service.compare_profile_with_observed_behavior(
        "COMP-000008", observed, date(2025, 12, 20)
    )
    finding = next(item for item in result if item.type == "TURNOVER_DEVIATION")
    assert finding.severity == "CRITICAL"
    assert "EV-KYC-KYC-002008" in finding.evidence_ids
    assert "EV-TX-IN-001" in finding.evidence_ids


def test_observed_subject_and_accounts_must_match(service):
    observed = observed_features(entity_id="COMP-OTHER", account_ids=["ACCT-SHB-002382"])
    with pytest.raises(EvidenceContractError):
        service.compare_profile_with_observed_behavior(
            "COMP-000008", observed, date(2025, 12, 20)
        )
```

- [ ] **Step 2: Write cross-border, country, transaction-count, long-window, and missing-evidence tests**

Cross-border mismatch uses a fixture whose declared value is `false`; do not
assert this mismatch for `COMP-000008`, whose checked-in profile declares
cross-border activity.

- [ ] **Step 3: Confirm tests fail before implementation**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_profile_deviation.py -q`

Expected: missing comparison behavior.

- [ ] **Step 4: Implement window and ratio calculations**

For `window <= 31 days`, compare absolute observed values. For longer windows,
use `observed * 30 / window_days`. Map ratio bands exactly from configuration.

- [ ] **Step 5: Implement mismatch rules and evidence enforcement**

Compare inflow, outflow, company turnover, transaction count, cross-border, and
countries. Reject any metric used by a rule when its metric-specific evidence
list is empty. Verify the observed subject ID and ownership of every supplied
SHB account without reading transaction rows. Treat supplied external IDs only
as `LIMITED_EXTERNAL_IDENTITY` visibility entries. Do not query transaction data.

- [ ] **Step 6: Run profile-deviation tests**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_profile_deviation.py -q`

Expected: all mismatch and evidence-provenance tests pass.

### Task 9: Cross-Source Contradictions, Missing Evidence, and Facade

**Files:**
- Create: `backend/app/kyc_entity/contradiction_detection.py`
- Create: `backend/app/kyc_entity/facade.py`
- Test: `backend/tests/unit/kyc_entity/test_contradiction_detection.py`
- Test: `backend/tests/unit/kyc_entity/test_facade.py`

**Interfaces:**
- Produces: `ContradictionService.detect_kyc_contradictions(entity_id, as_of_date)`, `KycEntityFacade` methods matching every requested tool operation plus exact account-owner retrieval.
- Consumes: Tasks 4–8 services and Task 1 contracts.

- [ ] **Step 1: Write contradiction semantics tests**

```python
def test_absence_is_missing_evidence_not_contradiction(service):
    result = service.detect_kyc_contradictions(
        "COMP-WITHOUT-UBO-DOC", date(2025, 12, 20)
    )
    assert result.contradictions == []
    assert any(item.type == "UBO_DECLARATION" for item in result.missing_documents)


def test_present_conflicting_values_require_both_sources(service):
    result = service.detect_kyc_contradictions(
        "CUST-CONFLICT", date(2025, 12, 20)
    )
    item = next(c for c in result.contradictions if c.field == "date_of_birth")
    assert item.evidence_a != item.evidence_b
```

- [ ] **Step 2: Implement supported contradiction rules**

Combine master/document, document/document, declaration/profile, duplicate
strong-ID, and identifiable declared-UBO/verified-ownership conflicts. Do not
interpret relationship labels alone as documentary proof.

- [ ] **Step 3: Implement a thin facade**

Expose the exact requested operations and delegate without duplicating rules:

```python
class KycEntityFacade:
    def resolve_account_owner(self, account_id: str, as_of_date: date):
        return self.snapshot_service.resolve_account_owner(account_id, as_of_date)

    def get_customer_kyc_snapshot(self, customer_id: str, as_of_date: date):
        return self.snapshot_service.get_customer_kyc_snapshot(
            customer_id, as_of_date
        )

    def get_company_profile(self, company_id: str, as_of_date: date):
        return self.snapshot_service.get_company_profile(company_id, as_of_date)

    def get_kyc_documents(self, entity_id: str):
        return self.document_service.get_kyc_documents(entity_id)

    def extract_document_fields(self, document_id: str):
        return self.document_service.extract_document_fields(document_id)

    def check_document_validity(self, document_ids: list[str], as_of_date: date):
        return self.document_service.check_document_validity(document_ids, as_of_date)

    def compare_kyc_fields(self, entity_id: str, as_of_date: date):
        return self.document_service.compare_kyc_fields(entity_id, as_of_date)

    def compare_profile_with_observed_behavior(
        self,
        entity_id: str,
        observed: ObservedTransactionFeatures,
        as_of_date: date,
    ):
        return self.profile_service.compare_profile_with_observed_behavior(
            entity_id, observed, as_of_date
        )

    def normalize_identity(self, raw_identity: dict[str, object]):
        return self.resolution_service.normalize_identity(raw_identity)

    def resolve_entity(
        self,
        input_entity: dict[str, object],
        candidate_entities: list[dict[str, object]],
    ):
        return self.resolution_service.resolve_entity(
            input_entity, candidate_entities
        )

    def build_ownership_graph(
        self, company_id: str, as_of_date: date, max_depth: int = 3
    ):
        return self.ownership_service.build_ownership_graph(
            company_id, as_of_date, max_depth
        )

    def calculate_ubo(
        self,
        ownership_graph: OwnershipGraphResult,
        ownership_threshold: float = 0.25,
    ):
        return self.ownership_service.calculate_ubo(
            ownership_graph, ownership_threshold
        )

    def find_ownership_gaps(self, ownership_graph: OwnershipGraphResult):
        return self.ownership_service.find_ownership_gaps(ownership_graph)

    def detect_kyc_contradictions(self, entity_id: str, as_of_date: date):
        return self.contradiction_service.detect_kyc_contradictions(
            entity_id, as_of_date
        )

    def flag_unverified_ubo(self, company_id: str, as_of_date: date):
        return self.ownership_service.flag_unverified_ubo(
            company_id, as_of_date
        )
```

- [ ] **Step 4: Ensure every facade result is a typed contribution or typed domain result**

No facade method returns Pandas, NetworkX, repository objects, or unvalidated
arbitrary dictionaries.

- [ ] **Step 5: Run contradiction and facade tests**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity/test_contradiction_detection.py tests/unit/kyc_entity/test_facade.py -q`

Expected: all Task 9 tests pass.

### Task 10: Backend-Owned Tool Adapters and Orchestrator Binding

**Files:**
- Modify: `backend/app/schemas/tools.py`
- Modify: `backend/app/investigation_orchestrator/tool_registry.py`
- Modify: `backend/app/investigation_orchestrator/state.py`
- Test: `backend/tests/unit/investigation_orchestrator/test_kyc_tools.py`

**Interfaces:**
- Produces: `KycToolContext`, registry entries for all requested tools, and atomic invoke/append behavior.
- Consumes: `KycEntityFacade`, `append_kyc_contribution`, current case context.

- [ ] **Step 1: Write case-binding and serialization tests**

```python
def test_tool_uses_bound_case_id_and_appends_before_return(registry, case_store):
    context = KycToolContext(case_id="CASE-1", as_of_date=date(2025, 12, 20))
    result = registry.invoke("get_company_profile", {"company_id": "COMP-000008"}, context)
    assert result["status"] == "ok"
    assert case_store.get("CASE-1").revision == 1
    json.dumps(result, allow_nan=False)


def test_scope_error_does_not_mutate_case(registry, case_store):
    before = case_store.get("CASE-1").model_copy(deep=True)
    result = registry.invoke("build_ownership_graph", {"company_id": "EXT-ACC-000001"}, context)
    assert result["error"]["code"] == "ENTITY_SCOPE_VIOLATION"
    assert case_store.get("CASE-1") == before
```

- [ ] **Step 2: Define strict tool input schemas**

Each tool input uses `extra="forbid"`. The `case_id` is absent from LLM-visible
input and supplied only by `KycToolContext`. KYC completeness and ownership
traversal use the context `as_of_date`. The explicit
`check_document_validity.as_of_date` input is allowed for historical queries
and is preserved in the result. No rule uses wall-clock time implicitly.

- [ ] **Step 3: Register all requested Person 3 tools**

Registry adapters validate input, invoke one facade method, create a
`KycCaseContribution`, validate/append atomically, then serialize the return.
Normalize domain exceptions into stable codes without exposing stack traces.

- [ ] **Step 4: Verify no direct repository use in tool modules**

Run: `rg -n "DataRepository|get_initialized_data_repository|pandas|networkx" backend/app/investigation_orchestrator backend/app/kyc_entity`

Expected: repository/provider imports appear only in backend data services;
`kyc_entity` and tool adapters do not import them.

- [ ] **Step 5: Run tool adapter tests**

Run: `cd backend && .venv/bin/pytest tests/unit/investigation_orchestrator/test_kyc_tools.py -q`

Expected: successful tools append, failed tools do not mutate, retries are idempotent, and all output is strict JSON.

### Task 11: Main Scenario and Full Regression Verification

**Files:**
- Create: `backend/tests/integration/test_kyc_entity_main_scenario.py`
- Verify: all Task 1–10 files and existing backend tests.

**Interfaces:**
- Consumes: initialized checked-in SHB-centric data, tool registry, Shared Case File.
- Produces: end-to-end evidence that Person 3 meets the scenario and business rules.

- [ ] **Step 1: Write main scenario integration test**

```python
def test_main_company_kyc_ubo_and_turnover_case(initialized_backend, registry):
    context = KycToolContext(case_id="CASE-MAIN", as_of_date=date(2025, 12, 20))
    profile = registry.invoke("get_company_profile", {"company_id": "COMP-000008"}, context)
    ownership = registry.invoke("build_ownership_graph", {"company_id": "COMP-000008", "max_depth": 3}, context)
    ubo = registry.invoke(
        "calculate_ubo",
        {
            "ownership_graph": ownership["result"]["ownership_graph"],
            "ownership_threshold": 0.25,
        },
        context,
    )
    mismatch = registry.invoke(
        "compare_profile_with_observed_behavior",
        {
            "entity_id": "COMP-000008",
            "observed_transaction_features": main_observed_features(),
        },
        context,
    )
    assert profile["status"] == "ok"
    assert any(item["verified"] for item in ubo["result"]["identified_ubos"])
    assert any(item["type"] == "TURNOVER_DEVIATION" for item in mismatch["result"]["profile_mismatches"])
    assert not any(item["type"] == "CROSS_BORDER_EXPECTATION_MISMATCH" for item in mismatch["result"]["profile_mismatches"])
```

- [ ] **Step 2: Assert real document replacement semantics**

For `COMP-000008`, assert `DOC-002015` produces `DOCUMENT_EXPIRED`, while valid
`DOC-002097` prevents `BUSINESS_LICENSE` from appearing in missing documents.

- [ ] **Step 3: Assert final Shared Case File evidence integrity**

Every referenced evidence ID must exist in the case ledger. Visibility summary
contains `COMP-000008` as internal and any external transaction context only as
limited external. Serialize with
`json.dumps(case.model_dump(mode="json"), allow_nan=False)`.

- [ ] **Step 4: Run Person 3 tests**

Run: `cd backend && .venv/bin/pytest tests/unit/kyc_entity tests/unit/investigation_orchestrator tests/integration/test_kyc_entity_main_scenario.py -q`

Expected: all Person 3 unit and integration tests pass.

- [ ] **Step 5: Run the complete backend suite**

Run: `cd backend && .venv/bin/pytest -q`

Expected: all existing data/generator tests and new Person 3 tests pass.

- [ ] **Step 6: Verify syntax and diff hygiene**

Run: `cd backend && .venv/bin/python -m compileall -q app tests`

Expected: exit code 0 with no output.

Run: `git diff --check`

Expected: exit code 0 with no whitespace errors.

- [ ] **Step 7: Review the implementation boundary**

Run: `rg -n "ground_truth|get_dataframe|get_graph|watchlist_entries\(" backend/app/kyc_entity backend/app/investigation_orchestrator backend/app/schemas`

Expected: no ground-truth access, generic repository access, raw graph access,
or full-watchlist access in Person 3 code.
