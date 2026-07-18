from pathlib import Path

import pytest

from app.detection.config import DetectionSettings
from app.detection.contracts import RunMode


def test_settings_read_detection_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DETECTION_DB_PATH", "/tmp/detection.db")
    monkeypatch.setenv("DETECTION_MODEL_PATH", "/tmp/model.json")
    monkeypatch.setenv("DETECTION_ML_QUEUE_THRESHOLD", "0.61")
    monkeypatch.setenv("DETECTION_ML_BLOCK_THRESHOLD", "0.995")
    monkeypatch.setenv("DETECTION_RUN_MODE", "auto")

    settings = DetectionSettings.from_env()

    assert settings.db_path == Path("/tmp/detection.db")
    assert settings.model_path == Path("/tmp/model.json")
    assert settings.ml_queue_threshold == 0.61
    assert settings.ml_block_threshold == 0.995
    assert settings.initial_run_mode is RunMode.AUTO


@pytest.mark.parametrize(
    ("queue", "block"),
    [(-0.1, 0.99), (0.6, 0.6), (0.99, 0.60), (0.6, 1.1)],
)
def test_settings_reject_invalid_thresholds(queue: float, block: float) -> None:
    with pytest.raises(ValueError, match="thresholds"):
        DetectionSettings(ml_queue_threshold=queue, ml_block_threshold=block)

