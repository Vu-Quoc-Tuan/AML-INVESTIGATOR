from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class KafkaSettings:
    bootstrap_servers: tuple[str, ...] = ("localhost:9092",)
    raw_topic: str = "aml.transactions.raw.v1"
    validated_topic: str = "aml.transactions.validated.v1"
    dlq_topic: str = "aml.transactions.dlq.v1"
    group_id: str = "aml-ingestion-v1"
    client_id: str = "aml-realtime-ingestion"
    poll_timeout_ms: int = 1_000
    ack_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.bootstrap_servers or any(not item.strip() for item in self.bootstrap_servers):
            raise ValueError("bootstrap_servers must contain at least one non-empty address")
        for name in ("raw_topic", "validated_topic", "dlq_topic", "group_id", "client_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.poll_timeout_ms <= 0:
            raise ValueError("poll_timeout_ms must be positive")
        if self.ack_timeout_seconds <= 0:
            raise ValueError("ack_timeout_seconds must be positive")

    @property
    def enable_auto_commit(self) -> bool:
        return False

    @classmethod
    def environment_names(cls) -> tuple[str, ...]:
        return (
            "KAFKA_BOOTSTRAP_SERVERS",
            "KAFKA_RAW_TOPIC",
            "KAFKA_VALIDATED_TOPIC",
            "KAFKA_DLQ_TOPIC",
            "KAFKA_GROUP_ID",
            "KAFKA_CLIENT_ID",
            "KAFKA_POLL_TIMEOUT_MS",
            "KAFKA_ACK_TIMEOUT_SECONDS",
        )

    @classmethod
    def from_env(cls) -> "KafkaSettings":
        defaults = cls()
        raw_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
        servers = (
            tuple(part.strip() for part in raw_servers.split(","))
            if raw_servers is not None
            else defaults.bootstrap_servers
        )
        return cls(
            bootstrap_servers=servers,
            raw_topic=os.getenv("KAFKA_RAW_TOPIC", defaults.raw_topic),
            validated_topic=os.getenv("KAFKA_VALIDATED_TOPIC", defaults.validated_topic),
            dlq_topic=os.getenv("KAFKA_DLQ_TOPIC", defaults.dlq_topic),
            group_id=os.getenv("KAFKA_GROUP_ID", defaults.group_id),
            client_id=os.getenv("KAFKA_CLIENT_ID", defaults.client_id),
            poll_timeout_ms=int(os.getenv("KAFKA_POLL_TIMEOUT_MS", defaults.poll_timeout_ms)),
            ack_timeout_seconds=float(
                os.getenv("KAFKA_ACK_TIMEOUT_SECONDS", defaults.ack_timeout_seconds)
            ),
        )
