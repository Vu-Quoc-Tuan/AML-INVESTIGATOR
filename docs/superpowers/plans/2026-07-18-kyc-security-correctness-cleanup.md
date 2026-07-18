# KYC Security, Correctness, and Safe Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five confirmed KYC/orchestrator defects, add regression coverage, and remove only demonstrably dead private code, unused imports/constants, and redundant `.gitkeep` files.

**Architecture:** Preserve current tool payload contracts while moving trust decisions to backend-owned state. Downstream ownership tools must use an exact graph already stored in the bound Shared Case File; identity scope is derived from record markers; ownership completeness is calculated for every reachable company; lifecycle and revision errors receive distinct codes.

**Tech Stack:** Python 3.11+, Pydantic 2, Pandas 2+, NetworkX 3+, pytest.

## Global Constraints

- Work in the current dirty tree and preserve all unrelated user changes.
- Do not commit, stage, push, or create a PR unless the user explicitly requests it.
- Do not remove the 82 roadmap/scaffold placeholder files.
- Do not remove empty `__init__.py` files, generated data, or public helpers whose external use cannot be disproved.
- Keep all current tool names and request payload schemas compatible.
- No test or cleanup command may rewrite `backend/data/generated`.
- Use `PYTHONDONTWRITEBYTECODE=1` and disable the pytest cache provider.

---

### Task 1: Bind Downstream UBO Tools to Stored Graphs

**Files:**
- Modify: `backend/app/investigation_orchestrator/tool_registry.py:7-152`
- Modify: `backend/app/kyc_entity/ownership_ubo.py:139-155`
- Test: `backend/tests/unit/investigation_orchestrator/test_kyc_tools.py`
- Test: `backend/tests/unit/kyc_entity/test_ownership_ubo.py`

**Interfaces:**
- Consumes: `KycToolContext.case_id`, `CaseStateStore.get(case_id)`, `OwnershipGraphResult.graph_id`.
- Produces: `KycToolRegistry._stored_ownership_graph(graph, context) -> OwnershipGraphResult`; verified edges require evidence IDs.

- [ ] **Step 1: Add failing registry tests**

Add tests proving a fabricated graph and a modified stored graph return `EVIDENCE_CONTRACT_ERROR` without changing the case, while the exact graph returned by `build_ownership_graph` remains accepted:

```python
def test_calculate_ubo_rejects_graph_not_stored_in_bound_case():
    registry = KycToolRegistry()
    context = KycToolContext(case_id="CASE-FABRICATED", as_of_date=date(2025, 12, 20))
    graph = {
        "graph_id": "CALLER-SUPPLIED",
        "root_company_id": "COMP-FAKE",
        "as_of_date": "2025-12-20",
        "max_depth": 3,
        "nodes": [
            {"node_id": "COMP-FAKE", "entity_type": "COMPANY"},
            {"node_id": "CUST-FAKE", "entity_type": "CUSTOMER"},
        ],
        "edges": [{
            "ownership_id": "OWN-FAKE",
            "owned_company_id": "COMP-FAKE",
            "owner_entity_id": "CUST-FAKE",
            "owner_entity_type": "CUSTOMER",
            "direct_percentage": 100,
            "verified": True,
        }],
        "ownership_coverage_percentage": 100,
        "ownership_status": "COMPLETE",
    }
    before = registry.case_store.get(context.case_id)
    result = registry.invoke(
        "calculate_ubo",
        {"ownership_graph": graph, "ownership_threshold": 0.25},
        context,
    )
    assert result["error"]["code"] == "EVIDENCE_CONTRACT_ERROR"
    assert registry.case_store.get(context.case_id) == before


def test_downstream_ubo_tools_require_exact_stored_graph():
    registry = KycToolRegistry()
    context = KycToolContext(case_id="CASE-STORED-GRAPH", as_of_date=date(2025, 12, 20))
    built = registry.invoke(
        "build_ownership_graph",
        {"company_id": "COMP-000008", "max_depth": 3},
        context,
    )
    assert built["status"] == "ok"
    exact = registry.invoke(
        "calculate_ubo",
        {"ownership_graph": built["result"], "ownership_threshold": 0.25},
        context,
    )
    assert exact["status"] == "ok"

    modified = {**built["result"], "ownership_status": "INCOMPLETE"}
    before = registry.case_store.get(context.case_id)
    rejected = registry.invoke(
        "find_ownership_gaps", {"ownership_graph": modified}, context
    )
    assert rejected["error"]["code"] == "EVIDENCE_CONTRACT_ERROR"
    assert registry.case_store.get(context.case_id) == before
```

- [ ] **Step 2: Run the registry module and confirm red state**

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/unit/investigation_orchestrator/test_kyc_tools.py \
  -q -p no:cacheprovider
```

Expected: the new fabricated/modified graph assertions fail because the current registry trusts both payloads.

- [ ] **Step 3: Add exact stored-graph validation**

Import `EvidenceContractError`, add:

```python
def _stored_ownership_graph(
    self,
    graph: OwnershipGraphResult,
    context: KycToolContext,
) -> OwnershipGraphResult:
    case = self.case_store.get(context.case_id)
    stored = next(
        (item for item in case.ownership_graphs if item.graph_id == graph.graph_id),
        None,
    )
    if stored is None:
        raise EvidenceContractError(
            f"ownership graph {graph.graph_id} is not stored in case {context.case_id}"
        )
    if stored != graph:
        raise EvidenceContractError(
            f"ownership graph {graph.graph_id} differs from the stored case graph"
        )
    return stored
```

Use the returned stored graph in both dispatch branches:

```python
if name == "calculate_ubo":
    graph = self._stored_ownership_graph(parsed.ownership_graph, context)
    return self.facade.calculate_ubo(graph, data["ownership_threshold"])
if name == "find_ownership_gaps":
    graph = self._stored_ownership_graph(parsed.ownership_graph, context)
    return self.facade.find_ownership_gaps(graph)
```

- [ ] **Step 4: Add and run a failing domain test**

```python
def test_verified_edge_requires_evidence_ids():
    graph = _graph([
        OwnershipEdge(
            ownership_id="O-NO-EVIDENCE",
            owned_company_id="TARGET",
            owner_entity_id="CUST-A",
            owner_entity_type="CUSTOMER",
            direct_percentage=100,
            verified=True,
            source_document_id="D1",
        ),
    ])
    with pytest.raises(OwnershipTraversalError, match="verified ownership edge lacks evidence"):
        OwnershipUboService().calculate_ubo(graph, 0.25)
```

Expected before implementation: the service returns a verified UBO.

- [ ] **Step 5: Reject evidence-free verified edges**

Immediately after graph-total validation:

```python
missing_evidence = [
    edge.ownership_id
    for edge in ownership_graph.edges
    if edge.verified and not edge.evidence_ids
]
if missing_evidence:
    raise OwnershipTraversalError(
        f"verified ownership edge lacks evidence: {sorted(missing_evidence)}"
    )
```

Add evidence IDs to existing cycle fixtures so those tests still reach cycle logic.

- [ ] **Step 6: Run both targeted modules**

Expected: all registry and ownership tests pass.

### Task 2: Derive External Identity Scope in the Backend

**Files:**
- Modify: `backend/app/kyc_entity/normalization.py:53-86`
- Modify: `backend/app/kyc_entity/entity_resolution.py:79-90`
- Test: `backend/tests/unit/kyc_entity/test_entity_resolution.py`

**Interfaces:**
- Produces: external markers always map to `LIMITED_EXTERNAL_IDENTITY`; external candidates always have `ubo_eligible=False`.

- [ ] **Step 1: Add failing scope tests**

```python
def test_external_identity_cannot_override_scope_or_ubo_eligibility():
    raw = {
        "external_account_id": "EXT-ACC-FAKE",
        "entity_id": "EXT-ACC-FAKE",
        "entity_type": "CUSTOMER",
        "identity_scope": "FULL_INTERNAL",
        "full_name": "External Person",
    }
    result = EntityResolutionService().resolve_entity(raw, [raw])
    candidate = result.candidates[0]
    assert result.normalized_input.identity_scope == "LIMITED_EXTERNAL_IDENTITY"
    assert candidate.identity_scope == "LIMITED_EXTERNAL_IDENTITY"
    assert candidate.ubo_eligible is False


def test_masked_external_record_is_limited_without_external_account_id():
    normalized = EntityResolutionService().normalize_identity({
        "masked_account_number": "****1234",
        "bank_id": "BANK-X",
        "identity_scope": "FULL_INTERNAL",
    })
    assert normalized.identity_scope == "LIMITED_EXTERNAL_IDENTITY"
```

- [ ] **Step 2: Run the module and confirm both tests fail**

Run the identity module with pytest and expect caller-provided `FULL_INTERNAL` to appear.

- [ ] **Step 3: Derive scope from markers**

Add:

```python
def _identity_scope(raw_identity: dict[str, Any]) -> str:
    identifiers = (
        raw_identity.get("entity_id"),
        raw_identity.get("account_id"),
        raw_identity.get("external_account_id"),
    )
    has_external_marker = bool(
        raw_identity.get("external_account_id")
        or raw_identity.get("masked_account_number")
        or any(str(value).startswith("EXT-") for value in identifiers if value)
    )
    if has_external_marker:
        return "LIMITED_EXTERNAL_IDENTITY"
    if raw_identity.get("identity_scope") == "LIMITED_EXTERNAL_IDENTITY":
        return "LIMITED_EXTERNAL_IDENTITY"
    return "FULL_INTERNAL"
```

Replace the inline scope expression with `scope = _identity_scope(raw_identity)`.

- [ ] **Step 4: Tighten candidate eligibility**

```python
ubo_eligible=(
    scope == "FULL_INTERNAL"
    and str(candidate.get("entity_type")) == "CUSTOMER"
    and entity_id.startswith("CUST-")
),
```

- [ ] **Step 5: Run the identity module**

Expected: all identity tests pass.

### Task 3: Detect Intermediate Ownership Gaps and Relationships

**Files:**
- Modify: `backend/app/kyc_entity/ownership_ubo.py:110-246`
- Test: `backend/tests/unit/kyc_entity/test_ownership_ubo.py`

**Interfaces:**
- Produces: one stable coverage gap per incomplete company and deduplicated unresolved relationship IDs from every company node.

- [ ] **Step 1: Add a failing intermediate-coverage test**

```python
def test_intermediate_company_incomplete_coverage_creates_gap():
    graph = OwnershipGraphResult(
        graph_id="PARTIAL-UPSTREAM",
        root_company_id="TARGET",
        as_of_date=date(2025, 12, 20),
        max_depth=3,
        nodes=[
            OwnershipNode(node_id="TARGET", entity_type="COMPANY"),
            OwnershipNode(node_id="COMP-A", entity_type="COMPANY"),
            OwnershipNode(node_id="CUST-A", entity_type="CUSTOMER"),
        ],
        edges=[
            OwnershipEdge(
                ownership_id="O1", owned_company_id="TARGET",
                owner_entity_id="COMP-A", owner_entity_type="COMPANY",
                direct_percentage=100, verified=True,
                source_document_id="D1", evidence_ids=["EV-OWN-O1"],
            ),
            OwnershipEdge(
                ownership_id="O2", owned_company_id="COMP-A",
                owner_entity_id="CUST-A", owner_entity_type="CUSTOMER",
                direct_percentage=50, verified=True,
                source_document_id="D2", evidence_ids=["EV-OWN-O2"],
            ),
        ],
        ownership_coverage_percentage=100,
        ownership_status="COMPLETE",
    )
    gaps = OwnershipUboService().find_ownership_gaps(graph)
    assert any(
        gap.type == "INCOMPLETE_OWNERSHIP_COVERAGE" and "COMP-A" in gap.gap_id
        for gap in gaps
    )
```

- [ ] **Step 2: Run the single test and confirm no intermediate gap exists**

- [ ] **Step 3: Compute coverage per company**

Replace the root-only block with:

```python
company_ids = {
    node.node_id for node in ownership_graph.nodes if node.entity_type == "COMPANY"
}
coverage_by_company: dict[str, float] = defaultdict(float)
for edge in ownership_graph.edges:
    coverage_by_company[edge.owned_company_id] += edge.direct_percentage

for company_id in sorted(company_ids):
    if company_id not in coverage_by_company:
        continue
    coverage = coverage_by_company[company_id]
    if coverage >= 99.99:
        continue
    gaps.append(OwnershipGap(
        gap_id=f"GAP-COVERAGE-{ownership_graph.graph_id}-{company_id}",
        type="INCOMPLETE_OWNERSHIP_COVERAGE",
        description=f"Known direct ownership for {company_id} covers {coverage}%",
    ))
```

This also handles the root and avoids a duplicate root gap.

- [ ] **Step 4: Add a failing intermediate unresolved-relationship test**

```python
def test_intermediate_unresolved_relationship_is_collected(monkeypatch):
    service = OwnershipUboService()
    baseline = service.build_ownership_graph("COMP-000005", date(2025, 12, 20), 3)
    intermediate = next(
        node.node_id
        for node in baseline.nodes
        if node.entity_type == "COMPANY" and node.node_id != baseline.root_company_id
    )
    original = service.entity_data.relationships

    def relationships(entity_id):
        if entity_id == intermediate:
            return [{
                "relationship_id": "REL-INTERMEDIATE-UNRESOLVED",
                "source_entity_id": "COMP-UNKNOWN",
                "target_entity_id": intermediate,
                "relationship_type": "UNRESOLVED_UBO_CHAIN",
            }]
        return original(entity_id)

    monkeypatch.setattr(service.entity_data, "relationships", relationships)
    graph = service.build_ownership_graph("COMP-000005", date(2025, 12, 20), 3)
    assert "REL-INTERMEDIATE-UNRESOLVED" in graph.unresolved_relationship_ids
```

- [ ] **Step 5: Query relationships for every company node**

```python
unresolved_ids: list[str] = []
for node in nodes:
    if node.entity_type != "COMPANY":
        continue
    for relationship in self.entity_data.relationships(node.node_id):
        if relationship.get("relationship_type") != "UNRESOLVED_UBO_CHAIN":
            continue
        relationship_id = str(relationship["relationship_id"])
        unresolved_ids.append(relationship_id)
        evidence.append(source_evidence(
            "REL", relationship_id, "SHB_ENTITY_RELATIONSHIP",
            f"Unresolved ownership relationship {relationship_id}", relationship,
        ))
unresolved_ids = sorted(set(unresolved_ids))
```

- [ ] **Step 6: Run the ownership test module**

Expected: all ownership tests pass.

### Task 4: Separate Error Semantics and Validate Document Subjects

**Files:**
- Modify: `backend/app/investigation_orchestrator/case_store.py:1-44`
- Modify: `backend/app/investigation_orchestrator/tool_registry.py:1-110`
- Modify: `backend/app/kyc_entity/document_intelligence.py:40-44`
- Test: `backend/tests/unit/investigation_orchestrator/test_kyc_tools.py`
- Test: `backend/tests/unit/kyc_entity/test_kyc_and_documents.py`

**Interfaces:**
- Produces: `CaseRevisionConflictError`; distinct repository/revision error codes; unknown document subjects raise `EntityNotFoundError`.

- [ ] **Step 1: Add failing error-mapping tests**

Use small fakes so repository global state is not disturbed:

```python
from app.data.exceptions import DataRepositoryNotInitializedError
from app.investigation_orchestrator.case_store import (
    CaseRevisionConflictError,
    InMemoryCaseStateStore,
)


def test_repository_not_initialized_has_distinct_error_code():
    class ColdFacade:
        def get_company_profile(self, company_id, as_of_date):
            raise DataRepositoryNotInitializedError("repository is cold")

    registry = KycToolRegistry(facade=ColdFacade())
    result = registry.invoke(
        "get_company_profile",
        {"company_id": "COMP-000008"},
        KycToolContext(case_id="CASE-COLD", as_of_date=date(2025, 12, 20)),
    )
    assert result["error"]["code"] == "DATA_REPOSITORY_NOT_INITIALIZED"


def test_case_revision_conflict_keeps_revision_error_code():
    class ConflictingStore(InMemoryCaseStateStore):
        def replace(self, case_id, expected_revision, new_state):
            raise CaseRevisionConflictError("stale case revision")

    registry = KycToolRegistry(case_store=ConflictingStore())
    result = registry.invoke(
        "normalize_identity",
        {"raw_identity": {"full_name": "Nguyen Van A"}},
        KycToolContext(case_id="CASE-STALE", as_of_date=date(2025, 12, 20)),
    )
    assert result["error"]["code"] == "CASE_REVISION_CONFLICT"
```

- [ ] **Step 2: Run the registry module and confirm red state**

Expected: repository initialization is mislabeled as revision conflict and `CaseRevisionConflictError` is absent.

- [ ] **Step 3: Add and map dedicated exceptions**

Define:

```python
class CaseRevisionConflictError(RuntimeError):
    """Raised when a compare-and-swap case replacement sees a stale revision."""
```

Raise it from `InMemoryCaseStateStore.replace`. Import repository exceptions and use ordered handlers:

```python
except DataRepositoryNotInitializedError as exc:
    return {"status": "error", "error": {
        "code": "DATA_REPOSITORY_NOT_INITIALIZED", "message": str(exc),
    }}
except DataRepositoryError as exc:
    return {"status": "error", "error": {
        "code": "DATA_REPOSITORY_ERROR", "message": str(exc),
    }}
except CaseRevisionConflictError as exc:
    return {"status": "error", "error": {
        "code": "CASE_REVISION_CONFLICT", "message": str(exc),
    }}
except RuntimeError as exc:
    return {"status": "error", "error": {
        "code": "INTERNAL_ERROR", "message": str(exc),
    }}
```

- [ ] **Step 4: Add failing unknown-document tests**

```python
def test_get_documents_rejects_unknown_internal_entity():
    with pytest.raises(EntityNotFoundError, match="entity not found"):
        DocumentIntelligenceService().get_kyc_documents("CUST-DOES-NOT-EXIST")


def test_get_documents_keeps_external_scope_error():
    with pytest.raises(EntityScopeViolationError):
        DocumentIntelligenceService().get_kyc_documents("EXT-ACC-000001")
```

- [ ] **Step 5: Validate entity existence**

```python
def get_kyc_documents(self, entity_id: str) -> DocumentAnalysisResult:
    self._require_internal(entity_id)
    if self.entity_data.entity(entity_id) is None:
        raise EntityNotFoundError(f"entity not found: {entity_id}")
    documents = self.entity_data.kyc_documents(entity_id)
    evidence = [self._document_evidence(item) for item in documents]
    return DocumentAnalysisResult(documents=documents, evidence=evidence)
```

- [ ] **Step 6: Run registry and KYC/document test modules**

Expected: all tests pass.

### Task 5: Remove Only Proven Dead Code and Redundant Keep Files

**Files:**
- Modify: `backend/app/kyc_entity/ownership_ubo.py`
- Modify: `backend/synthetic_data/{config,normal_transaction_generator,ownership_generator,pipeline,profiles,scenario_injector,validators}.py`
- Modify: `backend/tests/unit/synthetic_data/test_generator.py`
- Delete: twenty-one redundant `.gitkeep` files listed below.

**Interfaces:**
- Consumes: no runtime interface; deletion list is fixed by the approved design.
- Produces: no new interface; public behavior remains unchanged.

- [ ] **Step 1: Re-run the exact-reference scan**

```bash
rg -n "_utc|_sample_hour|_ownership_sum|_entity_start_customer|PURPOSE_CODES|CHANNELS|ACCOUNT_TYPES|DOCUMENT_TYPES" \
  backend docs -g '*.py' -g '*.md'
```

Expected: each symbol appears only at its definition or in the new design/plan.

- [ ] **Step 2: Remove exact dead symbols**

Delete `_utc`, `_sample_hour`, `_ownership_sum`, `_entity_start_customer`, `PURPOSE_CODES`, `CHANNELS`, `ACCOUNT_TYPES`, and `DOCUMENT_TYPES`.

- [ ] **Step 3: Remove exact unused imports**

```text
backend/app/kyc_entity/ownership_ubo.py: Any
backend/synthetic_data/config.py: date
backend/synthetic_data/normal_transaction_generator.py: timezone
backend/synthetic_data/pipeline.py: validate_world
backend/synthetic_data/profiles.py: field
backend/synthetic_data/scenario_injector.py: date
backend/synthetic_data/validators.py: timezone, EntityType
backend/tests/unit/synthetic_data/test_generator.py: Path
```

- [ ] **Step 4: Delete exactly these redundant keep files**

```text
backend/app/compliance_intelligence/.gitkeep
backend/app/detection/.gitkeep
backend/app/investigation_orchestrator/.gitkeep
backend/app/kyc_entity/.gitkeep
backend/app/schemas/.gitkeep
backend/app/transaction_investigation/.gitkeep
backend/config/.gitkeep
backend/data/generated/.gitkeep
backend/mocks/compliance_intelligence/.gitkeep
backend/mocks/detection/.gitkeep
backend/mocks/fixtures/.gitkeep
backend/mocks/investigation_orchestrator/.gitkeep
backend/mocks/kyc_entity/.gitkeep
backend/mocks/transaction_investigation/.gitkeep
backend/scripts/.gitkeep
backend/tests/e2e/.gitkeep
backend/tests/integration/.gitkeep
backend/tests/unit/.gitkeep
docker/.gitkeep
docs/.gitkeep
frontend/.gitkeep
```

- [ ] **Step 5: Check protected files**

Confirm `backend/data/sample/.gitkeep`, `backend/tests/fixtures/.gitkeep`, `frontend/src/.gitkeep`, `scripts/.gitkeep`, and every generated artifact remain unchanged.

### Task 6: Full Verification and Diff Review

**Files:**
- Verify all production, test, spec, plan, and `.gitkeep` changes from Tasks 1-5.

**Interfaces:**
- Produces: fresh evidence for targeted tests, full tests, syntax, boundaries, and diff scope.

- [ ] **Step 1: Run targeted regressions**

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/unit/investigation_orchestrator/test_kyc_tools.py \
  tests/unit/kyc_entity/test_entity_resolution.py \
  tests/unit/kyc_entity/test_ownership_ubo.py \
  tests/unit/kyc_entity/test_kyc_and_documents.py \
  -q -p no:cacheprovider
```

Expected: zero failures.

- [ ] **Step 2: Run the complete backend suite**

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

Expected: zero failures.

- [ ] **Step 3: Parse all Python sources**

```bash
python3 - <<'PY'
import ast
from pathlib import Path

files = [
    path for path in Path("backend").rglob("*.py")
    if ".venv" not in path.parts and "__pycache__" not in path.parts
]
for path in files:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
print(f"AST parse OK: {len(files)} Python files")
PY
```

Expected: one `AST parse OK` line and exit code 0.

- [ ] **Step 4: Re-run boundary and dead-symbol scans**

```bash
rg -n "ground_truth|DataRepository|get_initialized_data_repository|import pandas|import networkx" \
  backend/app/kyc_entity backend/app/investigation_orchestrator -g '*.py'
rg -n "^(def (_utc|_sample_hour|_ownership_sum|_entity_start_customer)|PURPOSE_CODES =|CHANNELS =|ACCOUNT_TYPES =|DOCUMENT_TYPES =)" \
  backend -g '*.py'
```

Expected: both commands produce no output and return no match.

- [ ] **Step 5: Review whitespace and scope**

```bash
git diff --check
git diff --stat
git diff -- backend/app backend/synthetic_data backend/tests
git status --short
```

Expected: `git diff --check` exits 0; no generated artifact changed; only the approved keep files are newly deleted; unrelated user changes remain intact.
