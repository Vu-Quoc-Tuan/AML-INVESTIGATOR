from __future__ import annotations

import logging
from collections.abc import Callable

from app.streaming.clients import build_consumer, build_producer
from app.streaming.config import KafkaSettings
from app.streaming.relay import TransactionRelay, process_record

logger = logging.getLogger(__name__)


def run_ingestion(
    settings: KafkaSettings,
    stop_requested: Callable[[], bool],
    *,
    consumer=None,
    producer=None,
) -> int:
    owned_consumer = consumer is None
    owned_producer = producer is None
    consumer = consumer or build_consumer(settings)
    producer = producer or build_producer(settings)
    relay = TransactionRelay(settings)
    processed = 0
    try:
        while not stop_requested():
            batches = consumer.poll(timeout_ms=settings.poll_timeout_ms)
            for records in batches.values():
                for record in records:
                    if stop_requested():
                        return processed
                    decision = process_record(record, producer, consumer, relay, settings)
                    processed += 1
                    logger.info(
                        "Kafka record routed route=%s topic=%s partition=%s offset=%s",
                        decision.route,
                        record.topic,
                        record.partition,
                        record.offset,
                    )
        return processed
    finally:
        if owned_consumer:
            consumer.close(autocommit=False)
        if owned_producer:
            producer.close(timeout=settings.ack_timeout_seconds)
