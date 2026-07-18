from pathlib import Path
import shutil

import pytest

from app.data.provider import _reset_data_repository_for_testing


@pytest.fixture(autouse=True)
def reset_repository_provider():
    _reset_data_repository_for_testing()
    yield
    _reset_data_repository_for_testing()


@pytest.fixture
def generated_data_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "generated"


@pytest.fixture
def copied_data(tmp_path: Path, generated_data_path: Path) -> Path:
    destination = tmp_path / "generated"
    shutil.copytree(generated_data_path, destination)
    return destination
