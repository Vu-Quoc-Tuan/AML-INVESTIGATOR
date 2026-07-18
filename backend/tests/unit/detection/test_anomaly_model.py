from pathlib import Path

import pytest

from app.detection.anomaly_model import XGBoostPredictor
from app.detection.contracts import FeatureSnapshot
from app.detection.features import FEATURE_COLUMNS


class Booster:
    def __init__(self, output):
        self.output = output

    def predict(self, matrix):
        return self.output


def snapshot(names=FEATURE_COLUMNS) -> FeatureSnapshot:
    return FeatureSnapshot(names, (0.0,) * len(names), ("source_owner_age",))


def test_missing_model_artifact_fails_at_startup(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        XGBoostPredictor(tmp_path / "missing.json")


def test_injected_booster_returns_validated_prediction(tmp_path: Path) -> None:
    predictor = XGBoostPredictor(tmp_path / "unused", booster=Booster([0.72]))
    result = predictor.predict(snapshot())
    assert result.confidence == 0.72
    assert result.imputed_features == ("source_owner_age",)


def test_wrong_feature_order_is_rejected(tmp_path: Path) -> None:
    predictor = XGBoostPredictor(tmp_path / "unused", booster=Booster([0.2]))
    with pytest.raises(ValueError, match="names/order"):
        predictor.predict(snapshot(tuple(reversed(FEATURE_COLUMNS))))


@pytest.mark.parametrize("output", [[float("nan")], [1.1], []])
def test_invalid_model_output_fails_closed(tmp_path: Path, output) -> None:
    predictor = XGBoostPredictor(tmp_path / "unused", booster=Booster(output))
    with pytest.raises(ValueError):
        predictor.predict(snapshot())


def test_repository_model_artifact_loads_with_feature_contract() -> None:
    model_path = Path(__file__).resolve().parents[3] / "model" / "xgb_model.json"
    result = XGBoostPredictor(model_path).predict(snapshot())
    assert 0 <= result.confidence <= 1
    assert result.model_version.startswith("xgboost-")
