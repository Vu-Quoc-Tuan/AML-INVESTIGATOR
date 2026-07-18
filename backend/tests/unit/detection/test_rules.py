from datetime import UTC, datetime

from app.detection.rules import RuleEngine
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


def event(**overrides) -> TransactionEventV1:
    values = {
        "event_id": "evt-1", "transaction_id": "tx-1",
        "occurred_at": datetime(2026, 7, 19, tzinfo=UTC),
        "ingested_at": datetime(2026, 7, 19, tzinfo=UTC),
        "source_account_ref": "src", "destination_account_ref": "dst",
        "source_bank_id": HOME_BANK_ID, "destination_bank_id": HOME_BANK_ID,
        "amount": 1_000, "currency": "USD", "direction": "INTERNAL",
        "data_visibility": "FULL_INTERNAL",
    }
    values.update(overrides)
    return TransactionEventV1.model_validate(values)


def test_missing_enrichment_has_no_hits() -> None:
    assert RuleEngine().evaluate(event()).hits == ()


def test_rule_order_is_stable_when_every_rule_hits() -> None:
    cross_border = event(
        direction="OUTBOUND", destination_bank_id="BANK-EXT-1",
        data_visibility="PAYMENT_MESSAGE_ONLY", amount=200_000,
    )
    result = RuleEngine().evaluate(cross_border, {
        "source_in_watchlist": 1, "ip_sharing_count_1h": 8,
        "dest_bank_risk_score": 9.0, "source_account_age_days": 10,
    })
    assert [hit.rule_id for hit in result.hits] == [
        "R001_HIGH_RISK_PARTY", "R002_SHARED_ACCESS",
        "R003_HIGH_VALUE_CROSS_BORDER", "R004_NEW_ACCOUNT_HIGH_VALUE",
    ]


def test_invalid_optional_numbers_are_treated_as_missing() -> None:
    assert RuleEngine().evaluate(event(), {"source_owner_risk": "unknown"}).hits == ()
