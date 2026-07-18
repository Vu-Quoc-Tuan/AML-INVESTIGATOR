from datetime import UTC, datetime, timedelta

from app.detection.features import FEATURE_COLUMNS, RealtimeFeatureExtractor
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


NOW = datetime(2026, 7, 19, 12, tzinfo=UTC)


def event(event_id: str, occurred_at=NOW, amount=100.0) -> TransactionEventV1:
    return TransactionEventV1.model_validate({
        "event_id": event_id, "transaction_id": f"tx-{event_id}",
        "occurred_at": occurred_at, "ingested_at": occurred_at,
        "source_account_ref": "src", "destination_account_ref": "dst",
        "source_bank_id": HOME_BANK_ID, "destination_bank_id": HOME_BANK_ID,
        "amount": amount, "currency": "VND", "direction": "INTERNAL",
        "data_visibility": "FULL_INTERNAL",
    })


def as_dict(snapshot):
    return dict(zip(snapshot.names, snapshot.values, strict=True))


def test_exact_legacy_feature_contract_and_zero_imputation() -> None:
    snapshot = RealtimeFeatureExtractor().extract(event("1"))
    assert len(FEATURE_COLUMNS) == 38
    assert snapshot.names == FEATURE_COLUMNS
    assert "source_owner_age" in snapshot.imputed_features
    assert "amount" not in snapshot.imputed_features


def test_current_event_does_not_count_itself_but_counts_on_next_event() -> None:
    extractor = RealtimeFeatureExtractor()
    first = as_dict(extractor.extract(event("1", amount=25)))
    extractor.observe(event("1", amount=25))
    second = as_dict(extractor.extract(event("2", NOW + timedelta(minutes=5), 75)))
    assert first["source_txn_count_1h"] == 0
    assert second["source_txn_count_1h"] == 1
    assert second["source_txn_amount_1h"] == 25
    assert second["dest_txn_count_24h"] == 1


def test_observations_older_than_24_hours_are_pruned() -> None:
    extractor = RealtimeFeatureExtractor()
    extractor.observe(event("old", NOW - timedelta(hours=25)))
    values = as_dict(extractor.extract(event("now")))
    assert values["source_txn_count_24h"] == 0


def test_enrichment_fills_feature_without_marking_it_imputed() -> None:
    snapshot = RealtimeFeatureExtractor().extract(
        event("1"), {"source_owner_age": 41}
    )
    assert as_dict(snapshot)["source_owner_age"] == 41
    assert "source_owner_age" not in snapshot.imputed_features


def test_observe_is_idempotent_for_kafka_replay() -> None:
    extractor = RealtimeFeatureExtractor()
    item = event("same", amount=25)
    assert extractor.observe(item) is True
    assert extractor.observe(item) is False
    values = as_dict(extractor.extract(event("next", NOW + timedelta(minutes=1))))
    assert values["source_txn_count_1h"] == 1
