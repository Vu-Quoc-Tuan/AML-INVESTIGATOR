#!/usr/bin/env python3
"""Drain queued investigations in AUTO or MANUAL trigger mode."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.detection.config import DetectionSettings  # noqa: E402
from app.detection.contracts import RunTrigger  # noqa: E402
from app.detection.repository import DetectionRepository  # noqa: E402
from app.detection.runner import InvestigationQueueRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", choices=("auto", "manual"), required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = DetectionSettings.from_env()
    repository = DetectionRepository(
        settings.db_path,
        initial_mode=settings.initial_run_mode,
        lease_seconds=settings.claim_lease_seconds,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
    )
    summary = InvestigationQueueRunner(repository).drain(
        RunTrigger(args.trigger.upper())
    )
    logging.getLogger(__name__).info(
        "investigation drain finished completed=%s failed=%s",
        summary.completed,
        summary.failed,
    )
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
