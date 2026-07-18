"""Ownership and result contracts for tools implemented outside this package."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue


AgentName = Literal["transaction", "kyc", "screening"]
REQUIRED_TOOL_OWNERS: tuple[AgentName, ...] = (
    "transaction",
    "kyc",
    "screening",
)


class ToolConfigurationError(RuntimeError):
    """Raised when production agent tool ownership is incomplete or ambiguous."""


class ToolEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    visibility_level: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """JSON-safe tool boundary.

    KYC evidence used by a finding requires ``data.entity_scope=SHB_INTERNAL``.
    A confirmed screening match additionally requires a tool-derived
    ``entity_scope`` and ``match_basis`` of ``IDENTIFIER`` or ``MULTI_ATTRIBUTE``.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["SUCCESS", "NO_DATA", "INCONCLUSIVE", "ERROR"]
    data: JsonValue = None
    evidence: list[ToolEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None


class ToolRegistry:
    """Keep tools scoped to their owning agent and reject ambiguous names."""

    def __init__(self) -> None:
        self._tools: dict[AgentName, dict[str, BaseTool]] = {
            "transaction": {},
            "kyc": {},
            "screening": {},
        }

    def register(self, owner: AgentName, tools: Iterable[BaseTool]) -> None:
        for tool in tools:
            if any(tool.name in owned for owned in self._tools.values()):
                raise ValueError(f"Tool name already registered: {tool.name}")
            self._tools[owner][tool.name] = tool

    def tools_for(self, owner: AgentName) -> tuple[BaseTool, ...]:
        return tuple(self._tools[owner].values())

    def get_tool(self, owner: AgentName, name: str) -> BaseTool:
        try:
            return self._tools[owner][name]
        except KeyError:
            raise KeyError(f"Tool {name!r} is not registered for {owner}") from None

    def require_tools(
        self, owners: Iterable[AgentName] = REQUIRED_TOOL_OWNERS
    ) -> None:
        missing = sorted(owner for owner in owners if not self._tools[owner])
        if missing:
            raise ToolConfigurationError(
                f"Missing required tools for owners: {', '.join(missing)}"
            )
