"""Tool ownership and evidence-boundary tests."""

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from pydantic import ValidationError

from app.investigation_orchestrator.agent_schemas import (
    AgentFindingResponse,
    WorkerAnalysisResponse,
)
from app.investigation_orchestrator.agents import (
    _assemble_worker_output,
    _finalize_screening_output,
    collect_tool_results,
)
from app.investigation_orchestrator.agent_schemas import ScreeningAnalysisResponse
from app.investigation_orchestrator.tool_registry import ToolRegistry, ToolResult


def test_tool_registry_enforces_agent_ownership_and_unique_names() -> None:
    @tool
    def lookup_record(record_id: str) -> dict:
        """Look up one deterministic test record."""

        return {"record_id": record_id}

    registry = ToolRegistry()
    registry.register("transaction", [lookup_record])

    assert registry.get_tool("transaction", "lookup_record") is lookup_record
    assert registry.tools_for("kyc") == ()
    with pytest.raises(KeyError, match="not registered for kyc"):
        registry.get_tool("kyc", "lookup_record")
    with pytest.raises(ValueError, match="already registered"):
        registry.register("screening", [lookup_record])


def test_worker_rejects_model_findings_without_tool_evidence() -> None:
    analysis = WorkerAnalysisResponse(
        status="COMPLETED",
        findings=[
            AgentFindingResponse(
                finding_id="F-1",
                finding_type="TRANSACTION_PATTERN",
                summary="Unsupported model claim",
                evidence_ids=["E-MISSING"],
                visibility_level="FULL_INTERNAL",
            )
        ],
    )
    output = _assemble_worker_output("transaction", analysis, [])

    assert output["status"] == "INCONCLUSIVE"
    assert output["findings"] == []
    assert output["evidence"] == []


def test_tool_messages_are_validated_against_the_result_contract() -> None:
    valid = ToolMessage(
        content=ToolResult(
            status="SUCCESS",
            evidence=[
                {
                    "evidence_id": "E-1",
                    "source_system": "SHB_TRANSACTION_LEDGER",
                    "source_record_id": "TX-1",
                    "visibility_level": "FULL_INTERNAL",
                }
            ],
        ).model_dump_json(),
        tool_call_id="call-1",
        name="lookup_record",
    )
    invalid = ToolMessage(
        content="not-json",
        tool_call_id="call-2",
        name="lookup_record",
    )

    results, warnings = collect_tool_results([valid, invalid], {"lookup_record"})

    assert [result.status for result in results] == ["SUCCESS"]
    assert warnings == ["Tool lookup_record returned an invalid result contract"]


def test_transaction_finding_visibility_must_match_tool_evidence() -> None:
    analysis = WorkerAnalysisResponse(
        status="COMPLETED",
        findings=[
            AgentFindingResponse(
                finding_id="F-VISIBILITY",
                finding_type="TRANSACTION_PATTERN",
                summary="Mismatched visibility",
                evidence_ids=["E-1"],
                visibility_level="PAYMENT_MESSAGE_ONLY",
            )
        ],
    )
    results = [
        ToolResult(
            status="SUCCESS",
            evidence=[
                {
                    "evidence_id": "E-1",
                    "source_system": "SHB_TRANSACTION_LEDGER",
                    "source_record_id": "TX-1",
                    "visibility_level": "FULL_INTERNAL",
                }
            ],
        )
    ]

    output = _assemble_worker_output("transaction", analysis, results)

    assert output["findings"] == []


def test_external_kyc_finding_is_rejected_at_the_boundary() -> None:
    analysis = WorkerAnalysisResponse(
        status="COMPLETED",
        findings=[
            AgentFindingResponse(
                finding_id="F-EXTERNAL-KYC",
                finding_type="KYC_PROFILE",
                summary="Unverified external profile",
                evidence_ids=["E-EXT"],
                entity_scope="EXTERNAL",
            )
        ],
    )
    results = [
        ToolResult(
            status="SUCCESS",
            evidence=[
                {
                    "evidence_id": "E-EXT",
                    "source_system": "PAYMENT_MESSAGE",
                    "source_record_id": "PARTY-1",
                }
            ],
        )
    ]

    output = _assemble_worker_output("kyc", analysis, results)

    assert output["findings"] == []


def test_duplicate_evidence_id_is_removed_as_ambiguous() -> None:
    analysis = WorkerAnalysisResponse(status="COMPLETED")
    duplicated = {
        "evidence_id": "E-DUPLICATE",
        "source_system": "SHB_KYC_REPOSITORY",
        "source_record_id": "KYC-1",
    }
    results = [
        ToolResult(status="SUCCESS", evidence=[duplicated]),
        ToolResult(status="SUCCESS", evidence=[duplicated]),
    ]

    output = _assemble_worker_output("kyc", analysis, results)

    assert output["evidence"] == []
    assert output["metadata"]["warnings"] == [
        "Duplicate evidence rejected: E-DUPLICATE"
    ]


def test_non_success_tool_evidence_cannot_support_findings() -> None:
    analysis = WorkerAnalysisResponse(
        status="COMPLETED",
        findings=[
            AgentFindingResponse(
                finding_id="F-NO-SOURCE",
                finding_type="KYC_PROFILE",
                summary="No successful source",
                evidence_ids=["E-NO-SOURCE"],
                entity_scope="SHB_INTERNAL",
            )
        ],
    )
    results = [
        ToolResult(
            status="INCONCLUSIVE",
            evidence=[
                {
                    "evidence_id": "E-NO-SOURCE",
                    "source_system": "SHB_KYC_REPOSITORY",
                    "source_record_id": "KYC-NO-SOURCE",
                }
            ],
        )
    ]

    output = _assemble_worker_output("kyc", analysis, results)

    assert output["status"] == "INCONCLUSIVE"
    assert output["findings"] == []
    assert output["evidence"] == []


def test_kyc_finding_without_internal_scope_is_rejected() -> None:
    analysis = WorkerAnalysisResponse(
        status="COMPLETED",
        findings=[
            AgentFindingResponse(
                finding_id="F-NO-SCOPE",
                finding_type="KYC_PROFILE",
                summary="Scope omitted",
                evidence_ids=["E-KYC"],
            )
        ],
    )
    results = [
        ToolResult(
            status="SUCCESS",
            evidence=[
                {
                    "evidence_id": "E-KYC",
                    "source_system": "SHB_KYC_REPOSITORY",
                    "source_record_id": "KYC-1",
                }
            ],
        )
    ]

    assert _assemble_worker_output("kyc", analysis, results)["findings"] == []


def test_kyc_internal_claim_requires_tool_derived_internal_scope() -> None:
    analysis = WorkerAnalysisResponse(
        status="COMPLETED",
        findings=[
            AgentFindingResponse(
                finding_id="F-UNVERIFIED-INTERNAL",
                finding_type="KYC_PROFILE",
                summary="Model-only internal scope",
                evidence_ids=["E-KYC-NO-SCOPE"],
                entity_scope="SHB_INTERNAL",
            )
        ],
    )
    results = [
        ToolResult(
            status="SUCCESS",
            data={"profile_status": "verified"},
            evidence=[
                {
                    "evidence_id": "E-KYC-NO-SCOPE",
                    "source_system": "SHB_KYC_REPOSITORY",
                    "source_record_id": "KYC-NO-SCOPE",
                }
            ],
        )
    ]

    assert _assemble_worker_output("kyc", analysis, results)["findings"] == []


def test_tool_contract_rejects_non_json_serializable_payload() -> None:
    with pytest.raises(ValidationError):
        ToolResult(
            status="SUCCESS",
            evidence=[
                {
                    "evidence_id": "E-OBJECT",
                    "source_system": "TEST",
                    "source_record_id": "OBJECT-1",
                    "payload": {"unsafe": object()},
                }
            ],
        )


def test_unavailable_screening_clears_findings() -> None:
    output = {
        "agent": "screening_agent",
        "status": "COMPLETED",
        "available": True,
        "findings": [
            {
                "finding_id": "F-SCREEN",
                "finding_type": "SCREENING_RESULT",
                "summary": "No longer admissible",
                "evidence_ids": ["E-SCREEN"],
            }
        ],
        "evidence": [],
        "metadata": {},
    }
    analysis = ScreeningAnalysisResponse(
        status="COMPLETED",
        screening_status="NO_MATCH",
        available=True,
    )
    results = [ToolResult(status="SUCCESS", data={"available": False})]

    finalized = _finalize_screening_output(output, analysis, results)

    assert finalized["status"] == "INCONCLUSIVE"
    assert finalized["available"] is False
    assert finalized["findings"] == []


def test_screening_analysis_error_cannot_be_reclassified_as_a_match() -> None:
    output = {
        "agent": "screening_agent",
        "status": "ERROR",
        "available": True,
        "findings": [],
        "evidence": [],
        "metadata": {},
    }
    analysis = ScreeningAnalysisResponse(
        status="ERROR",
        screening_status="CONFIRMED_MATCH",
        available=True,
    )

    finalized = _finalize_screening_output(
        output, analysis, [ToolResult(status="SUCCESS")]
    )

    assert finalized["status"] == "ERROR"
    assert finalized["available"] is False


def test_unsupported_confirmed_match_is_downgraded() -> None:
    output = {
        "agent": "screening_agent",
        "status": "COMPLETED",
        "available": True,
        "findings": [
            {
                "finding_id": "F-CONFIRMED",
                "finding_type": "SCREENING_RESULT",
                "summary": "Model claims a confirmed match",
                "evidence_ids": ["E-CONFIRMED"],
            }
        ],
        "evidence": [
            {
                "evidence_id": "E-CONFIRMED",
                "source_system": "INTERNAL_SCREENING_SERVICE",
                "source_record_id": "SCREEN-1",
            }
        ],
        "metadata": {},
    }
    analysis = ScreeningAnalysisResponse(
        status="COMPLETED",
        screening_status="CONFIRMED_MATCH",
        available=True,
    )

    finalized = _finalize_screening_output(
        output,
        analysis,
        [ToolResult(status="SUCCESS", data={"match_basis": "NAME"})],
    )

    assert finalized["status"] == "POTENTIAL_MATCH"


def test_tool_supported_identifier_match_can_remain_confirmed() -> None:
    output = {
        "agent": "screening_agent",
        "status": "COMPLETED",
        "available": True,
        "findings": [
            {
                "finding_id": "F-STRONG-MATCH",
                "finding_type": "SCREENING_RESULT",
                "summary": "Identifier-backed match",
                "evidence_ids": ["E-STRONG-MATCH"],
            }
        ],
        "evidence": [
            {
                "evidence_id": "E-STRONG-MATCH",
                "source_system": "INTERNAL_SCREENING_SERVICE",
                "source_record_id": "SCREEN-STRONG-1",
            }
        ],
        "metadata": {},
    }
    analysis = ScreeningAnalysisResponse(
        status="COMPLETED",
        screening_status="CONFIRMED_MATCH",
        available=True,
    )

    finalized = _finalize_screening_output(
        output,
        analysis,
        [
            ToolResult(
                status="SUCCESS",
                data={"entity_scope": "SHB_INTERNAL", "match_basis": "IDENTIFIER"},
                evidence=[
                    {
                        "evidence_id": "E-STRONG-MATCH",
                        "source_system": "INTERNAL_SCREENING_SERVICE",
                        "source_record_id": "SCREEN-STRONG-1",
                    }
                ],
            )
        ],
    )

    assert finalized["status"] == "CONFIRMED_MATCH"


def test_unrelated_strong_tool_cannot_confirm_another_tools_finding() -> None:
    output = {
        "agent": "screening_agent",
        "status": "COMPLETED",
        "available": True,
        "findings": [
            {
                "finding_id": "F-WEAK",
                "finding_type": "SCREENING_RESULT",
                "summary": "Name-based candidate",
                "evidence_ids": ["E-WEAK"],
            }
        ],
        "evidence": [
            {
                "evidence_id": "E-WEAK",
                "source_system": "INTERNAL_SCREENING_SERVICE",
                "source_record_id": "SCREEN-WEAK-1",
            },
            {
                "evidence_id": "E-UNRELATED-STRONG",
                "source_system": "INTERNAL_SCREENING_SERVICE",
                "source_record_id": "SCREEN-STRONG-2",
            },
        ],
        "metadata": {},
    }
    analysis = ScreeningAnalysisResponse(
        status="COMPLETED",
        screening_status="CONFIRMED_MATCH",
        available=True,
    )
    results = [
        ToolResult(
            status="SUCCESS",
            data={"entity_scope": "EXTERNAL", "match_basis": "NAME"},
            evidence=[
                {
                    "evidence_id": "E-WEAK",
                    "source_system": "INTERNAL_SCREENING_SERVICE",
                    "source_record_id": "SCREEN-WEAK-1",
                }
            ],
        ),
        ToolResult(
            status="SUCCESS",
            data={"entity_scope": "SHB_INTERNAL", "match_basis": "IDENTIFIER"},
            evidence=[
                {
                    "evidence_id": "E-UNRELATED-STRONG",
                    "source_system": "INTERNAL_SCREENING_SERVICE",
                    "source_record_id": "SCREEN-STRONG-2",
                }
            ],
        ),
    ]

    finalized = _finalize_screening_output(output, analysis, results)

    assert finalized["status"] == "POTENTIAL_MATCH"
