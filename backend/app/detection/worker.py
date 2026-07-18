"""Realtime Kafka worker for parallel rules and ML detection."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from kafka.structs import OffsetAndMetadata, TopicPartition

from app.streaming.schemas import TransactionEventV1

from .config import DetectionSettings
from .contracts import DecisionKind, DetectionDecision
from .risk_aggregator import aggregate

logger = logging.getLogger(__name__)


class DetectionWorker:
    def __init__(
        self,
        *,
        consumer: Any,
        repository: Any,
        rule_engine: Any,
        feature_extractor: Any,
        predictor: Any,
        settings: DetectionSettings,
        enrichment_provider: Callable[[TransactionEventV1], Mapping[str, Any]] | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.consumer = consumer
        self.repository = repository
        self.rule_engine = rule_engine
        self.feature_extractor = feature_extractor
        self.predictor = predictor
        self.settings = settings
        self.enrichment_provider = enrichment_provider or (lambda _event: {})
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="detection"
        )
        self._owns_executor = executor is None

    def process_record(self, record: Any) -> DetectionDecision:
        event = TransactionEventV1.model_validate_json(record.value)
        enrichment = self.enrichment_provider(event)
        rule_future = self._executor.submit(
            self.rule_engine.evaluate, event, enrichment
        )
        model_future = self._executor.submit(self._score, event, enrichment)
        rules = rule_future.result()
        prediction = model_future.result()
        decision = aggregate(rules, prediction, self.settings)

        if decision.kind is DecisionKind.BLOCKED:
            self.repository.record_blocked(event, decision)
        elif decision.kind is DecisionKind.QUEUED:
            self.repository.enqueue_candidate(event, decision)

        self.feature_extractor.observe(event)

        self.consumer.commit(
            offsets={
                TopicPartition(record.topic, record.partition): OffsetAndMetadata(
                    offset=record.offset + 1, metadata="", leader_epoch=-1
                )
            }
        )
        logger.info(
            "detection event_id=%s transaction_id=%s decision=%s confidence=%.6f "
            "rules=%s partition=%s offset=%s",
            event.event_id,
            event.transaction_id,
            decision.kind.value,
            decision.confidence,
            [hit.rule_id for hit in decision.rule_hits],
            record.partition,
            record.offset,
        )
        return decision

    def _score(
        self, event: TransactionEventV1, enrichment: Mapping[str, Any]
    ) -> Any:
        return self.predictor.predict(self.feature_extractor.extract(event, enrichment))

    def run(self, stop_requested: Callable[[], bool], poll_timeout_ms: int) -> int:
        processed = 0
        while not stop_requested():
            batches = self.consumer.poll(timeout_ms=poll_timeout_ms)
            for records in batches.values():
                for record in records:
                    if stop_requested():
                        return processed
                    self.process_record(record)
                    processed += 1
        return processed

    def close(self) -> None:
        if self._owns_executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
