"""Fast, deterministic rules used by the realtime detection branch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.schemas.common import TransactionDirection
from app.streaming.schemas import TransactionEventV1

from .contracts import RuleEvaluation, RuleHit


@dataclass(frozen=True)
class RuleSettings:
    high_value_amount: float = 100_000.0
    high_owner_risk_level: float = 2.0
    high_bank_risk_score: float = 7.5
    max_ip_sharing_1h: int = 5
    max_device_sharing_1h: int = 5
    new_account_days: int = 30


class RuleEngine:
    def __init__(self, settings: RuleSettings | None = None) -> None:
        self.settings = settings or RuleSettings()

    def evaluate(
        self,
        event: TransactionEventV1,
        enrichment: Mapping[str, Any] | None = None,
    ) -> RuleEvaluation:
        data = enrichment or {}
        hits: list[RuleHit] = []

        source_risk = _number(data.get("source_owner_risk"))
        destination_risk = _number(data.get("dest_owner_risk"))
        if (
            bool(data.get("source_in_watchlist"))
            or bool(data.get("dest_in_watchlist"))
            or source_risk >= self.settings.high_owner_risk_level
            or destination_risk >= self.settings.high_owner_risk_level
        ):
            hits.append(
                RuleHit(
                    "R001_HIGH_RISK_PARTY",
                    "A party is watchlisted or has a high risk score",
                    {
                        "source_watchlisted": bool(data.get("source_in_watchlist")),
                        "destination_watchlisted": bool(data.get("dest_in_watchlist")),
                    },
                )
            )

        ip_count = int(_number(data.get("ip_sharing_count_1h")))
        device_count = int(_number(data.get("device_sharing_count_1h")))
        if (
            ip_count > self.settings.max_ip_sharing_1h
            or device_count > self.settings.max_device_sharing_1h
        ):
            hits.append(
                RuleHit(
                    "R002_SHARED_ACCESS",
                    "IP or device sharing exceeds the realtime limit",
                    {"ip_count_1h": ip_count, "device_count_1h": device_count},
                )
            )

        is_cross_border = event.direction is not TransactionDirection.INTERNAL
        bank_risk = max(
            _number(data.get("source_bank_risk_score")),
            _number(data.get("dest_bank_risk_score")),
        )
        if (
            is_cross_border
            and event.amount >= self.settings.high_value_amount
            and bank_risk >= self.settings.high_bank_risk_score
        ):
            hits.append(
                RuleHit(
                    "R003_HIGH_VALUE_CROSS_BORDER",
                    "High-value cross-border transfer involves a high-risk bank",
                    {"amount": event.amount, "bank_risk_score": bank_risk},
                )
            )

        source_age_days = int(_number(data.get("source_account_age_days")))
        if (
            event.amount >= self.settings.high_value_amount
            and 0 < source_age_days <= self.settings.new_account_days
        ):
            hits.append(
                RuleHit(
                    "R004_NEW_ACCOUNT_HIGH_VALUE",
                    "High-value transfer originates from a newly opened account",
                    {"amount": event.amount, "source_account_age_days": source_age_days},
                )
            )

        return RuleEvaluation(tuple(hits))


def _number(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
