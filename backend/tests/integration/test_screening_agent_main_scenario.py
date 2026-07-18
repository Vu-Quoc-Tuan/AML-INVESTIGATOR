import json
from pathlib import Path

from app.data.provider import (
    _reset_data_repository_for_testing,
    initialize_data_repository,
)
from app.screening import ScreeningFacade


def test_screening_agent_uses_bounded_repository_lookup():
    generated_data_path = Path(__file__).resolve().parents[2] / "data" / "generated"
    _reset_data_repository_for_testing()
    initialize_data_repository(generated_data_path)
    with (generated_data_path / "watchlist_entries.jsonl").open(encoding="utf-8") as source:
        entry = json.loads(source.readline())

    is_organization = bool(entry.get("company_registration_number"))
    subject = {
        "subject_id": "SUBJECT-INTEGRATION-001",
        "entity_scope": "SHB_INTERNAL",
        "entity_type": "ORGANIZATION" if is_organization else "INDIVIDUAL",
        "name": entry["full_name"],
        "date_of_birth": entry.get("date_of_birth"),
        "nationalities": entry.get("nationalities", []),
        "registration_number": entry.get("company_registration_number"),
    }

    result = ScreeningFacade().screen(
        {
            "request_id": "REQ-INTEGRATION-001",
            "subject": subject,
            "screening_types": [entry["list_type"]],
            "as_of_date": "2025-12-31",
        }
    )

    assert result.status == "SUCCESS"
    assert result.conclusion == "CONFIRMED_MATCH"
    assert result.candidates[0].candidate_id == entry["watchlist_id"]
    assert result.evidence[0].source_record_id == entry["watchlist_id"]
    _reset_data_repository_for_testing()
