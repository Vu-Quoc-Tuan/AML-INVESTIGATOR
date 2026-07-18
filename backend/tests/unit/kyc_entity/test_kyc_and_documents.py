from datetime import date

import pytest

from app.kyc_entity.document_intelligence import DocumentIntelligenceService
from app.kyc_entity.exceptions import EntityNotFoundError, EntityScopeViolationError
from app.kyc_entity.kyc_service import KycSnapshotService


AS_OF = date(2025, 12, 20)


def test_company_profile_and_exact_account_owner():
    service = KycSnapshotService()
    result = service.get_company_profile("COMP-000008", AS_OF)
    owner = service.resolve_account_owner("ACCT-SHB-002382", AS_OF)

    assert result.entity["expected_monthly_turnover"] == 300_000_000
    assert result.representative["customer_id"] == "CUST-001690"
    assert result.ownership_coverage_percentage == 100.0
    assert owner.owner_entity_id == "COMP-000008"


def test_external_account_is_rejected_for_full_kyc():
    with pytest.raises(EntityScopeViolationError):
        KycSnapshotService().resolve_account_owner("EXT-ACC-000001", AS_OF)


def test_get_documents_rejects_unknown_internal_entity():
    with pytest.raises(EntityNotFoundError, match="entity not found"):
        DocumentIntelligenceService().get_kyc_documents(
            "CUST-DOES-NOT-EXIST"
        )


def test_get_documents_keeps_external_scope_error():
    with pytest.raises(EntityScopeViolationError):
        DocumentIntelligenceService().get_kyc_documents("EXT-ACC-000001")


def test_expired_license_with_valid_replacement_is_not_missing():
    result = DocumentIntelligenceService().compare_kyc_fields("COMP-000008", AS_OF)

    assert any(
        item.type == "DOCUMENT_EXPIRED" and "EV-DOC-DOC-002015" in item.evidence_ids
        for item in result.findings
    )
    assert not any(item.type == "BUSINESS_LICENSE" for item in result.missing_documents)


def test_classify_uses_as_of_date_not_snapshot_expired_status():
    """Generator may stamp verification_status=EXPIRED at world_end.

    Historical investigation dates before expires_at must still classify VALID.
    """
    document = {
        "document_id": "DOC-HIST-1",
        "issued_at": "2025-10-20T00:00:00",
        "expires_at": "2025-11-19T00:00:00",
        "verification_status": "EXPIRED",
    }
    classify = DocumentIntelligenceService._classify

    assert classify(document, date(2025, 11, 1)) == "VALID"
    assert classify(document, date(2025, 11, 18)) == "VALID"
    # expires_at day itself remains in force under exclusive upper bound
    assert classify(document, date(2025, 11, 19)) == "VALID"
    assert classify(document, date(2025, 11, 20)) == "EXPIRED"
    assert classify(document, date(2025, 12, 20)) == "EXPIRED"


def test_historical_validity_for_seed_expired_license():
    service = DocumentIntelligenceService()
    historical = service.check_document_validity(["DOC-002015"], date(2025, 11, 1))
    current = service.check_document_validity(["DOC-002015"], AS_OF)

    assert historical.validity[0].classification == "VALID"
    assert current.validity[0].classification == "EXPIRED"
    assert not any(item.type == "DOCUMENT_EXPIRED" for item in historical.findings)
    assert any(item.type == "DOCUMENT_EXPIRED" for item in current.findings)


def test_classify_edge_matrix():
    classify = DocumentIntelligenceService._classify

    verified = {
        "issued_at": "2025-10-01T00:00:00",
        "expires_at": "2025-12-31T00:00:00",
        "verification_status": "VERIFIED",
    }
    assert classify(verified, date(2025, 9, 30)) == "NOT_YET_VALID"
    assert classify(verified, date(2025, 10, 1)) == "VALID"
    assert classify(verified, date(2025, 12, 31)) == "VALID"
    assert classify(verified, date(2026, 1, 1)) == "EXPIRED"
    # Date wins over a still-VERIFIED snapshot after expiry.
    assert classify(verified, date(2026, 6, 1)) == "EXPIRED"

    assert classify({**verified, "verification_status": "PENDING"}, date(2025, 11, 1)) == "UNVERIFIED"
    assert classify({**verified, "verification_status": None}, date(2025, 11, 1)) == "UNVERIFIED"
    assert classify({**verified, "verification_status": "expired"}, date(2025, 11, 1)) == "VALID"

    assert (
        classify(
            {
                "issued_at": "2025-12-01",
                "expires_at": "2025-11-01",
                "verification_status": "VERIFIED",
            },
            date(2025, 11, 15),
        )
        == "INVALID_DATES"
    )
    assert (
        classify(
            {
                "issued_at": None,
                "expires_at": None,
                "verification_status": "EXPIRED",
            },
            date(2025, 11, 1),
        )
        == "EXPIRED"
    )
    assert (
        classify(
            {
                "issued_at": None,
                "expires_at": None,
                "verification_status": "VERIFIED",
            },
            date(2025, 11, 1),
        )
        == "VALID"
    )
    assert (
        classify(
            {
                "issued_at": "not-a-date",
                "expires_at": "2025-12-31",
                "verification_status": "VERIFIED",
            },
            date(2025, 11, 1),
        )
        == "INVALID_DATES"
    )


def test_missing_documents_respect_historical_validity():
    service = DocumentIntelligenceService()
    only_expired_snapshot = [
        {
            "document_id": "D1",
            "document_type": "BUSINESS_LICENSE",
            "entity_id": "COMP-000008",
            "issued_at": "2024-01-01",
            "expires_at": "2024-06-01",
            "verification_status": "EXPIRED",
        }
    ]
    missing_now = service.find_missing_documents(
        "COMP-000008", "COMPANY", only_expired_snapshot, date(2025, 12, 20)
    )
    missing_then = service.find_missing_documents(
        "COMP-000008", "COMPANY", only_expired_snapshot, date(2024, 3, 1)
    )
    assert any(item.type == "BUSINESS_LICENSE" for item in missing_now)
    assert not any(item.type == "BUSINESS_LICENSE" for item in missing_then)


def test_compare_kyc_fields_historical_skips_false_expired_finding():
    service = DocumentIntelligenceService()
    historical = service.compare_kyc_fields("COMP-000008", date(2025, 11, 1))
    current = service.compare_kyc_fields("COMP-000008", AS_OF)

    assert not any(
        item.type == "DOCUMENT_EXPIRED" and "DOC-002015" in "".join(item.evidence_ids)
        for item in historical.findings
    )
    assert any(
        item.type == "DOCUMENT_EXPIRED" and "DOC-002015" in "".join(item.evidence_ids)
        for item in current.findings
    )
    assert not any(item.type == "BUSINESS_LICENSE" for item in historical.missing_documents)
    assert not any(item.type == "BUSINESS_LICENSE" for item in current.missing_documents)


def test_ownership_requires_valid_support_document_at_as_of(monkeypatch):
    from app.kyc_entity.ownership_ubo import OwnershipUboService

    real_classify = DocumentIntelligenceService._classify

    def expired_support(document, as_of_date):
        if str(document.get("document_id")) == "DOC-002098":
            return "EXPIRED"
        return real_classify(document, as_of_date)

    monkeypatch.setattr(
        DocumentIntelligenceService, "_classify", staticmethod(expired_support)
    )
    graph = OwnershipUboService().build_ownership_graph("COMP-000008", AS_OF, 3)
    assert graph.edges
    assert all(not edge.verified for edge in graph.edges)
    assert OwnershipUboService().calculate_ubo(graph, 0.25).identified_ubos == []
