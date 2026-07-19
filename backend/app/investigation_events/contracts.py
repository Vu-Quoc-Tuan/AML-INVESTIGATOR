"""Typed, JSON-safe contracts for persisted investigation activity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class InvestigationEventType(StrEnum):
    AGENT_STARTED = "AGENT_STARTED"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_SUCCEEDED = "TOOL_SUCCEEDED"
    TOOL_FAILED = "TOOL_FAILED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_FAILED = "AGENT_FAILED"
    INVESTIGATION_COMPLETED = "INVESTIGATION_COMPLETED"
    INVESTIGATION_FAILED = "INVESTIGATION_FAILED"
    REVIEW_DECIDED = "REVIEW_DECIDED"


TERMINAL_EVENT_TYPES = frozenset(
    {
        InvestigationEventType.INVESTIGATION_COMPLETED,
        InvestigationEventType.INVESTIGATION_FAILED,
    }
)


@dataclass(frozen=True)
class InvestigationEvent:
    id: int
    ticket_id: str
    case_id: str
    agent_id: str | None
    event_type: InvestigationEventType
    status: str
    summary: str
    tool_name: str | None
    payload: dict[str, Any] | None
    created_at: datetime

    @property
    def terminal(self) -> bool:
        return self.event_type in TERMINAL_EVENT_TYPES

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "case_id": self.case_id,
            "agent_id": self.agent_id,
            "event_type": self.event_type.value,
            "status": self.status,
            "summary": self.summary,
            "tool_name": self.tool_name,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }
