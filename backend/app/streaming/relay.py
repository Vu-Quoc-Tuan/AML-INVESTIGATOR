from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from kafka.structs import OffsetAndMetadata, TopicPartition
from pydantic import ValidationError

from app.streaming.config import KafkaSettings
from app.streaming.schemas import (
    DeadLetterEventV1,
    TransactionEventV1,
    canonical_json_bytes,
)


@dataclass(frozen=True)
class SourceMetadata:
    topic: str
    partition: int
    offset: int


@dataclass(frozen=True)
class RelayDecision:
    topic: str
    key: bytes
    value: bytes
    route: Literal["validated", "dlq"]


class PublishFailed(RuntimeError):
    """The output record was not acknowledged, so the input must remain uncommitted."""


class TransactionRelay:
    def __init__(
        self,
        settings: KafkaSettings,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def route(self, raw_value: bytes | None, metadata: SourceMetadata) -> RelayDecision:
        if not raw_value:
            return self._dlq(metadata, "EMPTY_VALUE", "Kafka record has no value")

        try:
            decoded = json.loads(raw_value)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._dlq(metadata, "MALFORMED_JSON", "Kafka record is not valid JSON")

        event_id = decoded.get("event_id") if isinstance(decoded, dict) else None
        safe_event_id = event_id if isinstance(event_id, str) and event_id.strip() else None
        try:
            event = TransactionEventV1.model_validate(decoded)
        except ValidationError:
            return self._dlq(
                metadata,
                "SCHEMA_VALIDATION_FAILED",
                "Kafka record does not match TransactionEventV1",
                safe_event_id,
            )

        return RelayDecision(
            topic=self.settings.validated_topic,
            key=event.event_id.encode("utf-8"),
            value=canonical_json_bytes(event),
            route="validated",
        )

    def _dlq(
        self,
        metadata: SourceMetadata,
        error_code: Literal["EMPTY_VALUE", "MALFORMED_JSON", "SCHEMA_VALIDATION_FAILED"],
        error_message: str,
        event_id: str | None = None,
    ) -> RelayDecision:
        envelope = DeadLetterEventV1(
            error_code=error_code,
            error_message=error_message,
            source_topic=metadata.topic,
            source_partition=metadata.partition,
            source_offset=metadata.offset,
            failed_at=self.clock(),
            event_id=event_id,
        )
        key = event_id or f"{metadata.topic}:{metadata.partition}:{metadata.offset}"
        return RelayDecision(
            topic=self.settings.dlq_topic,
            key=key.encode("utf-8"),
            value=canonical_json_bytes(envelope),
            route="dlq",
        )


def process_record(record, producer, consumer, relay: TransactionRelay, settings: KafkaSettings):
    metadata = SourceMetadata(
        topic=record.topic,
        partition=record.partition,
        offset=record.offset,
    )
    decision = relay.route(record.value, metadata)
    try:
        acknowledgement = producer.send(
            decision.topic,
            key=decision.key,
            value=decision.value,
        )
        acknowledgement.get(timeout=settings.ack_timeout_seconds)
    except Exception as exc:
        raise PublishFailed(
            f"output publish was not acknowledged for {record.topic}:{record.partition}:{record.offset}"
        ) from exc

    source_partition = TopicPartition(record.topic, record.partition)
    consumer.commit(
        offsets={
            source_partition: OffsetAndMetadata(
                offset=record.offset + 1,
                metadata="",
                leader_epoch=-1,
            )
        }
    )
    return decision
