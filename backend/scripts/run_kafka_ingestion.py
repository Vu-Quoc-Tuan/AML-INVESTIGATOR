#!/usr/bin/env python3
from __future__ import annotations

import logging
from pathlib import Path
import signal
import sys
import threading

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.streaming.config import KafkaSettings  # noqa: E402
from app.streaming.runtime import run_ingestion  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("kafka").setLevel(logging.WARNING)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    settings = KafkaSettings.from_env()
    logging.info(
        "Starting Kafka ingestion bootstrap=%s raw_topic=%s",
        ",".join(settings.bootstrap_servers),
        settings.raw_topic,
    )
    run_ingestion(settings, stop.is_set)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
