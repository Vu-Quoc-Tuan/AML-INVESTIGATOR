"""Data repository exception hierarchy."""


class DataRepositoryError(RuntimeError):
    """Base class for repository failures."""


class DataRepositoryNotInitializedError(DataRepositoryError):
    """Raised when backend services are used before startup warm-up."""


class DataFileNotFoundError(DataRepositoryError):
    """Raised when a required generated artifact is absent."""


class DataSchemaError(DataRepositoryError):
    """Raised when an artifact does not satisfy its declared schema."""


class DataIntegrityError(DataRepositoryError):
    """Raised when cross-table or SHB-boundary integrity is violated."""
