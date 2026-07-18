"""Backend service for ownership evidence and dated ownership topology."""

from collections.abc import Collection
from datetime import date, datetime

from app.data.provider import get_initialized_data_repository

from .serialization import frame_to_records, graph_to_dict


class OwnershipDataService:
    """Expose ownership data without leaking shared NetworkX/Pandas state."""

    def ownership_records(self, company_id: str) -> list[dict[str, object]]:
        return frame_to_records(
            get_initialized_data_repository().ownership_records_for_company(company_id)
        )

    def ownership_subgraph(self, entity_ids: Collection[str]) -> dict[str, object]:
        return graph_to_dict(
            get_initialized_data_repository().ownership_subgraph(entity_ids)
        )

    def active_ownership_graph(
        self, as_of_date: str | date | datetime
    ) -> dict[str, object]:
        return graph_to_dict(
            get_initialized_data_repository().build_active_ownership_graph(as_of_date)
        )

    def ownership_neighborhood(
        self,
        company_id: str,
        as_of_date: str | date | datetime,
        max_depth: int,
    ) -> dict[str, object]:
        return graph_to_dict(
            get_initialized_data_repository().build_ownership_neighborhood(
                company_id, as_of_date, max_depth
            )
        )
