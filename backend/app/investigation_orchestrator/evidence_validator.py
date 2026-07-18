"""Cross-reference validation for Person 3 case contributions."""

from app.kyc_entity.exceptions import EvidenceContractError
from app.schemas.kyc_entity import KycCaseContribution
from app.schemas.state import SharedCaseFile


def referenced_evidence_ids(contribution: KycCaseContribution) -> set[str]:
    result: set[str] = set()
    for collection in (
        contribution.kyc_findings,
        contribution.profile_mismatches,
        contribution.identified_ubos,
        contribution.ownership_gaps,
    ):
        for item in collection:
            result.update(item.evidence_ids)
    for graph in contribution.ownership_graphs:
        for edge in graph.edges:
            result.update(edge.evidence_ids)
    for item in contribution.contradictions:
        result.add(item.evidence_a)
        result.add(item.evidence_b)
        result.update(item.additional_evidence_ids)
    return result


def validate_contribution_evidence(
    case: SharedCaseFile, contribution: KycCaseContribution
) -> None:
    available = {item.evidence_id for item in case.evidence}
    available.update(item.evidence_id for item in contribution.evidence)
    missing = sorted(referenced_evidence_ids(contribution) - available)
    if missing:
        raise EvidenceContractError(f"contribution references missing evidence: {missing}")
