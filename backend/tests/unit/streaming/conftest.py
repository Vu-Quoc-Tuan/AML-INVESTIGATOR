from datetime import datetime, timezone

from app.streaming.schemas import TransactionEventV1


def make_event(**overrides) -> TransactionEventV1:
    values = {
        "event_id": "EVENT-1",
        "transaction_id": "TX-1",
        "occurred_at": datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
        "ingested_at": datetime(2026, 7, 18, 10, 0, 1, tzinfo=timezone.utc),
        "source_account_ref": "ACCT-SHB-001",
        "destination_account_ref": "ACCT-SHB-002",
        "source_bank_id": "BANK-SHB-001",
        "destination_bank_id": "BANK-SHB-001",
        "amount": 1250000.0,
        "currency": "VND",
        "direction": "INTERNAL",
        "data_visibility": "FULL_INTERNAL",
    }
    values.update(overrides)
    return TransactionEventV1.model_validate(values)
