#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import signal
import sys
import threading

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.streaming.config import KafkaSettings  # noqa: E402
from app.streaming.mock_service import run_mock_publisher  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Publish valid mock AML transactions to Kafka using real account ids "
            "from data/generated accounts CSVs"
        )
    )
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between events")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N events")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic data seed")
    parser.add_argument(
        "--data-path",
        type=Path,
        default=None,
        help="Directory containing accounts.csv and external_accounts.csv "
        "(default: backend/data/generated)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("kafka").setLevel(logging.WARNING)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    count = run_mock_publisher(
        KafkaSettings.from_env(),
        interval_seconds=args.interval,
        limit=args.limit,
        seed=args.seed,
        stop_requested=stop.is_set,
        data_path=args.data_path,
    )
    logging.info("Mock publisher stopped published=%s", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
