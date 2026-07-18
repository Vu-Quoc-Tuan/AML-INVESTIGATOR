from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from datetime import datetime, timezone

from app.streaming.clients import build_producer
from app.streaming.config import KafkaSettings
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1, canonical_json_bytes

logger = logging.getLogger(__name__)


class MockTransactionFactory:
    def __init__(
        self,
        seed: int = 42,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.seed = seed
        self.random = random.Random(seed)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sequence = 0

    def next_event(self) -> TransactionEventV1:
        self.sequence += 1
        now = self.clock()
        direction = ("INTERNAL", "OUTBOUND", "INBOUND")[(self.sequence - 1) % 3]
        suffix = f"{self.seed:04d}-{self.sequence:08d}"
        common = {
            "event_id": f"MOCK-EVENT-{suffix}",
            "transaction_id": f"MOCK-TX-{suffix}",
            "occurred_at": now,
            "ingested_at": now,
            "amount": round(self.random.uniform(100_000, 50_000_000), 2),
            "currency": "VND",
            "direction": direction,
        }
        if direction == "INTERNAL":
            common.update(
                source_account_ref=f"ACCT-SHB-{self.random.randint(1, 999999):06d}",
                destination_account_ref=f"ACCT-SHB-{self.random.randint(1, 999999):06d}",
                source_bank_id=HOME_BANK_ID,
                destination_bank_id=HOME_BANK_ID,
                data_visibility="FULL_INTERNAL",
            )
        elif direction == "OUTBOUND":
            common.update(
                source_account_ref=f"ACCT-SHB-{self.random.randint(1, 999999):06d}",
                destination_account_ref=f"EXT-SG-{self.random.randint(1, 999999):06d}",
                source_bank_id=HOME_BANK_ID,
                destination_bank_id="BANK-FOREIGN-SG-DEMO",
                data_visibility="PAYMENT_MESSAGE_ONLY",
            )
        else:
            common.update(
                source_account_ref=f"EXT-US-{self.random.randint(1, 999999):06d}",
                destination_account_ref=f"ACCT-SHB-{self.random.randint(1, 999999):06d}",
                source_bank_id="BANK-FOREIGN-US-DEMO",
                destination_bank_id=HOME_BANK_ID,
                data_visibility="PAYMENT_MESSAGE_ONLY",
            )
        return TransactionEventV1.model_validate(common)


def run_mock_publisher(
    settings: KafkaSettings,
    interval_seconds: float,
    limit: int | None,
    stop_requested: Callable[[], bool],
    *,
    seed: int = 42,
    producer=None,
    factory: MockTransactionFactory | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if interval_seconds < 0:
        raise ValueError("interval_seconds must not be negative")
    if limit is not None and limit < 0:
        raise ValueError("limit must not be negative")

    owned_producer = producer is None
    producer = producer or build_producer(settings)
    factory = factory or MockTransactionFactory(seed=seed)
    published = 0
    try:
        while not stop_requested() and (limit is None or published < limit):
            event = factory.next_event()
            acknowledgement = producer.send(
                settings.raw_topic,
                key=event.event_id.encode("utf-8"),
                value=canonical_json_bytes(event),
            )
            delivery = acknowledgement.get(timeout=settings.ack_timeout_seconds)
            published += 1
            logger.info(
                "Mock transaction published event_id=%s topic=%s partition=%s offset=%s",
                event.event_id,
                getattr(delivery, "topic", settings.raw_topic),
                getattr(delivery, "partition", "unknown"),
                getattr(delivery, "offset", "unknown"),
            )
            if interval_seconds and (limit is None or published < limit):
                sleep(interval_seconds)
        return published
    finally:
        if owned_producer:
            producer.close(timeout=settings.ack_timeout_seconds)
