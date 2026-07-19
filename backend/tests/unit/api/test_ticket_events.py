from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.api.routes.tickets import format_sse_event, stream_ticket_events
from app.investigation_events import (
    InvestigationEventRepository,
    InvestigationEventType,
)


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def test_format_sse_event_contains_reconnect_id_and_json_payload(tmp_path: Path) -> None:
    repository = InvestigationEventRepository(tmp_path / "events.db")
    event = repository.append(
        ticket_id="ticket-1",
        case_id="case-1",
        agent_id="planner",
        event_type=InvestigationEventType.AGENT_STARTED,
        status="RUNNING",
        summary="Planner started",
    )

    frame = format_sse_event(event)

    assert frame.startswith(f"id: {event.id}\nevent: investigation\ndata: ")
    payload = json.loads(frame.split("data: ", 1)[1])
    assert payload["event_type"] == "AGENT_STARTED"
    assert payload["agent_id"] == "planner"
    assert frame.endswith("\n\n")


@pytest.mark.anyio
async def test_stream_replays_after_cursor_and_closes_on_terminal(tmp_path: Path) -> None:
    repository = InvestigationEventRepository(tmp_path / "events.db")
    first = repository.append(
        ticket_id="ticket-1",
        case_id="case-1",
        agent_id="planner",
        event_type=InvestigationEventType.AGENT_STARTED,
        status="RUNNING",
        summary="Planner started",
    )
    terminal = repository.append(
        ticket_id="ticket-1",
        case_id="case-1",
        event_type=InvestigationEventType.INVESTIGATION_COMPLETED,
        status="COMPLETED",
        summary="Investigation completed",
    )
    review = repository.append(
        ticket_id="ticket-1",
        case_id="case-1",
        event_type=InvestigationEventType.REVIEW_DECIDED,
        status="APPROVED",
        summary="Review decision: APPROVED",
        payload={"decision": "APPROVED"},
    )

    stream = stream_ticket_events(
        ConnectedRequest(),
        repository,
        "ticket-1",
        after_id=first.id,
        poll_seconds=0,
        heartbeat_seconds=30,
    )

    assert await anext(stream) == format_sse_event(terminal)
    assert await anext(stream) == format_sse_event(review)
    assert await anext(stream) == "event: stream_end\ndata: {}\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
