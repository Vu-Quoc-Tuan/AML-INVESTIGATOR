"""Realtime feature extraction compatible with the existing XGBoost model."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Mapping

from app.schemas.common import TransactionDirection
from app.streaming.schemas import TransactionEventV1

from .contracts import FeatureSnapshot


FEATURE_COLUMNS = (
    "amount", "is_cross_border",
    "source_txn_count_1h", "source_txn_amount_1h",
    "source_txn_count_24h", "source_txn_amount_24h",
    "dest_txn_count_1h", "dest_txn_amount_1h",
    "dest_txn_count_24h", "dest_txn_amount_24h",
    "dest_pass_through_ratio_1h", "ip_sharing_count_1h", "device_sharing_count_1h",
    "source_owner_type", "source_owner_age", "source_owner_income", "source_owner_risk",
    "source_initial_balance", "source_account_age_days", "source_bank_risk_score",
    "source_doc_rejected_or_missing", "source_in_watchlist",
    "dest_owner_type", "dest_owner_age", "dest_owner_income", "dest_owner_risk",
    "dest_initial_balance", "dest_account_age_days", "dest_bank_risk_score",
    "dest_doc_rejected_or_missing", "dest_in_watchlist", "has_relationship",
    "mismatch_cross_border_source", "mismatch_cross_border_dest",
    "mismatch_country_source", "mismatch_country_dest",
    "amt_to_expected_outflow_ratio_source", "amt_to_expected_inflow_ratio_dest",
)

_COMPUTED_COLUMNS = {
    "amount", "is_cross_border",
    "source_txn_count_1h", "source_txn_amount_1h",
    "source_txn_count_24h", "source_txn_amount_24h",
    "dest_txn_count_1h", "dest_txn_amount_1h",
    "dest_txn_count_24h", "dest_txn_amount_24h",
}


@dataclass(frozen=True)
class _Observation:
    occurred_at: datetime
    amount: float


class RealtimeFeatureExtractor:
    """Keeps a bounded, process-local 24-hour account window."""

    def __init__(self, max_events_per_account: int = 10_000) -> None:
        if max_events_per_account <= 0:
            raise ValueError("max_events_per_account must be positive")
        self._max_events = max_events_per_account
        self._outgoing: dict[str, deque[_Observation]] = defaultdict(deque)
        self._incoming: dict[str, deque[_Observation]] = defaultdict(deque)
        self._seen_event_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._max_seen_event_ids = max_events_per_account * 10
        self._lock = Lock()

    def extract(
        self,
        event: TransactionEventV1,
        enrichment: Mapping[str, Any] | None = None,
    ) -> FeatureSnapshot:
        with self._lock:
            source = self._outgoing[event.source_account_ref]
            destination = self._incoming[event.destination_account_ref]
            self._prune(source, event.occurred_at)
            self._prune(destination, event.occurred_at)

            values: dict[str, float] = {
                "amount": event.amount,
                "is_cross_border": float(
                    event.direction is not TransactionDirection.INTERNAL
                ),
                **self._window_values("source", source, event.occurred_at),
                **self._window_values("dest", destination, event.occurred_at),
            }
            provided = enrichment or {}
            imputed: list[str] = []
            for name in FEATURE_COLUMNS:
                if name in values:
                    continue
                if name in provided:
                    values[name] = _numeric(provided[name])
                else:
                    values[name] = 0.0
                    imputed.append(name)

            return FeatureSnapshot(
                names=FEATURE_COLUMNS,
                values=tuple(values[name] for name in FEATURE_COLUMNS),
                imputed_features=tuple(imputed),
            )

    def observe(self, event: TransactionEventV1) -> bool:
        """Commit one event to rolling state; replays are ignored by event_id."""

        with self._lock:
            if event.event_id in self._seen_event_ids:
                return False
            observation = _Observation(event.occurred_at, event.amount)
            source = self._outgoing[event.source_account_ref]
            destination = self._incoming[event.destination_account_ref]
            source.append(observation)
            destination.append(observation)
            while len(source) > self._max_events:
                source.popleft()
            while len(destination) > self._max_events:
                destination.popleft()
            self._seen_event_ids.add(event.event_id)
            self._seen_order.append(event.event_id)
            while len(self._seen_order) > self._max_seen_event_ids:
                self._seen_event_ids.discard(self._seen_order.popleft())
            return True

    @staticmethod
    def _prune(observations: deque[_Observation], now: datetime) -> None:
        cutoff = now - timedelta(hours=24)
        retained = [item for item in observations if item.occurred_at >= cutoff]
        observations.clear()
        observations.extend(retained)

    @staticmethod
    def _window_values(
        prefix: str, observations: deque[_Observation], now: datetime
    ) -> dict[str, float]:
        cutoff_1h = now - timedelta(hours=1)
        eligible_24h = [item for item in observations if item.occurred_at <= now]
        eligible_1h = [item for item in eligible_24h if item.occurred_at >= cutoff_1h]
        return {
            f"{prefix}_txn_count_1h": float(len(eligible_1h)),
            f"{prefix}_txn_amount_1h": sum(item.amount for item in eligible_1h),
            f"{prefix}_txn_count_24h": float(len(eligible_24h)),
            f"{prefix}_txn_amount_24h": sum(item.amount for item in eligible_24h),
        }


def _numeric(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"feature value is not numeric: {value!r}") from exc
