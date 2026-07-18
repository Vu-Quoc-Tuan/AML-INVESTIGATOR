"""Explicit composition root for backend-owned production tools."""

from __future__ import annotations

from typing import Any

from app.kyc_entity.tool_adapter import build_kyc_tools
from app.screening.tool_adapter import build_screening_tools
from app.transaction_investigation.tool_adapter import build_transaction_tools

from .tool_registry import ToolConfigurationError, ToolRegistry


def register_production_transaction_tools(
    registry: ToolRegistry,
    *,
    service: Any | None = None,
) -> None:
    """Register the domain factory under its sole approved owner."""

    try:
        registry.register("transaction", build_transaction_tools(service))
    except ValueError as exc:
        raise ToolConfigurationError("Transaction tool registration failed") from exc


def register_production_kyc_tools(
    registry: ToolRegistry,
    *,
    facade: Any | None = None,
) -> None:
    """Register the KYC domain factory under its sole approved owner."""

    try:
        registry.register("kyc", build_kyc_tools(facade))
    except ValueError as exc:
        raise ToolConfigurationError("KYC tool registration failed") from exc


def build_production_tool_registry() -> ToolRegistry:
    """Compose available factories and reject an incomplete production graph."""

    registry = ToolRegistry()
    register_production_transaction_tools(registry)
    register_production_kyc_tools(registry)
    try:
        registry.register("screening", build_screening_tools())
    except ValueError as exc:
        raise ToolConfigurationError("Screening tool registration failed") from exc
    registry.require_tools()
    return registry
