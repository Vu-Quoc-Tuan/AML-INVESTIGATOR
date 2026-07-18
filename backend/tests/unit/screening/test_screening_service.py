from datetime import date

from app.schemas.screening import ScreeningRequest
from app.screening.service import ScreeningService


class StubProvider:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def candidates(
        self,
        normalized_name,
        entity_type,
        nationalities=None,
        date_of_birth=None,
        list_types=None,
    ):
        self.calls.append((normalized_name, entity_type, list_types))
        return list(self.rows)


def request(**subject_overrides):
    subject = {
        "subject_id": "CUST-001",
        "entity_scope": "SHB_INTERNAL",
        "entity_type": "INDIVIDUAL",
        "name": "Nguyễn Văn An",
        "date_of_birth": "1980-05-05",
        "nationalities": ["VN"],
    }
    subject.update(subject_overrides)
    return ScreeningRequest.model_validate(
        {
            "request_id": "REQ-001",
            "subject": subject,
            "screening_types": ["SANCTIONS", "PEP"],
            "as_of_date": "2026-01-01",
        }
    )


def candidate(**overrides):
    row = {
        "watchlist_id": "WL-001",
        "list_type": "SANCTIONS",
        "full_name": "Nguyen Van An",
        "aliases": [],
        "date_of_birth": "1980-05-05",
        "nationalities": ["VN"],
        "document_numbers": [],
        "company_registration_number": None,
        "source_name": "DEMO-SANCTIONS-LIST",
        "effective_from": "2020-01-01",
        "effective_to": None,
        "status": "ACTIVE",
        "screening_dependency": "available",
    }
    row.update(overrides)
    return row


def test_exact_identifier_match_is_confirmed_and_evidenced():
    provider = StubProvider([candidate(document_numbers=["P-12345"])])

    result = ScreeningService(provider).screen(request(passport_number="P 12345"))

    assert result.status == "SUCCESS"
    assert result.conclusion == "CONFIRMED_MATCH"
    assert result.candidates[0].match_basis == "IDENTIFIER"
    assert result.candidates[0].evidence_ids == ["EV-SCREENING-WL-001"]
    assert result.evidence[0].source_record_id == "WL-001"


def test_name_dob_and_nationality_are_multi_attribute_confirmed_match():
    result = ScreeningService(StubProvider([candidate()])).screen(request())

    assert result.status == "SUCCESS"
    assert result.conclusion == "CONFIRMED_MATCH"
    assert result.candidates[0].match_basis == "MULTI_ATTRIBUTE"
    assert result.candidates[0].score == 0.8


def test_name_only_is_potential_not_confirmed():
    row = candidate(date_of_birth=None, nationalities=[])

    result = ScreeningService(StubProvider([row])).screen(
        request(date_of_birth=None, nationalities=[])
    )

    assert result.status == "INCONCLUSIVE"
    assert result.conclusion == "POTENTIAL_MATCH"
    assert result.candidates[0].match_basis == "NAME_ONLY"


def test_conflicting_attributes_prevent_confirmed_match():
    row = candidate(
        date_of_birth="1970-01-01",
        nationalities=["XX"],
        document_numbers=["OTHER-ID"],
    )

    result = ScreeningService(StubProvider([row])).screen(
        request(passport_number="P-12345")
    )

    assert result.conclusion == "POTENTIAL_MATCH"
    assert result.candidates[0].conflicting_attributes == [
        "identifier",
        "date_of_birth",
        "nationality",
    ]


def test_no_candidates_is_no_data_not_no_match():
    result = ScreeningService(StubProvider([])).screen(request())

    assert result.status == "NO_DATA"
    assert result.conclusion == "UNABLE_TO_SCREEN"
    assert result.warnings == ["NO_CANDIDATE_DATA"]


def test_expired_candidate_yields_successful_no_match():
    row = candidate(effective_to="2025-12-31")

    result = ScreeningService(StubProvider([row])).screen(request())

    assert result.status == "SUCCESS"
    assert result.conclusion == "NO_MATCH"
    assert result.warnings == ["NO_ACTIVE_CANDIDATES"]


def test_unavailable_dependency_is_inconclusive_not_no_match():
    row = candidate(screening_dependency="unavailable")

    result = ScreeningService(StubProvider([row])).screen(request())

    assert result.status == "INCONCLUSIVE"
    assert result.conclusion == "UNABLE_TO_SCREEN"
    assert result.warnings == ["SCREENING_DEPENDENCY_UNAVAILABLE"]


def test_external_observed_scope_is_preserved_in_evidence():
    result = ScreeningService(StubProvider([candidate()])).screen(
        request(entity_scope="EXTERNAL_OBSERVED")
    )

    assert result.entity_scope == "EXTERNAL_OBSERVED"
    assert result.evidence[0].visibility_level == "EXTERNAL_OBSERVED"


def test_organization_subject_maps_to_company_lookup():
    provider = StubProvider(
        [
            candidate(
                full_name="Demo Holdings",
                company_registration_number="REG-123",
                date_of_birth=None,
                nationalities=[],
            )
        ]
    )

    result = ScreeningService(provider).screen(
        request(
            entity_type="ORGANIZATION",
            name="Demo Holdings",
            date_of_birth=None,
            nationalities=[],
            registration_number="REG123",
        )
    )

    assert provider.calls == [("DEMO HOLDINGS", "COMPANY", ["SANCTIONS", "PEP"])]
    assert result.conclusion == "CONFIRMED_MATCH"


def test_candidate_limit_is_enforced_and_warned():
    rows = [candidate(watchlist_id=f"WL-{index:03d}") for index in range(25)]

    result = ScreeningService(StubProvider(rows)).screen(request())

    assert len(result.candidates) == 20
    assert len(result.evidence) == 20
    assert result.warnings == ["CANDIDATE_LIMIT_REACHED"]


def test_request_and_response_are_json_safe():
    result = ScreeningService(StubProvider([candidate()])).screen(request())

    assert result.model_dump(mode="json")["evidence"][0]["payload"][
        "effective_from"
    ] == "2020-01-01"
    assert request().as_of_date == date(2026, 1, 1)
