"""Immutable business-rule configuration for Person 3."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class KycEntityConfig:
    ownership_threshold: float = 0.25
    max_ownership_depth: int = 3
    identity_match_threshold: float = 0.85
    identity_possible_threshold: float = 0.35
    identity_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "strong_identifier": 0.55,
            "name": 0.20,
            "date_of_birth": 0.10,
            "phone": 0.05,
            "email": 0.05,
            "address": 0.05,
        }
    )
    deviation_medium_ratio: float = 2.0
    deviation_high_ratio: float = 5.0
    deviation_critical_ratio: float = 10.0
    required_documents: Mapping[str, Sequence[frozenset[str]]] = field(
        default_factory=lambda: {
            "CUSTOMER": (frozenset({"NATIONAL_ID", "PASSPORT"}),),
            "COMPANY": (
                frozenset({"BUSINESS_LICENSE"}),
                frozenset({"UBO_DECLARATION"}),
            ),
        }
    )

    def __post_init__(self) -> None:
        if not 0 < self.ownership_threshold <= 1:
            raise ValueError("ownership_threshold must be in (0, 1]")
        if self.max_ownership_depth < 1:
            raise ValueError("max_ownership_depth must be at least 1")
        if not 0 <= self.identity_possible_threshold <= self.identity_match_threshold <= 1:
            raise ValueError("identity thresholds are invalid")
