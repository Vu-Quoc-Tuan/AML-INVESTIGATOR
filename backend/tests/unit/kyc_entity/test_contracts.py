import pytest
from pydantic import ValidationError

from app.schemas.kyc_entity import Contradiction, ObservedTransactionFeatures


def test_observed_metric_requires_metric_evidence():
    with pytest.raises(ValidationError):
        ObservedTransactionFeatures(
            entity_id="COMP-000008",
            window_start="2025-12-20T10:00:00Z",
            window_end="2025-12-20T10:05:00Z",
            account_ids=["ACCT-SHB-002382"],
            metrics={"total_inflow": 5_000_000_000},
            metric_evidence_ids={},
        )


def test_contradiction_requires_distinct_evidence():
    with pytest.raises(ValidationError):
        Contradiction(
            contradiction_id="C-1",
            type="FIELD_MISMATCH",
            field="name",
            declared="A",
            observed="B",
            evidence_a="EV-1",
            evidence_b="EV-1",
        )
