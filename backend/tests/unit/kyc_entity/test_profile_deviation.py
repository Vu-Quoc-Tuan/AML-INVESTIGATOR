from datetime import date

import pytest

from app.kyc_entity.exceptions import EvidenceContractError
from app.kyc_entity.profile_deviation import ProfileDeviationService
from app.schemas.kyc_entity import ObservedTransactionFeatures


def _observed(entity_id="COMP-000008", accounts=None):
    return ObservedTransactionFeatures(
        entity_id=entity_id,
        window_start="2025-12-20T10:00:00Z",
        window_end="2025-12-20T10:05:00Z",
        account_ids=accounts or ["ACCT-SHB-002382"],
        metrics={
            "total_inflow": 5_000_000_000,
            "cross_border_observed": True,
            "observed_countries": ["VN", "SG"],
        },
        metric_evidence_ids={
            "total_inflow": ["EV-TX-IN-1"],
            "cross_border_observed": ["EV-TX-XB-1"],
            "observed_countries": ["EV-TX-XB-1"],
        },
    )


def test_main_turnover_is_critical_with_two_sided_evidence():
    result = ProfileDeviationService().compare_profile_with_observed_behavior(
        "COMP-000008", _observed(), date(2025, 12, 20)
    )
    turnover = next(item for item in result.profile_mismatches if item.type == "TURNOVER_DEVIATION")
    assert turnover.severity == "CRITICAL"
    assert "EV-KYC-KYC-002008" in turnover.evidence_ids
    assert "EV-TX-IN-1" in turnover.evidence_ids
    assert not any(item.type == "CROSS_BORDER_EXPECTATION_MISMATCH" for item in result.profile_mismatches)


def test_observed_subject_must_match():
    with pytest.raises(EvidenceContractError):
        ProfileDeviationService().compare_profile_with_observed_behavior(
            "COMP-000008", _observed("COMP-OTHER"), date(2025, 12, 20)
        )


def test_unexpected_cross_border_creates_high_finding():
    observed = ObservedTransactionFeatures(
        entity_id="CUST-000001",
        window_start="2025-12-20T10:00:00Z",
        window_end="2025-12-20T10:05:00Z",
        account_ids=["ACCT-SHB-000001"],
        metrics={"cross_border_observed": True},
        metric_evidence_ids={"cross_border_observed": ["EV-TX-XB-2"]},
    )
    result = ProfileDeviationService().compare_profile_with_observed_behavior(
        "CUST-000001", observed, date(2025, 12, 20)
    )
    mismatch = next(
        item for item in result.profile_mismatches
        if item.type == "CROSS_BORDER_EXPECTATION_MISMATCH"
    )
    assert mismatch.severity == "HIGH"
    assert "EV-TX-XB-2" in mismatch.evidence_ids
