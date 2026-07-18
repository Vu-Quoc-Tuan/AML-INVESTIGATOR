from datetime import datetime, timezone

from app.streaming.config import KafkaSettings
from app.streaming.mock_service import MockTransactionFactory, run_mock_publisher
from app.streaming.schemas import TransactionEventV1


FIXED_TIME = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)


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


def test_mock_factory_emits_unique_valid_events():
    factory = MockTransactionFactory(seed=42, clock=lambda: FIXED_TIME)
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


def test_mock_factory_is_reproducible_for_same_seed():
    first = MockTransactionFactory(seed=7, clock=lambda: FIXED_TIME).next_event()
    second = MockTransactionFactory(seed=7, clock=lambda: FIXED_TIME).next_event()
    assert first == second


def test_mock_publisher_waits_for_ack_and_honors_limit():
    producer = FakeProducer()
    count = run_mock_publisher(
        KafkaSettings(),
        interval_seconds=0,
        limit=3,
        stop_requested=lambda: False,
        producer=producer,
    )
    assert count == 3
    assert producer.ack_count == 3
    assert all(item[0] == "aml.transactions.raw.v1" for item in producer.sent)


def test_mock_publisher_can_stop_before_first_event():
    producer = FakeProducer()
    count = run_mock_publisher(
        KafkaSettings(), 0, None, lambda: True, producer=producer
    )
    assert count == 0
    assert producer.sent == []
