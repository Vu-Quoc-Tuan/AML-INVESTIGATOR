"""Realtime detection and deferred-investigation boundary."""

from .config import DetectionSettings
from .contracts import DecisionKind, DetectionDecision
from .risk_aggregator import aggregate

__all__ = ["DecisionKind", "DetectionDecision", "DetectionSettings", "aggregate"]
