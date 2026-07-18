#!/usr/bin/env python3
"""Run realtime detection against the validated Kafka topic."""

from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path
from threading import Event

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.detection.anomaly_model import XGBoostPredictor  # noqa: E402
from app.detection.config import DetectionSettings  # noqa: E402
from app.detection.enrichment import StaticEnrichmentProvider  # noqa: E402
from app.detection.features import RealtimeFeatureExtractor  # noqa: E402
from app.detection.repository import DetectionRepository  # noqa: E402
from app.detection.rules import RuleEngine  # noqa: E402
from app.detection.worker import DetectionWorker  # noqa: E402
from app.streaming.clients import build_validated_consumer  # noqa: E402
from app.streaming.config import KafkaSettings  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    kafka_settings = KafkaSettings.from_env()
    detection_settings = DetectionSettings.from_env()
    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_args: stop.set())

    consumer = build_validated_consumer(
        kafka_settings,
        group_id=detection_settings.group_id,
        client_id=detection_settings.client_id,
    )
    repository = DetectionRepository(
        detection_settings.db_path,
        initial_mode=detection_settings.initial_run_mode,
        lease_seconds=detection_settings.claim_lease_seconds,
        retry_delay_seconds=detection_settings.retry_delay_seconds,
        max_attempts=detection_settings.max_attempts,
    )
    worker = DetectionWorker(
        consumer=consumer,
        repository=repository,
        rule_engine=RuleEngine(),
        feature_extractor=RealtimeFeatureExtractor(),
        predictor=XGBoostPredictor(detection_settings.model_path),
        settings=detection_settings,
        enrichment_provider=StaticEnrichmentProvider(
            detection_settings.enrichment_data_path
        ),
    )
    try:
        worker.run(stop.is_set, kafka_settings.poll_timeout_ms)
    finally:
        worker.close()
        consumer.close(autocommit=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
