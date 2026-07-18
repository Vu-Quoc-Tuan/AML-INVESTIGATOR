import pytest

from app.detection.config import DetectionSettings
from app.detection.contracts import (
    DecisionKind,
    ModelPrediction,
    RuleEvaluation,
    RuleHit,
)
from app.detection.risk_aggregator import aggregate


SETTINGS = DetectionSettings()


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (0.0, DecisionKind.ALLOWED),
        (0.599999, DecisionKind.ALLOWED),
        (0.60, DecisionKind.QUEUED),
        (0.989999, DecisionKind.QUEUED),
        (0.99, DecisionKind.BLOCKED),
        (1.0, DecisionKind.BLOCKED),
    ],
)
def test_exact_ml_boundaries(confidence: float, expected: DecisionKind) -> None:
    decision = aggregate(
        RuleEvaluation(), ModelPrediction(confidence, "test-model"), SETTINGS
    )
    assert decision.kind is expected


def test_rule_hit_queues_but_never_blocks_low_ml_confidence() -> None:
    hit = RuleHit("R001", "watchlist match")
    decision = aggregate(
        RuleEvaluation((hit,)), ModelPrediction(0.01, "test-model"), SETTINGS
    )
    assert decision.kind is DecisionKind.QUEUED
    assert decision.rule_hits == (hit,)


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.01, 1.01])
def test_invalid_confidence_fails_closed(confidence: float) -> None:
    with pytest.raises(ValueError, match="finite probability"):
        aggregate(RuleEvaluation(), ModelPrediction(confidence, "test-model"), SETTINGS)
