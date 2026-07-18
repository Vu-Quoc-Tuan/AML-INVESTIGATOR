"""Pure aggregation of rule and ML branch results."""

from __future__ import annotations

import math

from .config import DetectionSettings
from .contracts import (
    DecisionKind,
    DetectionDecision,
    ModelPrediction,
    RuleEvaluation,
)


def aggregate(
    rules: RuleEvaluation,
    prediction: ModelPrediction,
    settings: DetectionSettings,
) -> DetectionDecision:
    confidence = prediction.confidence
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("model confidence must be a finite probability")

    if confidence >= settings.ml_block_threshold:
        kind = DecisionKind.BLOCKED
    elif rules.suspicious or confidence >= settings.ml_queue_threshold:
        kind = DecisionKind.QUEUED
    else:
        kind = DecisionKind.ALLOWED

    return DetectionDecision(
        kind=kind,
        confidence=confidence,
        model_version=prediction.model_version,
        rule_hits=rules.hits,
        imputed_features=prediction.imputed_features,
    )
