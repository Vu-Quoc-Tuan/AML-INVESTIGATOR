"""Backend service for SHB entity, KYC, and relationship data."""

from collections.abc import Collection

from app.data.provider import get_initialized_data_repository

from .serialization import frame_to_records, graph_to_dict, series_to_dict


class EntityDataService:
    """Expose internal and limited external identity data without raw frames."""

    def account(self, account_id: str) -> dict[str, object] | None:
        return series_to_dict(get_initialized_data_repository().account_by_id(account_id))

    def external_account(self, external_account_id: str) -> dict[str, object] | None:
        return series_to_dict(
            get_initialized_data_repository().external_account_by_id(external_account_id)
        )

    def entity(self, entity_id: str) -> dict[str, object] | None:
        return series_to_dict(get_initialized_data_repository().entity_by_id(entity_id))

    def kyc_profile(self, entity_id: str) -> dict[str, object] | None:
        return series_to_dict(
            get_initialized_data_repository().kyc_profile_by_entity(entity_id)
        )

    def kyc_documents(self, entity_id: str) -> list[dict[str, object]]:
        return frame_to_records(
            get_initialized_data_repository().kyc_documents_by_entity(entity_id)
        )

    def relationships(self, entity_id: str) -> list[dict[str, object]]:
        return frame_to_records(
            get_initialized_data_repository().relationships_for_entity(entity_id)
        )

    def relationship_subgraph(self, entity_ids: Collection[str]) -> dict[str, object]:
        return graph_to_dict(get_initialized_data_repository().entity_subgraph(entity_ids))
