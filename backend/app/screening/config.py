"""Immutable business rules for deterministic screening."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScreeningConfig:
    confirmed_score: float = 0.80
    potential_score: float = 0.45
    name_weight: float = 0.45
    date_of_birth_weight: float = 0.25
    nationality_weight: float = 0.10
    identifier_weight: float = 0.55

    def __post_init__(self) -> None:
        if not 0 <= self.potential_score <= self.confirmed_score <= 1:
            raise ValueError("screening thresholds are invalid")
        weights = (
            self.name_weight,
            self.date_of_birth_weight,
            self.nationality_weight,
            self.identifier_weight,
        )
        if any(weight < 0 or weight > 1 for weight in weights):
            raise ValueError("screening weights must be in [0, 1]")
