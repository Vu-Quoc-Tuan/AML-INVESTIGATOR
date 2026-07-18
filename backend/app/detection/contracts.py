"""Typed contracts shared by realtime detection and batch investigation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DecisionKind(StrEnum):
    ALLOWED = "ALLOWED"
    QUEUED = "QUEUED"
    BLOCKED = "BLOCKED"


class CandidateStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RunMode(StrEnum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class RunTrigger(StrEnum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleEvaluation:
    hits: tuple[RuleHit, ...] = ()

    @property
    def suspicious(self) -> bool:
        return bool(self.hits)


@dataclass(frozen=True)
class FeatureSnapshot:
    names: tuple[str, ...]
    values: tuple[float, ...]
    imputed_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.names) != len(self.values):
            raise ValueError("feature names and values must have equal length")


@dataclass(frozen=True)
class ModelPrediction:
    confidence: float
    model_version: str
    imputed_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetectionDecision:
    kind: DecisionKind
    confidence: float
    model_version: str
    rule_hits: tuple[RuleHit, ...] = ()
    imputed_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    event_id: str
    transaction_snapshot: dict[str, Any]
    decision: DetectionDecision
    status: CandidateStatus
    attempts: int

