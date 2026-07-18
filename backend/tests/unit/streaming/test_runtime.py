from types import SimpleNamespace

from app.streaming.config import KafkaSettings
from app.streaming.runtime import run_ingestion
from app.streaming.schemas import canonical_json_bytes
from tests.unit.streaming.conftest import make_event


class Ack:
    def get(self, timeout):
        return None


class Producer:
    def __init__(self):
        self.sent = []

    def send(self, topic, *, key, value):
        self.sent.append((topic, key, value))
        return Ack()


class Consumer:
    def __init__(self, records):
        self.records = records
        self.poll_count = 0
        self.commits = []

    def poll(self, timeout_ms):
        self.poll_count += 1
        if self.poll_count == 1:
            return {("raw", 0): self.records}
        return {}

    def commit(self, offsets):
        self.commits.append(offsets)


def test_runtime_processes_every_polled_record_then_stops():
    records = [
        SimpleNamespace(
            topic="aml.transactions.raw.v1",
            partition=0,
            offset=index,
            value=canonical_json_bytes(make_event(event_id=f"EVENT-{index}")),
        )
        for index in range(2)
    ]
    consumer = Consumer(records)
    producer = Producer()
    processed = run_ingestion(
        KafkaSettings(),
        lambda: consumer.poll_count >= 2,
        consumer=consumer,
        producer=producer,
    )
    assert processed == 2
    assert len(producer.sent) == 2
    assert len(consumer.commits) == 2


def test_runtime_does_not_own_injected_clients():
    consumer = Consumer([])
    producer = Producer()
    assert run_ingestion(
        KafkaSettings(), lambda: True, consumer=consumer, producer=producer
    ) == 0
