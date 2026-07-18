import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.streaming.config import KafkaSettings
from app.streaming.relay import (
    PublishFailed,
    SourceMetadata,
    TransactionRelay,
    process_record,
)
from app.streaming.schemas import canonical_json_bytes
from tests.unit.streaming.conftest import make_event


FIXED_TIME = datetime(2026, 7, 18, 11, 0, tzinfo=timezone.utc)


def build_relay():
    return TransactionRelay(KafkaSettings(), clock=lambda: FIXED_TIME)


def source_metadata():
    return SourceMetadata("aml.transactions.raw.v1", 2, 41)


def test_valid_event_routes_to_validated_topic():
    decision = build_relay().route(canonical_json_bytes(make_event()), source_metadata())
    assert decision.route == "validated"
    assert decision.topic == "aml.transactions.validated.v1"
    assert decision.key == b"EVENT-1"


def test_malformed_json_routes_to_redacted_dlq():
    decision = build_relay().route(b'{"account":"secret"', source_metadata())
    assert decision.route == "dlq"
    assert b"secret" not in decision.value
    assert json.loads(decision.value)["error_code"] == "MALFORMED_JSON"


def test_invalid_schema_dlq_never_contains_source_payload():
    raw = b'{"event_id":"EVENT-X","account":"ACCT-SECRET-1"}'
    decision = build_relay().route(raw, source_metadata())
    assert decision.key == b"EVENT-X"
    assert b"ACCT-SECRET-1" not in decision.value


class FakeAck:
    def __init__(self, order, fail=False):
        self.order = order
        self.fail = fail

    def get(self, timeout):
        self.order.append("ack")
        if self.fail:
            raise TimeoutError("broker unavailable")


class FakeProducer:
    def __init__(self, order, fail=False):
        self.order = order
        self.fail = fail

    def send(self, topic, *, key, value):
        self.order.append("send")
        return FakeAck(self.order, self.fail)


class FakeConsumer:
    def __init__(self, order):
        self.order = order
        self.commits = []

    def commit(self, offsets):
        self.order.append("commit")
        self.commits.append(offsets)


def record():
    return SimpleNamespace(
        topic="aml.transactions.raw.v1",
        partition=0,
        offset=7,
        value=canonical_json_bytes(make_event()),
    )


def test_commit_happens_only_after_publish_acknowledgement():
    order = []
    process_record(
        record(), FakeProducer(order), FakeConsumer(order), build_relay(), KafkaSettings()
    )
    assert order == ["send", "ack", "commit"]


def test_commit_uses_next_source_offset():
    consumer = FakeConsumer([])
    process_record(record(), FakeProducer([]), consumer, build_relay(), KafkaSettings())
    committed = next(iter(consumer.commits[0].values()))
    assert committed.offset == 8


def test_publish_failure_does_not_commit():
    consumer = FakeConsumer([])
    with pytest.raises(PublishFailed):
        process_record(
            record(), FakeProducer([], fail=True), consumer, build_relay(), KafkaSettings()
        )
    assert consumer.commits == []
