"""Public entry point for the standalone screening agent."""

from app.data.exceptions import DataRepositoryError, DataRepositoryNotInitializedError
from app.schemas.screening import ScreeningRequest, ScreeningResponse
from app.services.screening_data_service import ScreeningDataService

from .service import CandidateProvider, ScreeningService


class ScreeningFacade:
    def __init__(self, candidate_provider: CandidateProvider | None = None) -> None:
        self.service = ScreeningService(candidate_provider or ScreeningDataService())

    def screen(self, request: ScreeningRequest | dict[str, object]) -> ScreeningResponse:
        parsed = (
            request
            if isinstance(request, ScreeningRequest)
            else ScreeningRequest.model_validate(request)
        )
        try:
            return self.service.screen(parsed)
        except DataRepositoryNotInitializedError as exc:
            return self._error(parsed, "DATA_REPOSITORY_NOT_INITIALIZED", str(exc))
        except DataRepositoryError as exc:
            return self._error(parsed, "DATA_REPOSITORY_ERROR", str(exc))
        except (KeyError, TypeError, ValueError) as exc:
            return self._error(parsed, "SCREENING_DATA_ERROR", str(exc))

    @staticmethod
    def _error(
        request: ScreeningRequest, error_code: str, message: str
    ) -> ScreeningResponse:
        return ScreeningResponse(
            request_id=request.request_id,
            subject_id=request.subject.subject_id,
            entity_scope=request.subject.entity_scope,
            status="ERROR",
            conclusion="UNABLE_TO_SCREEN",
            warnings=[message],
            error_code=error_code,
        )
