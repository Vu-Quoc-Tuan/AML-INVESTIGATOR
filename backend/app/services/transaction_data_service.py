"""Backend service for transaction-ledger data used by agent tools."""

from collections.abc import Collection
from datetime import datetime

from app.data.provider import get_initialized_data_repository

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
