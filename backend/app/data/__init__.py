"""Shared backend data layer. Importing this package performs no data I/O."""

from .config import RepositoryConfig
from .exceptions import (
    DataFileNotFoundError,
    DataIntegrityError,
    DataRepositoryError,
    DataRepositoryNotInitializedError,
    DataSchemaError,
)
from .provider import get_initialized_data_repository, initialize_data_repository
from .repository import DataRepository

__all__ = [
    "DataFileNotFoundError",
    "DataIntegrityError",
    "DataRepository",
    "DataRepositoryError",
    "DataRepositoryNotInitializedError",
    "DataSchemaError",
    "RepositoryConfig",
    "get_initialized_data_repository",
    "initialize_data_repository",
]
