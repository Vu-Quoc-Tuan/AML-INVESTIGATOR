"""Atomic Shared Case File contribution append."""

from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from app.kyc_entity.exceptions import EvidenceConflictError
from app.schemas.kyc_entity import KycCaseContribution, VisibilitySummary
from app.schemas.state import SharedCaseFile

from .evidence_ledger import EvidenceLedger
from .evidence_validator import validate_contribution_evidence

ModelT = TypeVar("ModelT", bound=BaseModel)


def _deduplicate(
    existing: list[ModelT], incoming: list[ModelT], key: Callable[[ModelT], str]
) -> list[ModelT]:
    result = list(existing)
    seen = {key(item): item for item in existing}
    for item in incoming:
        identifier = key(item)
        if identifier in seen and seen[identifier] != item:
            raise EvidenceConflictError(
                f"stable result ID {identifier} has conflicting content"
            )
        if identifier not in seen:
            result.append(item)
            seen[identifier] = item
    return result


def append_kyc_contribution(
    case: SharedCaseFile, contribution: KycCaseContribution
) -> SharedCaseFile:
    """Validate first, then return a fully appended deep copy."""

    validate_contribution_evidence(case, contribution)
    evidence = EvidenceLedger.append_many(case.evidence, contribution.evidence)
    updates = {
        "normalized_entities": _deduplicate(
            case.normalized_entities, contribution.normalized_entities,
            lambda item: item.resolution_id,
        ),
        "kyc_findings": _deduplicate(
            case.kyc_findings, contribution.kyc_findings,
            lambda item: item.finding_id,
        ),
        "profile_mismatches": _deduplicate(
            case.profile_mismatches, contribution.profile_mismatches,
            lambda item: item.mismatch_id,
        ),
        "ownership_graphs": _deduplicate(
            case.ownership_graphs, contribution.ownership_graphs,
            lambda item: item.graph_id,
        ),
        "identified_ubos": _deduplicate(
            case.identified_ubos, contribution.identified_ubos,
            lambda item: item.ubo_result_id,
        ),
        "ownership_gaps": _deduplicate(
            case.ownership_gaps, contribution.ownership_gaps,
            lambda item: item.gap_id,
        ),
        "missing_documents": _deduplicate(
            case.missing_documents, contribution.missing_documents,
            lambda item: item.missing_document_id,
        ),
        "contradictions": _deduplicate(
            case.contradictions, contribution.contradictions,
            lambda item: item.contradiction_id,
        ),
        "evidence": evidence,
        "visibility_summary": VisibilitySummary(
            internal_entities=sorted(set(
                case.visibility_summary.internal_entities
                + contribution.visibility_summary.internal_entities
            )),
            external_entities=sorted(set(
                case.visibility_summary.external_entities
                + contribution.visibility_summary.external_entities
            )),
        ),
    }
    changed = any(getattr(case, key) != value for key, value in updates.items())
    return case.model_copy(
        update={**updates, "revision": case.revision + (1 if changed else 0)},
        deep=True,
    )
