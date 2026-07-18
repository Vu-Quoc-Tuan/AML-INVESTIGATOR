from pathlib import Path

import pytest

from app.data.provider import _reset_data_repository_for_testing, initialize_data_repository


@pytest.fixture(scope="module", autouse=True)
def initialized_repository():
    _reset_data_repository_for_testing()
    initialize_data_repository(Path(__file__).resolve().parents[3] / "data" / "generated")
    yield
    _reset_data_repository_for_testing()
