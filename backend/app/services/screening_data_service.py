"""Backend service for bounded, indexed watchlist candidate lookup."""

from datetime import date

from app.data.provider import get_initialized_data_repository

from .serialization import frame_to_records


class ScreeningDataService:
    """Expose candidates only; never expose the complete watchlist."""

    def candidates(
        self,
        normalized_name: str,
        entity_type: str,
        nationalities: list[str] | None = None,
        date_of_birth: date | None = None,
        list_types: list[str] | None = None,
    ) -> list[dict[str, object]]:
        return frame_to_records(
            get_initialized_data_repository().watchlist_candidates(
                normalized_name=normalized_name,
                entity_type=entity_type,
                nationalities=nationalities,
                date_of_birth=date_of_birth,
                list_types=list_types,
            )
        )
