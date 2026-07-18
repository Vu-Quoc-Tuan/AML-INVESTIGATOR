from pathlib import Path

import pytest

from app.data.provider import (
    _reset_data_repository_for_testing,
    initialize_data_repository,
)


@pytest.fixture(scope="module", autouse=True)
def initialized_repository():
    _reset_data_repository_for_testing()
    data_path = Path(__file__).resolve().parents[3] / "data" / "generated"
    repository = initialize_data_repository(data_path)
    yield repository
    _reset_data_repository_for_testing()
