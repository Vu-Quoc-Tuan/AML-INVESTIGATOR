"""Bounded ownership traversal and deterministic UBO calculation."""

from collections import defaultdict, deque
from datetime import date

from app.schemas.kyc_entity import (
    IdentifiedUbo,
    KycFinding,
    OwnershipEdge,
    OwnershipGap,
    OwnershipGraphResult,
    OwnershipNode,
    UboCalculationResult,
)
from app.services.entity_data_service import EntityDataService
from app.services.ownership_data_service import OwnershipDataService

from .config import KycEntityConfig
from .document_intelligence import DocumentIntelligenceService
from .evidence import source_evidence
from .exceptions import EntityNotFoundError, EntityScopeViolationError, OwnershipTraversalError


class OwnershipUboService:
    def __init__(
        self,
        ownership_data: OwnershipDataService | None = None,
        entity_data: EntityDataService | None = None,
        config: KycEntityConfig | None = None,
    ) -> None:
        self.ownership_data = ownership_data or OwnershipDataService()
        self.entity_data = entity_data or EntityDataService()
        self.config = config or KycEntityConfig()
        self.documents = DocumentIntelligenceService(self.entity_data, self.config)

    def build_ownership_graph(
        self, company_id: str, as_of_date: date, max_depth: int = 3
    ) -> OwnershipGraphResult:
        if company_id.startswith("EXT-"):
            raise EntityScopeViolationError("external counterparties do not receive UBO analysis")
        company = self.entity_data.entity(company_id)
        if company is None or "company_id" not in company:
            raise EntityNotFoundError(f"company not found: {company_id}")
        if max_depth < 1:
            raise OwnershipTraversalError("max_depth must be at least 1")
        raw = self.ownership_data.ownership_neighborhood(company_id, as_of_date, max_depth)
        raw_nodes = {str(item["id"]): item.get("attributes", {}) for item in raw["nodes"]}
        nodes: list[OwnershipNode] = []
        for node_id, attributes in raw_nodes.items():
            entity = self.entity_data.entity(node_id)
            display_name = None
            if entity:
                display_name = entity.get("full_name") or entity.get("legal_name")
            nodes.append(OwnershipNode(
                node_id=node_id,
                entity_type=str(attributes.get("entity_type") or (
                    "CUSTOMER" if node_id.startswith("CUST-") else "COMPANY"
                )),
                display_name=display_name,
            ))
        edges: list[OwnershipEdge] = []
        evidence = []
        for raw_edge in raw["edges"]:
            owned_company = str(raw_edge["source"])
            owner = str(raw_edge["target"])
            attrs = raw_edge.get("attributes", {})
            ownership_ids = [str(item) for item in attrs.get("ownership_ids", [])]
            records = {
                str(item["ownership_id"]): item
                for item in self.ownership_data.ownership_records(owned_company)
            }
            for ownership_id in ownership_ids:
                record = records.get(ownership_id)
                if record is None:
                    continue
                record_evidence = source_evidence(
                    "OWN", ownership_id, "SHB_OWNERSHIP_RECORD",
                    f"Ownership record {ownership_id}", record,
                )
                evidence.append(record_evidence)
                document_id = record.get("source_document_id")
                document_verified = False
                document_evidence_id = None
                if document_id:
                    document = self.entity_data.kyc_document(str(document_id))
                    if document:
                        doc_result = self.documents.check_document_validity(
                            [str(document_id)], as_of_date
                        )
                        evidence.extend(doc_result.evidence)
                        document_verified = bool(
                            doc_result.validity
                            and doc_result.validity[0].classification == "VALID"
                        )
                        document_evidence_id = f"EV-DOC-{document_id}"
                edge_evidence = [record_evidence.evidence_id]
                if document_evidence_id:
                    edge_evidence.append(document_evidence_id)
                edges.append(OwnershipEdge(
                    ownership_id=ownership_id,
                    owned_company_id=owned_company,
                    owner_entity_id=owner,
                    owner_entity_type=str(record["owner_entity_type"]),
                    direct_percentage=float(record["ownership_percentage"]),
                    verified=bool(record["verified"]) and document_verified,
                    source_document_id=str(document_id) if document_id else None,
                    evidence_ids=edge_evidence,
                ))
        root_coverage = sum(
            edge.direct_percentage for edge in edges
            if edge.owned_company_id == company_id
        )
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
        metadata = raw.get("metadata", {})
        return OwnershipGraphResult(
            graph_id=f"OWNGRAPH-{company_id}-{as_of_date.isoformat()}-D{max_depth}",
            root_company_id=company_id,
            as_of_date=as_of_date,
            max_depth=max_depth,
            nodes=nodes,
            edges=edges,
            ownership_coverage_percentage=round(root_coverage, 4),
            ownership_status="COMPLETE" if abs(root_coverage - 100.0) <= 0.01 else "INCOMPLETE",
            ownership_cycle_detected=bool(metadata.get("ownership_cycle_detected")),
            ownership_cycles=metadata.get("ownership_cycles") or [],
            unresolved_relationship_ids=unresolved_ids,
            evidence=list({item.evidence_id: item for item in evidence}.values()),
        )

    def calculate_ubo(
        self,
        ownership_graph: OwnershipGraphResult,
        ownership_threshold: float = 0.25,
    ) -> UboCalculationResult:
        if not 0 < ownership_threshold <= 1:
            raise OwnershipTraversalError("ownership_threshold must be in (0, 1]")
        self._validate_graph_totals(ownership_graph)
        missing_evidence = [
            edge.ownership_id
            for edge in ownership_graph.edges
            if edge.verified and not edge.evidence_ids
        ]
        if missing_evidence:
            raise OwnershipTraversalError(
                "verified ownership edge lacks evidence: "
                f"{sorted(missing_evidence)}"
            )
        node_types = {node.node_id: node.entity_type for node in ownership_graph.nodes}
        adjacency: dict[str, list[OwnershipEdge]] = defaultdict(list)
        for edge in ownership_graph.edges:
            adjacency[edge.owned_company_id].append(edge)
        contributions: dict[str, float] = defaultdict(float)
        paths: dict[str, list[list[str]]] = defaultdict(list)
        evidence_ids: dict[str, set[str]] = defaultdict(set)
        gaps = self.find_ownership_gaps(ownership_graph)
        queue = deque([(
            ownership_graph.root_company_id,
            0,
            100.0,
            [ownership_graph.root_company_id],
            [],
        )])
        while queue:
            company_id, depth, cumulative, path, path_evidence = queue.popleft()
            for edge in adjacency.get(company_id, []):
                next_id = edge.owner_entity_id
                next_path = [*path, next_id]
                next_evidence = [*path_evidence, *edge.evidence_ids]
                if next_id in path:
                    continue
                next_depth = depth + 1
                if next_depth > ownership_graph.max_depth:
                    raise OwnershipTraversalError(
                        f"ownership path exceeds max_depth "
                        f"{ownership_graph.max_depth}: {' -> '.join(next_path)}"
                    )
                if not edge.verified:
                    continue
                next_percentage = cumulative * edge.direct_percentage / 100.0
                if node_types.get(next_id) == "CUSTOMER":
                    contributions[next_id] += next_percentage
                    paths[next_id].append(next_path)
                    evidence_ids[next_id].update(next_evidence)
                elif node_types.get(next_id) == "COMPANY":
                    queue.append((
                        next_id,
                        next_depth,
                        next_percentage,
                        next_path,
                        next_evidence,
                    ))
        threshold_percentage = ownership_threshold * 100.0
        identified = [
            IdentifiedUbo(
                ubo_result_id=f"UBO-{ownership_graph.graph_id}-{ubo_id}",
                ubo_id=ubo_id,
                ownership_percentage=round(percentage, 6),
                verified=True,
                paths=paths[ubo_id],
                evidence_ids=sorted(evidence_ids[ubo_id]),
            )
            for ubo_id, percentage in sorted(contributions.items())
            if percentage + 1e-9 >= threshold_percentage
        ]
        return UboCalculationResult(
            identified_ubos=identified,
            ownership_gaps=gaps,
            evidence=ownership_graph.evidence,
        )

    def find_ownership_gaps(
        self, ownership_graph: OwnershipGraphResult
    ) -> list[OwnershipGap]:
        gaps: list[OwnershipGap] = []
        company_ids = {
            node.node_id
            for node in ownership_graph.nodes
            if node.entity_type == "COMPANY"
        }
        coverage_by_company: dict[str, float] = defaultdict(float)
        for edge in ownership_graph.edges:
            coverage_by_company[edge.owned_company_id] += edge.direct_percentage
        for company_id in sorted(company_ids):
            coverage = coverage_by_company.get(company_id, 0.0)
            if coverage >= 99.99:
                continue
            gaps.append(OwnershipGap(
                gap_id=(
                    f"GAP-COVERAGE-{ownership_graph.graph_id}-{company_id}"
                ),
                type="INCOMPLETE_OWNERSHIP_COVERAGE",
                description=(
                    f"Known direct ownership for {company_id} covers {coverage}%"
                ),
            ))
        adjacency: dict[str, list[OwnershipEdge]] = defaultdict(list)
        for edge in ownership_graph.edges:
            adjacency[edge.owned_company_id].append(edge)
            if not edge.verified:
                gaps.append(OwnershipGap(
                    gap_id=f"GAP-UNVERIFIED-{edge.ownership_id}",
                    type="UNVERIFIED_OWNERSHIP",
                    description=f"Ownership record {edge.ownership_id} is unverified or lacks valid support",
                    evidence_ids=edge.evidence_ids,
                ))
            if not edge.source_document_id:
                gaps.append(OwnershipGap(
                    gap_id=f"GAP-DOCUMENT-{edge.ownership_id}",
                    type="MISSING_OWNERSHIP_DOCUMENT",
                    description=f"Ownership record {edge.ownership_id} has no supporting document",
                    evidence_ids=edge.evidence_ids,
                ))
        node_types = {node.node_id: node.entity_type for node in ownership_graph.nodes}
        depths = self._depths(ownership_graph)
        for node_id, node_type in node_types.items():
            if node_type == "COMPANY" and node_id != ownership_graph.root_company_id and not adjacency.get(node_id):
                depth = depths.get(node_id, ownership_graph.max_depth)
                gap_type = "MAX_DEPTH_REACHED" if depth >= ownership_graph.max_depth else "BROKEN_OWNERSHIP_CHAIN"
                gaps.append(OwnershipGap(
                    gap_id=f"GAP-{gap_type}-{ownership_graph.graph_id}-{node_id}",
                    type=gap_type,
                    description=f"Ownership chain stops at company {node_id} at depth {depth}",
                ))
        for relationship_id in ownership_graph.unresolved_relationship_ids:
            gaps.append(OwnershipGap(
                gap_id=f"GAP-UNRESOLVED-{relationship_id}",
                type="UNRESOLVED_UBO_CHAIN",
                description=f"Unresolved UBO relationship {relationship_id}",
                evidence_ids=[f"EV-REL-{relationship_id}"],
            ))
        cycles = ownership_graph.ownership_cycles or self._detect_cycles(ownership_graph)
        for index, cycle in enumerate(cycles):
            gaps.append(OwnershipGap(
                gap_id=f"GAP-CYCLE-{ownership_graph.graph_id}-{index}",
                type="OWNERSHIP_CYCLE",
                description=f"Ownership cycle detected: {' -> '.join(cycle)}",
            ))
        return list({gap.gap_id: gap for gap in gaps}.values())

    def flag_unverified_ubo(
        self, company_id: str, as_of_date: date, max_depth: int = 3
    ) -> UboCalculationResult:
        graph = self.build_ownership_graph(company_id, as_of_date, max_depth)
        gaps = self.find_ownership_gaps(graph)
        findings = [
            KycFinding(
                finding_id=f"FIND-{gap.gap_id}",
                type=gap.type,
                statement=gap.description,
                evidence_ids=gap.evidence_ids,
                severity="HIGH" if gap.type in {"UNVERIFIED_OWNERSHIP", "UNRESOLVED_UBO_CHAIN"} else "MEDIUM",
            )
            for gap in gaps
        ]
        return UboCalculationResult(
            ownership_gaps=gaps, findings=findings, evidence=graph.evidence
        )

    @staticmethod
    def _validate_graph_totals(graph: OwnershipGraphResult) -> None:
        totals: dict[str, float] = defaultdict(float)
        for edge in graph.edges:
            totals[edge.owned_company_id] += edge.direct_percentage
        invalid = {company: value for company, value in totals.items() if value > 100.01}
        if invalid:
            raise OwnershipTraversalError(f"ownership total exceeds 100%: {invalid}")

    @staticmethod
    def _depths(graph: OwnershipGraphResult) -> dict[str, int]:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in graph.edges:
            adjacency[edge.owned_company_id].append(edge.owner_entity_id)
        depths = {graph.root_company_id: 0}
        queue = deque([graph.root_company_id])
        while queue:
            current = queue.popleft()
            for child in adjacency.get(current, []):
                if child not in depths:
                    depths[child] = depths[current] + 1
                    queue.append(child)
        return depths

    @staticmethod
    def _detect_cycles(graph: OwnershipGraphResult) -> list[list[str]]:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in graph.edges:
            if edge.owner_entity_type == "COMPANY":
                adjacency[edge.owned_company_id].append(edge.owner_entity_id)
        cycles: list[list[str]] = []

        def visit(node: str, path: list[str]) -> None:
            for child in adjacency.get(node, []):
                if child in path:
                    cycles.append([*path[path.index(child):], child])
                else:
                    visit(child, [*path, child])

        visit(graph.root_company_id, [graph.root_company_id])
        return cycles
