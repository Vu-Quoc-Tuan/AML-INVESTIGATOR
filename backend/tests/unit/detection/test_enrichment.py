from datetime import UTC, datetime
from pathlib import Path

from app.detection.enrichment import StaticEnrichmentProvider
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


def test_generated_data_enriches_real_mock_account_pair() -> None:
    data_path = Path(__file__).resolve().parents[3] / "data" / "generated"
    provider = StaticEnrichmentProvider(data_path)
    occurred_at = datetime(2026, 7, 19, tzinfo=UTC)
    event = TransactionEventV1.model_validate({
        "event_id": "evt", "transaction_id": "tx", "occurred_at": occurred_at,
        "ingested_at": occurred_at, "source_account_ref": "ACCT-SHB-000001",
        "destination_account_ref": "EXT-ACC-000001", "source_bank_id": HOME_BANK_ID,
        "destination_bank_id": "BANK-TCB-EXT", "amount": 100_000, "currency": "VND",
        "direction": "OUTBOUND", "data_visibility": "PAYMENT_MESSAGE_ONLY",
    })
    result = provider(event)
    assert result["source_owner_age"] > 0
    assert result["source_initial_balance"] > 0
    assert 0 <= result["source_owner_risk"] <= 2
    assert result["dest_account_age_days"] > 0
    assert result["source_bank_risk_score"] >= 0
