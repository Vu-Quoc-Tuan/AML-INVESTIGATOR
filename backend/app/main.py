"""Backend startup hooks.

The current scaffold has no web framework dependency. A future FastAPI lifespan
should call :func:`initialize_backend` rather than constructing a repository.
"""

from pathlib import Path

from app.data.config import RepositoryConfig
from app.data.provider import initialize_data_repository
from app.data.repository import DataRepository


def initialize_backend(
    data_path: str | Path | None = None,
    config: RepositoryConfig | None = None,
) -> DataRepository:
    """Warm and validate shared backend data explicitly at process startup."""

    return initialize_data_repository(data_path=data_path, config=config)
