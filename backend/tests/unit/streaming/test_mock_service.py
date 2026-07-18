from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.streaming.config import KafkaSettings
from app.streaming.mock_service import (
    AccountRoster,
    ExternalAccountRef,
    MockTransactionFactory,
    load_account_roster,
    run_mock_publisher,
)
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


FIXED_TIME = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)
FIXTURE_ROSTER = AccountRoster(
    internal_account_ids=("ACCT-SHB-000001", "ACCT-SHB-000002", "ACCT-SHB-000003"),
    external_accounts=(
        ExternalAccountRef("EXT-ACC-000001", "BANK-TCB-EXT"),
        ExternalAccountRef("EXT-ACC-000002", "BANK-MBB-EXT"),
    ),
)


class FakeAck:
    def __init__(self, producer):
        self.producer = producer

    def get(self, timeout):
        self.producer.ack_count += 1
        return None


class FakeProducer:
    def __init__(self):
        self.sent = []
        self.ack_count = 0

    def send(self, topic, *, key, value):
        self.sent.append((topic, key, value))
        return FakeAck(self)


def test_mock_factory_emits_unique_valid_events_from_roster():
    factory = MockTransactionFactory(
        seed=42, clock=lambda: FIXED_TIME, roster=FIXTURE_ROSTER
    )
    first = factory.next_event()
    second = factory.next_event()
    third = factory.next_event()
    assert len({first.event_id, second.event_id, third.event_id}) == 3
    assert [first.direction.value, second.direction.value, third.direction.value] == [
        "INTERNAL",
        "OUTBOUND",
        "INBOUND",
    ]
    for event in (first, second, third):
        assert event.amount > 0
        TransactionEventV1.model_validate(event.model_dump())

    assert first.source_account_ref in FIXTURE_ROSTER.internal_account_ids
    assert first.destination_account_ref in FIXTURE_ROSTER.internal_account_ids
    assert first.source_account_ref != first.destination_account_ref

    assert second.source_account_ref in FIXTURE_ROSTER.internal_account_ids
    assert second.destination_account_ref.startswith("EXT-ACC-")
    assert second.destination_bank_id in {"BANK-TCB-EXT", "BANK-MBB-EXT"}

    assert third.destination_account_ref in FIXTURE_ROSTER.internal_account_ids
    assert third.source_account_ref.startswith("EXT-ACC-")


def test_mock_factory_is_reproducible_for_same_seed():
    first = MockTransactionFactory(
        seed=7, clock=lambda: FIXED_TIME, roster=FIXTURE_ROSTER
    ).next_event()
    second = MockTransactionFactory(
        seed=7, clock=lambda: FIXED_TIME, roster=FIXTURE_ROSTER
    ).next_event()
    assert first == second


def test_load_account_roster_from_generated_data():
    data_path = Path(__file__).resolve().parents[3] / "data" / "generated"
    if not (data_path / "accounts.csv").is_file():
        pytest.skip("generated accounts.csv not present")
    roster = load_account_roster(data_path)
    assert len(roster.internal_account_ids) >= 2
    assert roster.external_accounts
    event = MockTransactionFactory(
        seed=1, clock=lambda: FIXED_TIME, roster=roster
    ).next_event()
    assert event.source_bank_id == HOME_BANK_ID or event.destination_bank_id == HOME_BANK_ID
    TransactionEventV1.model_validate(event.model_dump())


def test_mock_publisher_waits_for_ack_and_honors_limit():
    producer = FakeProducer()
    count = run_mock_publisher(
        KafkaSettings(),
        interval_seconds=0,
        limit=3,
        stop_requested=lambda: False,
        producer=producer,
        factory=MockTransactionFactory(seed=42, roster=FIXTURE_ROSTER),
    )
    assert count == 3
    assert producer.ack_count == 3
    assert all(item[0] == "aml.transactions.raw.v1" for item in producer.sent)


def test_mock_publisher_can_stop_before_first_event():
    producer = FakeProducer()
    count = run_mock_publisher(
        KafkaSettings(),
        0,
        None,
        lambda: True,
        producer=producer,
        factory=MockTransactionFactory(seed=42, roster=FIXTURE_ROSTER),
    )
    assert count == 0
    assert producer.sent == []
