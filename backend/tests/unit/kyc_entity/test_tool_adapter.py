from datetime import date

import pytest
from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from app.investigation_orchestrator.tool_registry import ToolRegistry, ToolResult
from app.kyc_entity.exceptions import (
    EntityNotFoundError,
    EntityScopeViolationError,
    EvidenceConflictError,
    EvidenceContractError,
    KycEntityError,
    OwnershipTraversalError,
)
from app.kyc_entity.tool_adapter import build_kyc_tools
from app.schemas.evidence import KycEvidence
from app.schemas.kyc_entity import (
    CompanyProfileSnapshot,
    DocumentAnalysisResult,
    IdentifiedUbo,
    OwnershipGap,
    OwnershipGraphResult,
    UboCalculationResult,
)


AS_OF = date(2025, 12, 20)
KYC_TOOL_NAMES = {
    "get_company_profile",
    "get_kyc_documents",
    "build_ownership_graph",
    "calculate_ubo",
    "find_ownership_gaps",
}
VALID_INPUTS = {
    "get_company_profile": {"company_id": "COMP-001", "as_of_date": AS_OF},
    "get_kyc_documents": {"entity_id": "COMP-001"},
    "build_ownership_graph": {
        "company_id": "COMP-001",
        "as_of_date": AS_OF,
        "max_depth": 3,
    },
    "calculate_ubo": {
        "company_id": "COMP-001",
        "as_of_date": AS_OF,
        "max_depth": 3,
        "ownership_threshold": 0.25,
    },
    "find_ownership_gaps": {
        "company_id": "COMP-001",
        "as_of_date": AS_OF,
        "max_depth": 3,
    },
}


def kyc_evidence() -> KycEvidence:
    return KycEvidence(
        evidence_id="EV-KYC-COMP-001",
        source_type="SHB_COMPANY_MASTER",
        source_record_id="COMP-001",
        statement="SHB company master record COMP-001",
        visibility_level="FULL_INTERNAL",
        attributes={"company_id": "COMP-001"},
    )


def ownership_graph() -> OwnershipGraphResult:
    return OwnershipGraphResult(
        graph_id="OWNGRAPH-COMP-001-2025-12-20-D3",
        root_company_id="COMP-001",
        as_of_date=AS_OF,
        max_depth=3,
        ownership_coverage_percentage=100.0,
        ownership_status="COMPLETE",
        evidence=[kyc_evidence()],
    )


class StaticKycFacade:
    def __init__(self) -> None:
        self.graph = ownership_graph()
        self.graph_build_count = 0
        self.calculated_graphs = []
        self.gap_graphs = []

    def get_company_profile(self, company_id, as_of_date):
        return CompanyProfileSnapshot(
            entity={"company_id": company_id},
            address=None,
            accounts=[],
            kyc_profile=None,
            documents=[],
            representative=None,
            direct_owners=[],
            ownership_coverage_percentage=100.0,
            ownership_status="COMPLETE",
            evidence=[kyc_evidence()],
        )

    def get_kyc_documents(self, entity_id):
        return DocumentAnalysisResult(
            documents=[{"document_id": "DOC-001", "entity_id": entity_id}],
            evidence=[kyc_evidence()],
        )

    def build_ownership_graph(self, company_id, as_of_date, max_depth=3):
        self.graph_build_count += 1
        return self.graph

    def calculate_ubo(self, graph, ownership_threshold=0.25):
        self.calculated_graphs.append(graph)
        return UboCalculationResult(
            identified_ubos=[
                IdentifiedUbo(
                    ubo_result_id="UBO-001",
                    ubo_id="CUST-001",
                    ownership_percentage=100.0,
                    verified=True,
                    evidence_ids=["EV-KYC-COMP-001"],
                )
            ],
            evidence=graph.evidence,
        )

    def find_ownership_gaps(self, graph):
        self.gap_graphs.append(graph)
        return [
            OwnershipGap(
                gap_id="GAP-001",
                type="MISSING_OWNERSHIP_DOCUMENT",
                description="One ownership document is missing",
                evidence_ids=["EV-KYC-COMP-001"],
            )
        ]


def invoke_tool(tool, args: dict) -> ToolMessage:
    message = tool.invoke(
        {"name": tool.name, "args": args, "id": "CALL-KYC-001", "type": "tool_call"}
    )
    assert isinstance(message, ToolMessage)
    return message


def test_factory_exposes_only_approved_kyc_tools() -> None:
    tools = build_kyc_tools(StaticKycFacade())

    assert {tool.name for tool in tools} == KYC_TOOL_NAMES
    assert len(tools) == len(KYC_TOOL_NAMES)


@pytest.mark.parametrize("tool_name", sorted(KYC_TOOL_NAMES))
def test_every_kyc_tool_returns_the_orchestrator_contract(tool_name: str) -> None:
    tool = next(
        tool
        for tool in build_kyc_tools(StaticKycFacade())
        if tool.name == tool_name
    )

    result = ToolResult.model_validate(
        invoke_tool(tool, VALID_INPUTS[tool_name]).artifact
    )

    assert result.status == "SUCCESS"
    assert result.data["entity_scope"] == "SHB_INTERNAL"
    assert result.evidence


def test_kyc_evidence_preserves_provenance_and_statement() -> None:
    tool = next(
        tool
        for tool in build_kyc_tools(StaticKycFacade())
        if tool.name == "get_company_profile"
    )

    result = ToolResult.model_validate(
        invoke_tool(tool, VALID_INPUTS[tool.name]).artifact
    )
    evidence = result.evidence[0]

    assert evidence.evidence_id == "EV-KYC-COMP-001"
    assert evidence.source_system == "SHB_COMPANY_MASTER"
    assert evidence.source_record_id == "COMP-001"
    assert evidence.visibility_level == "FULL_INTERNAL"
    assert evidence.payload == {
        "statement": "SHB company master record COMP-001",
        "attributes": {"company_id": "COMP-001"},
    }


@pytest.mark.parametrize("tool_name", ["calculate_ubo", "find_ownership_gaps"])
def test_downstream_tools_build_their_own_trusted_graph(tool_name: str) -> None:
    facade = StaticKycFacade()
    tool = next(
        tool for tool in build_kyc_tools(facade) if tool.name == tool_name
    )

    result = ToolResult.model_validate(
        invoke_tool(tool, VALID_INPUTS[tool_name]).artifact
    )

    received = facade.calculated_graphs if tool_name == "calculate_ubo" else facade.gap_graphs
    assert result.status == "SUCCESS"
    assert facade.graph_build_count == 1
    assert received == [facade.graph]


def test_ubo_input_rejects_a_model_supplied_ownership_graph() -> None:
    tool = next(
        tool
        for tool in build_kyc_tools(StaticKycFacade())
        if tool.name == "calculate_ubo"
    )

    with pytest.raises(ValidationError):
        tool.invoke(
            {
                **VALID_INPUTS[tool.name],
                "ownership_graph": ownership_graph().model_dump(mode="json"),
            }
        )


@pytest.mark.parametrize(
    ("exception", "status", "marker"),
    [
        (EntityNotFoundError("missing"), "NO_DATA", "ENTITY_NOT_FOUND"),
        (
            OwnershipTraversalError("incomplete"),
            "INCONCLUSIVE",
            "OWNERSHIP_TRAVERSAL_ERROR",
        ),
        (
            EntityScopeViolationError("external"),
            "ERROR",
            "ENTITY_SCOPE_VIOLATION",
        ),
        (
            EvidenceContractError("invalid evidence"),
            "ERROR",
            "EVIDENCE_CONTRACT_ERROR",
        ),
        (EvidenceConflictError("conflict"), "ERROR", "EVIDENCE_CONFLICT"),
        (KycEntityError("domain error"), "ERROR", "KYC_ENTITY_ERROR"),
    ],
)
def test_domain_errors_are_redacted_to_stable_markers(exception, status, marker) -> None:
    class RaisingFacade(StaticKycFacade):
        def get_company_profile(self, company_id, as_of_date):
            raise exception

    tool = next(
        tool
        for tool in build_kyc_tools(RaisingFacade())
        if tool.name == "get_company_profile"
    )

    result = ToolResult.model_validate(
        invoke_tool(tool, VALID_INPUTS[tool.name]).artifact
    )

    assert result.status == status
    assert result.warnings == [marker]
    assert result.error_code == (marker if status == "ERROR" else None)


def test_unexpected_programming_error_is_not_disguised_as_domain_result() -> None:
    class BrokenFacade(StaticKycFacade):
        def get_company_profile(self, company_id, as_of_date):
            raise RuntimeError("unexpected programming error")

    tool = next(
        tool
        for tool in build_kyc_tools(BrokenFacade())
        if tool.name == "get_company_profile"
    )

    with pytest.raises(RuntimeError, match="unexpected programming error"):
        tool.invoke(VALID_INPUTS[tool.name])


def test_kyc_tools_are_registered_only_for_the_kyc_owner() -> None:
    tools = build_kyc_tools(StaticKycFacade())
    registry = ToolRegistry()

    registry.register("kyc", tools)

    assert registry.tools_for("transaction") == ()
    assert registry.tools_for("screening") == ()
    assert registry.tools_for("kyc") == tools
