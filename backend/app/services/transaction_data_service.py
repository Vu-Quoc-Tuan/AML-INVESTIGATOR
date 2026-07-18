from collections.abc import Collection
from datetime import datetime

from app.data.provider import get_initialized_data_repository
from app.transaction_investigation import (
    get_account_transactions,
    trace_funds,
    detect_fan_in_fan_out,
    detect_rapid_pass_through,
    detect_structuring,
    detect_cycles,
    find_common_funding_sources,
    find_common_destinations,
    find_shared_identifiers,
    find_coordinated_amounts,
    detect_round_tripping,
    build_case_subgraph,
    calculate_graph_risk,
)
from app.schemas.common import TraceDirection
from .serialization import frame_to_records, graph_to_dict

class TransactionDataService:
    """Expose transaction data as JSON-safe structures only."""

    def transactions_for_account(
        self,
        account_id: str,
        start_time: str | datetime | None = None,
        end_time: str | datetime | None = None,
        direction: str | None = None,
    ) -> list[dict[str, object]]:
        repository = get_initialized_data_repository()
        return frame_to_records(
            repository.transactions_for_account(
                account_id,
                start_time=start_time,
                end_time=end_time,
                direction=direction,
            )
        )

    def transaction_subgraph(self, account_ids: Collection[str]) -> dict[str, object]:
        repository = get_initialized_data_repository()
        return graph_to_dict(repository.transaction_subgraph(account_ids))

    def get_account_transactions(self, account_id: str, start_time: str | datetime | None = None, end_time: str | datetime | None = None, direction: str | None = None) -> dict[str, object]:
        return get_account_transactions(account_id, start_time, end_time, direction).model_dump(mode="json")

    def trace_funds(self, seed_account_ids: list[str], direction: str, max_depth: int = 3, start_time: str | datetime | None = None, end_time: str | datetime | None = None) -> dict[str, object]:
        return trace_funds(seed_account_ids, direction, max_depth, start_time, end_time).model_dump(mode="json")

    def detect_fan_in_fan_out(self, account_id: str, time_window_hours: float = 24.0) -> dict[str, object]:
        return detect_fan_in_fan_out(account_id, time_window_hours).model_dump(mode="json")

    def detect_rapid_pass_through(self, account_id: str, time_window_hours: float = 24.0) -> dict[str, object]:
        return detect_rapid_pass_through(account_id, time_window_hours).model_dump(mode="json")

    def detect_structuring(self, account_id: str, time_window_hours: float = 24.0) -> dict[str, object]:
        return detect_structuring(account_id, time_window_hours).model_dump(mode="json")

    def detect_cycles(self, seed_account_id: str, max_depth: int = 5) -> dict[str, object]:
        return detect_cycles(seed_account_id, max_depth).model_dump(mode="json")

    def find_common_funding_sources(self, account_ids: list[str], lookback_period_hours: float = 24.0) -> dict[str, object]:
        return find_common_funding_sources(account_ids, lookback_period_hours).model_dump(mode="json")

    def find_common_destinations(self, account_ids: list[str], lookforward_period_hours: float = 24.0) -> dict[str, object]:
        return find_common_destinations(account_ids, lookforward_period_hours).model_dump(mode="json")

    def find_shared_identifiers(self, account_ids: list[str], identifier_types: list[str] | None = None) -> dict[str, object]:
        return find_shared_identifiers(account_ids, identifier_types).model_dump(mode="json")

    def find_coordinated_amounts(self, account_id: str, time_window_hours: float = 24.0) -> dict[str, object]:
        return find_coordinated_amounts(account_id, time_window_hours).model_dump(mode="json")

    def detect_round_tripping(self, account_id: str, time_window_hours: float = 24.0) -> dict[str, object]:
        return detect_round_tripping(account_id, time_window_hours).model_dump(mode="json")

    def build_case_subgraph(self, seed_entity_ids: list[str], max_depth: int = 2, start_time: str | datetime | None = None, end_time: str | datetime | None = None) -> dict[str, object]:
        return build_case_subgraph(seed_entity_ids, max_depth, start_time, end_time).model_dump(mode="json")

    def calculate_graph_risk(self, graph_snapshot: dict) -> dict[str, object]:
        return calculate_graph_risk(graph_snapshot).model_dump(mode="json")
