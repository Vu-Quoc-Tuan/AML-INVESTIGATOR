"""Explicit, process-local lifecycle for the shared repository."""

from pathlib import Path
from threading import RLock

from .config import RepositoryConfig
from .exceptions import DataRepositoryNotInitializedError
from .repository import DataRepository

_lock = RLock()
_repository: DataRepository | None = None


def initialize_data_repository(
    data_path: str | Path | None = None,
    config: RepositoryConfig | None = None,
) -> DataRepository:
    """Load the process repository once and return the cached instance."""

    global _repository
    with _lock:
        if _repository is not None:
            requested = DataRepository.resolve_data_path(data_path)
            if requested != _repository.data_path:
                raise RuntimeError(
                    "DataRepository is already initialized with "
                    f"{_repository.data_path}; requested {requested}"
                )
            if config is not None and config != _repository.config:
                raise RuntimeError("DataRepository is already initialized with another config")
            return _repository

        candidate = DataRepository(data_path=data_path, config=config)
        candidate.load()
        _repository = candidate
        return candidate


def get_initialized_data_repository() -> DataRepository:
    """Return the warm repository without implicitly loading it."""

    with _lock:
        if _repository is None:
            raise DataRepositoryNotInitializedError(
                "DataRepository has not been initialized; call initialize_backend() at startup"
            )
        return _repository


def _reset_data_repository_for_testing() -> None:
    """Clear process state between isolated tests. Never call in production."""

    global _repository
    with _lock:
        _repository = None
