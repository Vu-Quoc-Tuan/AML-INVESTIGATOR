#!/usr/bin/env python3
from __future__ import annotations

import logging
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.streaming.config import KafkaSettings  # noqa: E402
from app.streaming.topic_admin import ensure_topics  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("kafka").setLevel(logging.WARNING)
    settings = KafkaSettings.from_env()
    created = ensure_topics(settings)
    if created:
        logging.info("Created Kafka topics: %s", ", ".join(sorted(created)))
    else:
        logging.info("All Kafka topics already exist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
