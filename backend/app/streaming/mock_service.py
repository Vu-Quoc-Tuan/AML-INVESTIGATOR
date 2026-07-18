from __future__ import annotations

import csv
import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.streaming.clients import build_producer
from app.streaming.config import KafkaSettings
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1, canonical_json_bytes

logger = logging.getLogger(__name__)

DEFAULT_GENERATED_DATA = (
    Path(__file__).resolve().parents[2] / "data" / "generated"
)


@dataclass(frozen=True)
class ExternalAccountRef:
    account_id: str
    bank_id: str


@dataclass(frozen=True)
class AccountRoster:
    """In-memory account lists loaded from generated CSVs for realistic mocks."""

    internal_account_ids: tuple[str, ...]
    external_accounts: tuple[ExternalAccountRef, ...]

    def __post_init__(self) -> None:
        if len(self.internal_account_ids) < 2:
            raise ValueError("AccountRoster requires at least two internal accounts")
        if not self.external_accounts:
            raise ValueError("AccountRoster requires at least one external account")


def load_account_roster(data_path: str | Path | None = None) -> AccountRoster:
    """Load SHB and external account ids from synthetic CSV data."""

    root = Path(data_path) if data_path is not None else DEFAULT_GENERATED_DATA
    accounts_path = root / "accounts.csv"
    external_path = root / "external_accounts.csv"
    if not accounts_path.is_file():
        raise FileNotFoundError(f"accounts.csv not found: {accounts_path}")
    if not external_path.is_file():
        raise FileNotFoundError(f"external_accounts.csv not found: {external_path}")

    internal: list[str] = []
    with accounts_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            account_id = (row.get("account_id") or "").strip()
            bank_id = (row.get("bank_id") or "").strip()
            if not account_id:
                continue
            if bank_id and bank_id != HOME_BANK_ID:
                continue
            internal.append(account_id)

    external: list[ExternalAccountRef] = []
    with external_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            account_id = (row.get("external_account_id") or "").strip()
            bank_id = (row.get("bank_id") or "").strip() or "BANK-FOREIGN-DEMO"
            if account_id:
                external.append(ExternalAccountRef(account_id=account_id, bank_id=bank_id))

    roster = AccountRoster(
        internal_account_ids=tuple(internal),
        external_accounts=tuple(external),
    )
    logger.info(
        "Loaded account roster internal=%s external=%s from %s",
        len(roster.internal_account_ids),
        len(roster.external_accounts),
        root,
    )
    return roster


class MockTransactionFactory:
    def __init__(
        self,
        seed: int = 42,
        clock: Callable[[], datetime] | None = None,
        *,
        roster: AccountRoster | None = None,
        data_path: str | Path | None = None,
    ) -> None:
        self.seed = seed
        self.random = random.Random(seed)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sequence = 0
        self.roster = roster if roster is not None else load_account_roster(data_path)

    def _pick_distinct_internal(self) -> tuple[str, str]:
        source, destination = self.random.sample(self.roster.internal_account_ids, 2)
        return source, destination

    def _pick_internal(self) -> str:
        return self.random.choice(self.roster.internal_account_ids)

    def _pick_external(self) -> ExternalAccountRef:
        return self.random.choice(self.roster.external_accounts)

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
            source, destination = self._pick_distinct_internal()
            common.update(
                source_account_ref=source,
                destination_account_ref=destination,
                source_bank_id=HOME_BANK_ID,
                destination_bank_id=HOME_BANK_ID,
                data_visibility="FULL_INTERNAL",
            )
        elif direction == "OUTBOUND":
            external = self._pick_external()
            common.update(
                source_account_ref=self._pick_internal(),
                destination_account_ref=external.account_id,
                source_bank_id=HOME_BANK_ID,
                destination_bank_id=external.bank_id,
                data_visibility="PAYMENT_MESSAGE_ONLY",
            )
        else:
            external = self._pick_external()
            common.update(
                source_account_ref=external.account_id,
                destination_account_ref=self._pick_internal(),
                source_bank_id=external.bank_id,
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
    data_path: str | Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if interval_seconds < 0:
        raise ValueError("interval_seconds must not be negative")
    if limit is not None and limit < 0:
        raise ValueError("limit must not be negative")

    owned_producer = producer is None
    producer = producer or build_producer(settings)
    factory = factory or MockTransactionFactory(seed=seed, data_path=data_path)
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
                "Mock transaction published event_id=%s src=%s dst=%s direction=%s "
                "topic=%s partition=%s offset=%s",
                event.event_id,
                event.source_account_ref,
                event.destination_account_ref,
                event.direction.value,
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
