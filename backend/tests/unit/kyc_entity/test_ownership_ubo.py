from datetime import date

import pytest

from app.kyc_entity.exceptions import OwnershipTraversalError
from app.kyc_entity.ownership_ubo import OwnershipUboService
from app.schemas.kyc_entity import OwnershipEdge, OwnershipGraphResult, OwnershipNode


def _graph(edges):
    nodes = {
        "TARGET": OwnershipNode(node_id="TARGET", entity_type="COMPANY"),
        "COMP-A": OwnershipNode(node_id="COMP-A", entity_type="COMPANY"),
        "CUST-A": OwnershipNode(node_id="CUST-A", entity_type="CUSTOMER"),
    }
    return OwnershipGraphResult(
        graph_id="G-1",
        root_company_id="TARGET",
        as_of_date=date(2025, 12, 20),
        max_depth=3,
        nodes=list(nodes.values()),
        edges=edges,
        ownership_coverage_percentage=sum(
            edge.direct_percentage for edge in edges if edge.owned_company_id == "TARGET"
        ),
        ownership_status="COMPLETE",
    )


def test_indirect_ubo_multiplies_percentages():
    graph = _graph([
        OwnershipEdge(ownership_id="O1", owned_company_id="TARGET", owner_entity_id="COMP-A", owner_entity_type="COMPANY", direct_percentage=50, verified=True, source_document_id="D1", evidence_ids=["EV-OWN-O1"]),
        OwnershipEdge(ownership_id="O2", owned_company_id="COMP-A", owner_entity_id="CUST-A", owner_entity_type="CUSTOMER", direct_percentage=60, verified=True, source_document_id="D2", evidence_ids=["EV-OWN-O2"]),
    ])
    result = OwnershipUboService().calculate_ubo(graph, 0.25)
    assert result.identified_ubos[0].ownership_percentage == 30.0


def test_calculate_ubo_rejects_path_beyond_graph_max_depth():
    graph = _graph([
        OwnershipEdge(
            ownership_id="O1",
            owned_company_id="TARGET",
            owner_entity_id="COMP-A",
            owner_entity_type="COMPANY",
            direct_percentage=100,
            verified=True,
            source_document_id="D1",
            evidence_ids=["EV-OWN-O1"],
        ),
        OwnershipEdge(
            ownership_id="O2",
            owned_company_id="COMP-A",
            owner_entity_id="CUST-A",
            owner_entity_type="CUSTOMER",
            direct_percentage=100,
            verified=True,
            source_document_id="D2",
            evidence_ids=["EV-OWN-O2"],
        ),
    ]).model_copy(update={"max_depth": 1})

    with pytest.raises(OwnershipTraversalError, match="exceeds max_depth"):
        OwnershipUboService().calculate_ubo(graph, 0.25)


def test_unverified_path_is_not_confirmed_ubo():
    graph = _graph([
        OwnershipEdge(ownership_id="O1", owned_company_id="TARGET", owner_entity_id="CUST-A", owner_entity_type="CUSTOMER", direct_percentage=80, verified=False, evidence_ids=["EV-OWN-O1"]),
    ])
    result = OwnershipUboService().calculate_ubo(graph, 0.25)
    assert result.identified_ubos == []
    assert any(item.type == "UNVERIFIED_OWNERSHIP" for item in result.ownership_gaps)


def test_over_100_is_rejected_defensively():
    graph = _graph([
        OwnershipEdge(ownership_id="O1", owned_company_id="TARGET", owner_entity_id="CUST-A", owner_entity_type="CUSTOMER", direct_percentage=101, verified=True, source_document_id="D1"),
    ])
    with pytest.raises(OwnershipTraversalError):
        OwnershipUboService().calculate_ubo(graph, 0.25)


def test_cycle_terminates_and_creates_gap():
    graph = _graph([
        OwnershipEdge(ownership_id="O1", owned_company_id="TARGET", owner_entity_id="COMP-A", owner_entity_type="COMPANY", direct_percentage=100, verified=True, source_document_id="D1", evidence_ids=["EV-OWN-O1"]),
        OwnershipEdge(ownership_id="O2", owned_company_id="COMP-A", owner_entity_id="TARGET", owner_entity_type="COMPANY", direct_percentage=100, verified=True, source_document_id="D2", evidence_ids=["EV-OWN-O2"]),
    ])
    result = OwnershipUboService().calculate_ubo(graph, 0.25)
    assert result.identified_ubos == []
    assert any(item.type == "OWNERSHIP_CYCLE" for item in result.ownership_gaps)


def test_real_direct_and_indirect_ubo():
    service = OwnershipUboService()
    direct = service.calculate_ubo(
        service.build_ownership_graph("COMP-000008", date(2025, 12, 20), 3), 0.25
    )
    indirect = service.calculate_ubo(
        service.build_ownership_graph("COMP-000005", date(2025, 12, 20), 3), 0.25
    )
    assert {item.ubo_id for item in direct.identified_ubos} == {"CUST-000750", "CUST-001277"}
    assert any(item.ubo_id == "CUST-000556" and item.ownership_percentage == 69.112268 for item in indirect.identified_ubos)


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
    with pytest.raises(
        OwnershipTraversalError, match="verified ownership edge lacks evidence"
    ):
        OwnershipUboService().calculate_ubo(graph, 0.25)


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
                ownership_id="O1",
                owned_company_id="TARGET",
                owner_entity_id="COMP-A",
                owner_entity_type="COMPANY",
                direct_percentage=100,
                verified=True,
                source_document_id="D1",
                evidence_ids=["EV-OWN-O1"],
            ),
            OwnershipEdge(
                ownership_id="O2",
                owned_company_id="COMP-A",
                owner_entity_id="CUST-A",
                owner_entity_type="CUSTOMER",
                direct_percentage=50,
                verified=True,
                source_document_id="D2",
                evidence_ids=["EV-OWN-O2"],
            ),
        ],
        ownership_coverage_percentage=100,
        ownership_status="COMPLETE",
    )
    gaps = OwnershipUboService().find_ownership_gaps(graph)
    assert any(
        gap.type == "INCOMPLETE_OWNERSHIP_COVERAGE"
        and "COMP-A" in gap.gap_id
        for gap in gaps
    )


def test_company_without_ownership_edges_has_zero_coverage_gap():
    graph = _graph([])
    gaps = OwnershipUboService().find_ownership_gaps(graph)
    assert any(
        gap.type == "INCOMPLETE_OWNERSHIP_COVERAGE"
        and "TARGET" in gap.gap_id
        and "0.0%" in gap.description
        for gap in gaps
    )


def test_intermediate_unresolved_relationship_is_collected(monkeypatch):
    service = OwnershipUboService()
    baseline = service.build_ownership_graph(
        "COMP-000005", date(2025, 12, 20), 3
    )
    intermediate = next(
        node.node_id
        for node in baseline.nodes
        if node.entity_type == "COMPANY"
        and node.node_id != baseline.root_company_id
    )
    original = service.entity_data.relationships

    def relationships(entity_id):
        if entity_id == intermediate:
            return [
                {
                    "relationship_id": "REL-INTERMEDIATE-UNRESOLVED",
                    "source_entity_id": "COMP-UNKNOWN",
                    "target_entity_id": intermediate,
                    "relationship_type": "UNRESOLVED_UBO_CHAIN",
                }
            ]
        return original(entity_id)

    monkeypatch.setattr(service.entity_data, "relationships", relationships)
    graph = service.build_ownership_graph(
        "COMP-000005", date(2025, 12, 20), 3
    )
    assert "REL-INTERMEDIATE-UNRESOLVED" in graph.unresolved_relationship_ids
