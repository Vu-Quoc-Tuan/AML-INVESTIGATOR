"""XGBoost prediction adapter with strict feature and probability validation."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Callable

from .contracts import FeatureSnapshot, ModelPrediction
from .features import FEATURE_COLUMNS


def _identity_matrix(data: Any, feature_names: list[str]) -> tuple[Any, list[str]]:
    return data, feature_names


class XGBoostPredictor:
    def __init__(
        self,
        model_path: Path,
        *,
        booster: Any | None = None,
        dmatrix_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        if booster is None:
            if not self.model_path.is_file():
                raise FileNotFoundError(f"XGBoost model not found: {self.model_path}")
            import xgboost as xgb

            booster = xgb.Booster()
            booster.load_model(self.model_path)
            dmatrix_factory = xgb.DMatrix
        if dmatrix_factory is None:
            dmatrix_factory = _identity_matrix
        self._booster = booster
        self._dmatrix_factory = dmatrix_factory
        self.model_version = self._version()

    def predict(self, features: FeatureSnapshot) -> ModelPrediction:
        if features.names != FEATURE_COLUMNS:
            raise ValueError("feature names/order do not match the trained model contract")
        matrix = self._dmatrix_factory(
            [list(features.values)], feature_names=list(features.names)
        )
        raw = self._booster.predict(matrix)
        if len(raw) != 1:
            raise ValueError("model must return exactly one prediction")
        confidence = float(raw[0])
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("model returned an invalid probability")
        return ModelPrediction(
            confidence=confidence,
            model_version=self.model_version,
            imputed_features=features.imputed_features,
        )

    def _version(self) -> str:
        if self.model_path.is_file():
            digest = hashlib.sha256(self.model_path.read_bytes()).hexdigest()[:12]
            return f"xgboost-{digest}"
        return "xgboost-injected"
