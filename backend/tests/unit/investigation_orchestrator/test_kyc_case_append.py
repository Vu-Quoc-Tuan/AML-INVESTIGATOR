import pytest

from app.investigation_orchestrator.state import append_kyc_contribution
from app.kyc_entity.exceptions import EvidenceContractError
from app.schemas.evidence import KycEvidence
from app.schemas.kyc_entity import KycCaseContribution, KycFinding
from app.schemas.state import SharedCaseFile


def _evidence(evidence_id="EV-1"):
    return KycEvidence(
        evidence_id=evidence_id,
        source_type="TEST",
        source_record_id="R1",
        statement="test evidence",
        visibility_level="FULL_INTERNAL",
    )


def test_exact_retry_is_idempotent():
    case = SharedCaseFile(case_id="CASE-1")
    contribution = KycCaseContribution(evidence=[_evidence()])
    once = append_kyc_contribution(case, contribution)
    twice = append_kyc_contribution(once, contribution)
    assert len(twice.evidence) == 1
    assert twice.revision == 1


def test_invalid_reference_rolls_back():
    case = SharedCaseFile(case_id="CASE-1")
    contribution = KycCaseContribution(kyc_findings=[KycFinding(
        finding_id="F1", type="X", statement="x", evidence_ids=["EV-MISSING"]
    )])
    with pytest.raises(EvidenceContractError):
        append_kyc_contribution(case, contribution)
    assert case.revision == 0
    assert case.kyc_findings == []
