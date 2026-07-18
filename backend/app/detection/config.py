"""Environment-backed settings for the detection pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .contracts import RunMode


_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DetectionSettings:
    db_path: Path = _BACKEND_ROOT / "data" / "detection_queue.db"
    model_path: Path = _BACKEND_ROOT / "model" / "xgb_model.json"
    enrichment_data_path: Path = _BACKEND_ROOT / "data" / "generated"
    ml_queue_threshold: float = 0.60
    ml_block_threshold: float = 0.99
    group_id: str = "aml-detection-v1"
    client_id: str = "aml-realtime-detection"
    initial_run_mode: RunMode = RunMode.MANUAL
    claim_lease_seconds: int = 1_800
    retry_delay_seconds: int = 300
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if not 0 <= self.ml_queue_threshold < self.ml_block_threshold <= 1:
            raise ValueError("thresholds must satisfy 0 <= queue < block <= 1")
        if self.claim_lease_seconds <= 0:
            raise ValueError("claim_lease_seconds must be positive")
        if self.retry_delay_seconds <= 0:
            raise ValueError("retry_delay_seconds must be positive")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if not self.group_id.strip() or not self.client_id.strip():
            raise ValueError("Kafka group_id and client_id must not be empty")
        if not str(self.db_path).strip() or not str(self.model_path).strip():
            raise ValueError("database and model paths must not be empty")

    @classmethod
    def from_env(cls) -> "DetectionSettings":
        defaults = cls()
        return cls(
            db_path=Path(os.getenv("DETECTION_DB_PATH", str(defaults.db_path))),
            model_path=Path(os.getenv("DETECTION_MODEL_PATH", str(defaults.model_path))),
            enrichment_data_path=Path(
                os.getenv(
                    "DETECTION_ENRICHMENT_DATA_PATH",
                    str(defaults.enrichment_data_path),
                )
            ),
            ml_queue_threshold=float(
                os.getenv("DETECTION_ML_QUEUE_THRESHOLD", defaults.ml_queue_threshold)
            ),
            ml_block_threshold=float(
                os.getenv("DETECTION_ML_BLOCK_THRESHOLD", defaults.ml_block_threshold)
            ),
            group_id=os.getenv("DETECTION_GROUP_ID", defaults.group_id),
            client_id=os.getenv("DETECTION_CLIENT_ID", defaults.client_id),
            initial_run_mode=RunMode(
                os.getenv("DETECTION_RUN_MODE", defaults.initial_run_mode.value).upper()
            ),
            claim_lease_seconds=int(
                os.getenv("DETECTION_CLAIM_LEASE_SECONDS", defaults.claim_lease_seconds)
            ),
            retry_delay_seconds=int(
                os.getenv("DETECTION_RETRY_DELAY_SECONDS", defaults.retry_delay_seconds)
            ),
            max_attempts=int(os.getenv("DETECTION_MAX_ATTEMPTS", defaults.max_attempts)),
        )
