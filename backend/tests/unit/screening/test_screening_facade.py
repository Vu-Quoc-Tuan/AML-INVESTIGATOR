import pytest
from pydantic import ValidationError

from app.data.exceptions import DataRepositoryError
from app.screening import ScreeningFacade


def payload():
    return {
        "request_id": "REQ-001",
        "subject": {
            "subject_id": "CUST-001",
            "entity_scope": "SHB_INTERNAL",
            "entity_type": "INDIVIDUAL",
            "name": "Nguyen Van An",
        },
        "screening_types": ["SANCTIONS"],
        "as_of_date": "2026-01-01",
    }


class FailingProvider:
    def candidates(self, *args, **kwargs):
        raise DataRepositoryError("screening store is unavailable")


class InvalidProvider:
    def candidates(self, *args, **kwargs):
        return [{"unexpected": "record"}]


def test_facade_returns_stable_repository_error():
    result = ScreeningFacade(FailingProvider()).screen(payload())

    assert result.status == "ERROR"
    assert result.conclusion == "UNABLE_TO_SCREEN"
    assert result.error_code == "DATA_REPOSITORY_ERROR"
    assert result.warnings == ["screening store is unavailable"]


def test_facade_returns_stable_invalid_data_error():
    result = ScreeningFacade(InvalidProvider()).screen(payload())

    assert result.status == "ERROR"
    assert result.error_code == "SCREENING_DATA_ERROR"


def test_facade_validates_input_before_invocation():
    invalid = payload()
    invalid["subject"]["unknown"] = True

    with pytest.raises(ValidationError):
        ScreeningFacade(InvalidProvider()).screen(invalid)
