#!/usr/bin/env python3
"""Persist the allowed investigation runner mode."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.detection.config import DetectionSettings  # noqa: E402
from app.detection.contracts import RunMode  # noqa: E402
from app.detection.repository import DetectionRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("AUTO", "MANUAL"))
    args = parser.parse_args()
    settings = DetectionSettings.from_env()
    repository = DetectionRepository(
        settings.db_path,
        initial_mode=settings.initial_run_mode,
        lease_seconds=settings.claim_lease_seconds,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
    )
    repository.set_mode(RunMode(args.mode))
    print(f"Investigation mode: {repository.get_mode().value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
