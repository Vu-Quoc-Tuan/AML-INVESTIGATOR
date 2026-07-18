import json
from datetime import date

from app.data.exceptions import DataRepositoryNotInitializedError
from app.investigation_orchestrator.case_store import (
    CaseRevisionConflictError,
    InMemoryCaseStateStore,
)
from app.investigation_orchestrator.tool_registry import KycToolRegistry
from app.schemas.tools import KycToolContext


def test_tool_binds_case_appends_and_serializes():
    registry = KycToolRegistry()
    context = KycToolContext(case_id="CASE-TOOLS", as_of_date=date(2025, 12, 20))
    result = registry.invoke(
        "get_company_profile", {"company_id": "COMP-000008"}, context
    )
    assert result["status"] == "ok"
    assert registry.case_store.get("CASE-TOOLS").revision == 1
    json.dumps(result, allow_nan=False)


def test_scope_error_does_not_mutate_case():
    registry = KycToolRegistry()
    context = KycToolContext(case_id="CASE-SCOPE", as_of_date=date(2025, 12, 20))
    before = registry.case_store.get("CASE-SCOPE")
    result = registry.invoke(
        "build_ownership_graph", {"company_id": "EXT-ACC-000001"}, context
    )
    assert result["error"]["code"] == "ENTITY_SCOPE_VIOLATION"
    assert registry.case_store.get("CASE-SCOPE") == before


def test_distinct_identity_inputs_do_not_reuse_evidence_id():
    registry = KycToolRegistry()
    context = KycToolContext(case_id="CASE-IDENTITY", as_of_date=date(2025, 12, 20))
    first = registry.invoke(
        "normalize_identity", {"raw_identity": {"full_name": "Nguyen Van A"}}, context
    )
    second = registry.invoke(
        "normalize_identity", {"raw_identity": {"full_name": "Nguyen Van B"}}, context
    )
    assert first["status"] == second["status"] == "ok"
    evidence_ids = [item.evidence_id for item in registry.case_store.get("CASE-IDENTITY").evidence]
    assert len(evidence_ids) == len(set(evidence_ids)) == 2


def test_calculate_ubo_rejects_graph_not_stored_in_bound_case():
    registry = KycToolRegistry()
    context = KycToolContext(
        case_id="CASE-FABRICATED", as_of_date=date(2025, 12, 20)
    )
    graph = {
        "graph_id": "CALLER-SUPPLIED",
        "root_company_id": "COMP-FAKE",
        "as_of_date": "2025-12-20",
        "max_depth": 3,
        "nodes": [
            {"node_id": "COMP-FAKE", "entity_type": "COMPANY"},
            {"node_id": "CUST-FAKE", "entity_type": "CUSTOMER"},
        ],
        "edges": [
            {
                "ownership_id": "OWN-FAKE",
                "owned_company_id": "COMP-FAKE",
                "owner_entity_id": "CUST-FAKE",
                "owner_entity_type": "CUSTOMER",
                "direct_percentage": 100,
                "verified": True,
            }
        ],
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
    context = KycToolContext(
        case_id="CASE-STORED-GRAPH", as_of_date=date(2025, 12, 20)
    )
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


def test_repository_not_initialized_has_distinct_error_code():
    class ColdFacade:
        def get_company_profile(self, company_id, as_of_date):
            raise DataRepositoryNotInitializedError("repository is cold")

    registry = KycToolRegistry(facade=ColdFacade())
    result = registry.invoke(
        "get_company_profile",
        {"company_id": "COMP-000008"},
        KycToolContext(
            case_id="CASE-COLD", as_of_date=date(2025, 12, 20)
        ),
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
        KycToolContext(
            case_id="CASE-STALE", as_of_date=date(2025, 12, 20)
        ),
    )
    assert result["error"]["code"] == "CASE_REVISION_CONFLICT"


def test_unmapped_tool_result_returns_error_without_mutating_case():
    class UnexpectedFacade:
        def get_company_profile(self, company_id, as_of_date):
            return {"company_id": company_id, "as_of_date": as_of_date}

    registry = KycToolRegistry(facade=UnexpectedFacade())
    context = KycToolContext(
        case_id="CASE-UNMAPPED-RESULT", as_of_date=date(2025, 12, 20)
    )
    before = registry.case_store.get(context.case_id)

    result = registry.invoke(
        "get_company_profile", {"company_id": "COMP-000008"}, context
    )

    assert result["error"]["code"] == "INTERNAL_ERROR"
    assert registry.case_store.get(context.case_id) == before
