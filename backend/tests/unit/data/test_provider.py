from pathlib import Path

import pytest

from app.data.exceptions import DataFileNotFoundError, DataRepositoryNotInitializedError
from app.data.provider import (
    get_initialized_data_repository,
    initialize_data_repository,
)


def test_accessor_requires_explicit_warmup():
    with pytest.raises(DataRepositoryNotInitializedError):
        get_initialized_data_repository()


def test_repeated_initialization_returns_same_loaded_instance(generated_data_path: Path):
    first = initialize_data_repository(generated_data_path)
    second = initialize_data_repository(generated_data_path)

    assert first is second
    assert first.is_loaded


def test_failed_initialization_is_not_published(tmp_path: Path):
    with pytest.raises(DataFileNotFoundError):
        initialize_data_repository(tmp_path)

    with pytest.raises(DataRepositoryNotInitializedError):
        get_initialized_data_repository()


def test_imports_do_not_initialize_repository():
    import app.data  # noqa: F401
    import app.main  # noqa: F401
    import app.services  # noqa: F401

    with pytest.raises(DataRepositoryNotInitializedError):
        get_initialized_data_repository()
