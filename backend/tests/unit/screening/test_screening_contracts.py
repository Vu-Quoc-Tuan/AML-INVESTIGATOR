import pytest
from pydantic import ValidationError

from app.schemas.screening import ScreeningResponse


def base_response():
    return {
        "request_id": "REQ-001",
        "subject_id": "CUST-001",
        "entity_scope": "SHB_INTERNAL",
        "status": "SUCCESS",
        "conclusion": "NO_MATCH",
    }


def test_contract_forbids_unknown_fields():
    data = base_response()
    data["unknown"] = True

    with pytest.raises(ValidationError):
        ScreeningResponse.model_validate(data)


def test_error_requires_error_code():
    data = base_response()
    data.update(status="ERROR", conclusion="UNABLE_TO_SCREEN")

    with pytest.raises(ValidationError):
        ScreeningResponse.model_validate(data)


def test_confirmed_match_requires_strong_candidate():
    data = base_response()
    data.update(
        conclusion="CONFIRMED_MATCH",
        candidates=[
            {
                "candidate_id": "WL-001",
                "list_type": "SANCTIONS",
                "source_name": "DEMO",
                "matched_name": "Nguyen Van An",
                "score": 0.99,
                "match_basis": "NAME_ONLY",
            }
        ],
    )

    with pytest.raises(ValidationError):
        ScreeningResponse.model_validate(data)
