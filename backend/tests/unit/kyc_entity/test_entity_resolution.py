from app.kyc_entity.entity_resolution import EntityResolutionService


def test_alias_dob_phone_is_possible_match():
    result = EntityResolutionService().resolve_entity(
        {
            "full_name": "NGUYEN VAN AN",
            "date_of_birth": "1990-01-01",
            "phone": "0901234567",
        },
        [{
            "entity_id": "CUST-1",
            "entity_type": "CUSTOMER",
            "full_name": "Nguyễn Văn Bình",
            "aliases": ["Nguyen Van An"],
            "date_of_birth": "1990-01-01",
            "phone": "+84901234567",
        }],
    )
    assert result.candidates[0].decision == "POSSIBLE_MATCH"


def test_same_name_conflicting_national_id_is_contradiction():
    result = EntityResolutionService().resolve_entity(
        {"full_name": "Tran Van A", "national_id": "111"},
        [{
            "entity_id": "CUST-2",
            "entity_type": "CUSTOMER",
            "full_name": "Trần Văn A",
            "national_id": "222",
        }],
    )
    assert result.candidates[0].decision == "CONTRADICTION"
    assert result.contradictions[0].evidence_a != result.contradictions[0].evidence_b


def test_external_record_match_stays_limited():
    raw = {
        "external_account_id": "EXT-1",
        "masked_account_number": "****1234",
        "bank_id": "BANK-X",
        "counterparty_name": "A",
    }
    result = EntityResolutionService().resolve_entity(raw, [raw])
    candidate = result.candidates[0]
    assert candidate.decision == "EXTERNAL_ACCOUNT_RECORD_MATCH"
    assert candidate.identity_scope == "LIMITED_EXTERNAL_IDENTITY"
    assert candidate.ubo_eligible is False


def test_external_identity_cannot_override_scope_or_ubo_eligibility():
    raw = {
        "external_account_id": "EXT-ACC-FAKE",
        "entity_id": "EXT-ACC-FAKE",
        "entity_type": "CUSTOMER",
        "identity_scope": "FULL_INTERNAL",
        "full_name": "External Person",
    }
    result = EntityResolutionService().resolve_entity(raw, [raw])
    candidate = result.candidates[0]
    assert result.normalized_input.identity_scope == "LIMITED_EXTERNAL_IDENTITY"
    assert candidate.identity_scope == "LIMITED_EXTERNAL_IDENTITY"
    assert candidate.ubo_eligible is False


def test_masked_external_record_is_limited_without_external_account_id():
    normalized = EntityResolutionService().normalize_identity({
        "masked_account_number": "****1234",
        "bank_id": "BANK-X",
        "identity_scope": "FULL_INTERNAL",
    })
    assert normalized.identity_scope == "LIMITED_EXTERNAL_IDENTITY"
