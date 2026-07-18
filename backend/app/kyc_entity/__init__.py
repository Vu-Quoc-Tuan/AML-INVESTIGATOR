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
from .tool_adapter import build_kyc_tools

__all__ = [
    "EntityNotFoundError",
    "EntityScopeViolationError",
    "EvidenceConflictError",
    "EvidenceContractError",
    "KycEntityConfig",
    "KycEntityError",
    "OwnershipTraversalError",
    "build_kyc_tools",
]
