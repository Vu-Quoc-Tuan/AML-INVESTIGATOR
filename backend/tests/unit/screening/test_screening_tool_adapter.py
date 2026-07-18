from app.investigation_orchestrator.tool_registry import ToolResult, ToolRegistry
from app.schemas.screening import ScreeningCandidate, ScreeningEvidence, ScreeningResponse
from app.screening.tool_adapter import adapt_screening_response, build_screening_tools


def evidence(scope="SHB_INTERNAL"):
    return ScreeningEvidence(
        evidence_id="EV-SCREENING-WL-001",
        source_system="DEMO-SANCTIONS-LIST",
        source_record_id="WL-001",
        visibility_level=scope,
    )


def candidate(match_basis, score=0.9, conflicts=None):
    return ScreeningCandidate(
        candidate_id="WL-001",
        list_type="SANCTIONS",
        source_name="DEMO-SANCTIONS-LIST",
        matched_name="Nguyen Van An",
        score=score,
        match_basis=match_basis,
        conflicting_attributes=conflicts or [],
        evidence_ids=["EV-SCREENING-WL-001"],
    )


def response(*, status, conclusion, match_basis=None, scope="SHB_INTERNAL"):
    candidates = [] if match_basis is None else [candidate(match_basis)]
    evidence_items = [] if match_basis is None else [evidence(scope)]
    return ScreeningResponse(
        request_id="REQ-001",
        subject_id="CUST-001",
        entity_scope=scope,
        status=status,
        conclusion=conclusion,
        candidates=candidates,
        evidence=evidence_items,
        error_code="SCREENING_DATA_ERROR" if status == "ERROR" else None,
    )


def test_confirmed_response_validates_as_orchestrator_tool_result():
    boundary = adapt_screening_response(
        response(
            status="SUCCESS",
            conclusion="CONFIRMED_MATCH",
            match_basis="IDENTIFIER",
        )
    )

    parsed = ToolResult.model_validate(boundary.model_dump(mode="json"))

    assert parsed.status == "SUCCESS"
    assert parsed.data["available"] is True
    assert parsed.data["match_basis"] == "IDENTIFIER"
    assert parsed.evidence[0].evidence_id == "EV-SCREENING-WL-001"


def test_potential_match_is_successful_tool_execution_with_evidence():
    boundary = adapt_screening_response(
        response(
            status="INCONCLUSIVE",
            conclusion="POTENTIAL_MATCH",
            match_basis="NAME_ONLY",
        )
    )

    assert boundary.status == "SUCCESS"
    assert boundary.data["available"] is True
    assert boundary.data["conclusion"] == "POTENTIAL_MATCH"
    assert boundary.data["match_basis"] == "NAME"
    assert boundary.evidence


def test_external_scope_is_translated_only_at_orchestrator_boundary():
    boundary = adapt_screening_response(
        response(
            status="INCONCLUSIVE",
            conclusion="POTENTIAL_MATCH",
            match_basis="NAME_ONLY",
            scope="EXTERNAL_OBSERVED",
        )
    )

    assert boundary.data["entity_scope"] == "EXTERNAL"
    assert boundary.evidence[0].visibility_level == "EXTERNAL_OBSERVED"


def test_unavailable_and_error_results_remain_unavailable():
    no_data = adapt_screening_response(
        response(status="NO_DATA", conclusion="UNABLE_TO_SCREEN")
    )
    error = adapt_screening_response(
        response(status="ERROR", conclusion="UNABLE_TO_SCREEN")
    )

    assert no_data.status == "NO_DATA"
    assert no_data.data["available"] is False
    assert error.status == "ERROR"
    assert error.data["available"] is False
    assert error.error_code == "SCREENING_DATA_ERROR"


def test_screening_tool_factory_registers_under_screening_owner():
    tools = build_screening_tools()
    registry = ToolRegistry()

    registry.register("screening", tools)

    assert len(tools) == 1
    assert registry.get_tool("screening", "screen_subject_against_watchlists") is tools[0]
