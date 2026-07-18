from app.streaming import clients
from app.streaming.config import KafkaSettings


def fake_constructor(captured):
    def constructor(*topics, **kwargs):
        captured["topics"] = topics
        captured.update(kwargs)
        return object()

    return constructor


def test_consumer_disables_auto_commit(monkeypatch):
    captured = {}
    monkeypatch.setattr(clients, "KafkaConsumer", fake_constructor(captured))
    clients.build_consumer(KafkaSettings())
    assert captured["topics"] == ("aml.transactions.raw.v1",)
    assert captured["enable_auto_commit"] is False
    assert captured["group_id"] == "aml-ingestion-v1"
    assert captured["auto_offset_reset"] == "earliest"


def test_producer_requires_all_replicas_ack(monkeypatch):
    captured = {}
    monkeypatch.setattr(clients, "KafkaProducer", fake_constructor(captured))
    clients.build_producer(KafkaSettings())
    assert captured["acks"] == "all"
    assert captured["retries"] > 0
