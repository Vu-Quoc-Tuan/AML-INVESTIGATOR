import json
from pathlib import Path
from pydantic import BaseModel

class PatternThresholds(BaseModel):
    fan_in_min_sources: int = 5
    fan_out_min_destinations: int = 5
    pass_through_min_ratio: float = 0.90
    pass_through_max_hours: float = 24.0
    coordinated_amounts_tolerance: float = 0.02
    coordinated_amounts_min_transactions: int = 3
    structuring_threshold_amount: float = 100_000_000.0  # e.g., 100M VND
    structuring_min_transactions: int = 5
    structuring_max_hours: float = 24.0

class InvestigationConfig(BaseModel):
    thresholds: PatternThresholds = PatternThresholds()

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config(path: Path | None = None) -> InvestigationConfig:
    path = path or _DEFAULT_CONFIG_PATH
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return InvestigationConfig(**data)
    return InvestigationConfig()
