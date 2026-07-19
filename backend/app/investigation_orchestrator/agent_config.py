"""Per-agent model + soft-prompt configuration contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AGENT_IDS: tuple[str, ...] = (
    "planner",
    "transaction",
    "kyc",
    "screening",
    "behavior_mapper",
    "report",
)

AGENT_LABELS: dict[str, str] = {
    "planner": "Planner Agent",
    "transaction": "Transaction Agent",
    "kyc": "KYC Agent",
    "screening": "Screening Agent",
    "behavior_mapper": "Behavior Mapper",
    "report": "Report Agent",
}


class AgentSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    model_id: str | None = None
    soft_prompt: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if value not in AGENT_IDS:
            raise ValueError(f"unknown agent id: {value}")
        return value

    @field_validator("soft_prompt", mode="before")
    @classmethod
    def normalize_soft_prompt(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if len(normalized) > 4_000:
            raise ValueError("soft_prompt must contain at most 4000 characters")
        return normalized

    @field_validator("model_id", mode="before")
    @classmethod
    def normalize_model_id(cls, value: object) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class AgentSettingsBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[AgentSetting] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_agent_ids(self) -> "AgentSettingsBundle":
        ids = [item.id for item in self.agents]
        duplicates = sorted({agent_id for agent_id in ids if ids.count(agent_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate agent ids: {', '.join(duplicates)}")
        return self

    def by_id(self) -> dict[str, AgentSetting]:
        return {item.id: item for item in self.agents}

    def for_agent(self, agent_id: str) -> AgentSetting:
        mapping = self.by_id()
        if agent_id in mapping:
            return mapping[agent_id]
        return AgentSetting(id=agent_id)

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            item.id: {
                "model_id": item.model_id,
                "soft_prompt": item.soft_prompt,
            }
            for item in self.agents
        }

    @classmethod
    def from_storage(cls, raw: dict[str, Any] | None) -> "AgentSettingsBundle":
        raw = raw or {}
        agents: list[AgentSetting] = []
        for agent_id in AGENT_IDS:
            entry = raw.get(agent_id) or {}
            if not isinstance(entry, dict):
                entry = {}
            agents.append(
                AgentSetting(
                    id=agent_id,
                    model_id=entry.get("model_id"),
                    soft_prompt=entry.get("soft_prompt"),
                )
            )
        return cls(agents=agents)

    @classmethod
    def defaults(cls) -> "AgentSettingsBundle":
        return cls(agents=[AgentSetting(id=agent_id) for agent_id in AGENT_IDS])
