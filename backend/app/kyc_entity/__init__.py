"""Deterministic KYC, entity-resolution, and ownership capabilities."""

from .config import KycEntityConfig
from .exceptions import (
    EntityNotFoundError,
    EntityScopeViolationError,
    EvidenceConflictError,
    EvidenceContractError,
    KycEntityError,
    OwnershipTraversalError,
)

__all__ = [
    "EntityNotFoundError",
    "EntityScopeViolationError",
    "EvidenceConflictError",
    "EvidenceContractError",
    "KycEntityConfig",
    "KycEntityError",
    "OwnershipTraversalError",
]
