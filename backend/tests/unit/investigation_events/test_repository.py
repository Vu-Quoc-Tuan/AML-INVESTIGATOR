from __future__ import annotations

from pathlib import Path

import pytest

from app.investigation_events import (
    InvestigationEventRepository,
    InvestigationEventType,
)


def repository(tmp_path: Path) -> InvestigationEventRepository:
    return InvestigationEventRepository(tmp_path / "events.db")


def test_append_orders_events_and_replays_after_cursor(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    first = repo.append(
        ticket_id="ticket-1",
        case_id="case-1",
        agent_id="planner",
        event_type=InvestigationEventType.AGENT_STARTED,
        status="RUNNING",
        summary="Planner started",
    )
    second = repo.append(
        ticket_id="ticket-1",
        case_id="case-1",
        agent_id="planner",
        event_type=InvestigationEventType.AGENT_COMPLETED,
        status="COMPLETED",
        summary="Planner completed",
        payload={"steps": 3},
    )
    repo.append(
        ticket_id="ticket-2",
        case_id="case-2",
        agent_id="planner",
        event_type=InvestigationEventType.AGENT_STARTED,
        status="RUNNING",
        summary="Other ticket",
    )

    assert second.id > first.id
    replay = repo.list_after("ticket-1", after_id=first.id)
    assert [event.id for event in replay] == [second.id]
    assert replay[0].payload == {"steps": 3}
    assert repo.latest_for_ticket("ticket-1") == second


def test_rejects_non_json_payload_and_limits_large_payload(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    with pytest.raises(ValueError, match="JSON serializable"):
        repo.append(
            ticket_id="ticket-1",
            case_id="case-1",
            agent_id="transaction",
            event_type=InvestigationEventType.TOOL_SUCCEEDED,
            status="COMPLETED",
            summary="Bad payload",
            payload={"secret": object()},
        )

    event = repo.append(
        ticket_id="ticket-1",
        case_id="case-1",
        agent_id="transaction",
        event_type=InvestigationEventType.TOOL_SUCCEEDED,
        status="COMPLETED",
        summary="Large tool result",
        payload={"data": "x" * 40_000},
    )

    assert event.payload == {
        "truncated": True,
        "original_bytes": 40_011,
    }


def test_validates_paging_and_required_identity(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    with pytest.raises(ValueError, match="ticket_id"):
        repo.append(
            ticket_id=" ",
            case_id="case-1",
            agent_id="planner",
            event_type=InvestigationEventType.AGENT_STARTED,
            status="RUNNING",
            summary="Planner started",
        )
    with pytest.raises(ValueError, match="after_id"):
        repo.list_after("ticket-1", after_id=-1)
    with pytest.raises(ValueError, match="limit"):
        repo.list_after("ticket-1", limit=0)
