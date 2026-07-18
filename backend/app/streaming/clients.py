from __future__ import annotations

from kafka import KafkaConsumer, KafkaProducer

from app.streaming.config import KafkaSettings


def build_producer(settings: KafkaSettings) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=list(settings.bootstrap_servers),
        client_id=settings.client_id,
        acks="all",
        retries=10,
        request_timeout_ms=max(1_000, int(settings.ack_timeout_seconds * 1_000)),
    )


def build_consumer(settings: KafkaSettings) -> KafkaConsumer:
    return KafkaConsumer(
        settings.raw_topic,
        bootstrap_servers=list(settings.bootstrap_servers),
        client_id=settings.client_id,
        group_id=settings.group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
