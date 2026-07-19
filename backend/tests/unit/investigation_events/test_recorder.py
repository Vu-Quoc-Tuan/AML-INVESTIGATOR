from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from app.investigation_events import (
    ExecutionEventRecorder,
    InvestigationEventRepository,
    InvestigationEventType,
    ToolEventCallback,
    ToolExecutionFailed,
)


def recorder(tmp_path: Path) -> ExecutionEventRecorder:
    return ExecutionEventRecorder(
        InvestigationEventRepository(tmp_path / "events.db"),
        ticket_id="ticket-1",
        case_id="case-1",
    )


def test_tool_callback_records_start_and_safe_artifact(tmp_path: Path) -> None:
    event_recorder = recorder(tmp_path)
    callback = ToolEventCallback(event_recorder, "transaction_agent")
    run_id = "run-1"

    callback.on_tool_start(
        {"name": "trace_funds"},
        {"account_id": "ACC-1", "messages": ["must not persist"]},
        run_id=run_id,
    )
    callback.on_tool_end(
        ToolMessage(
            content="ok",
            tool_call_id="call-1",
            name="trace_funds",
            artifact={"status": "SUCCESS", "data": {"hops": 2}},
        ),
        run_id=run_id,
    )

    events = event_recorder.repository.list_after("ticket-1")
    assert [event.event_type for event in events] == [
        InvestigationEventType.TOOL_STARTED,
        InvestigationEventType.TOOL_SUCCEEDED,
    ]
    assert events[0].payload == {"input": {"account_id": "ACC-1"}}
    assert events[1].payload == {
        "result": {"status": "SUCCESS", "data": {"hops": 2}}
    }
    assert "messages" not in str([event.to_dict() for event in events]).lower()
    callback.raise_if_failed()


def test_event_payload_redacts_nested_credentials_and_keeps_identifiers(
    tmp_path: Path,
) -> None:
    event_recorder = recorder(tmp_path)

    event = event_recorder.append(
        InvestigationEventType.TOOL_STARTED,
        status="RUNNING",
        summary="Credential-safe payload",
        payload={
            "password": "password-value",
            "access_token": "access-token-value",
            "refreshToken": "refresh-token-value",
            "client-secret": "client-secret-value",
            "credentials": {"username": "alice", "password": "nested-value"},
            "nested": {"token": "nested-token", "transaction_id": "tx-1"},
            "transaction_id": "tx-1",
        },
    )

    assert event.payload == {
        "nested": {"transaction_id": "tx-1"},
        "transaction_id": "tx-1",
    }
    serialized = str(event.to_dict())
    for secret in (
        "password-value",
        "access-token-value",
        "refresh-token-value",
        "client-secret-value",
        "nested-value",
        "nested-token",
    ):
        assert secret not in serialized


@pytest.mark.parametrize(
    ("output", "expected_type"),
    [
        (
            ToolMessage(
                content="failed",
                tool_call_id="call-1",
                name="trace_funds",
                status="error",
            ),
            "ToolMessageError",
        ),
        ({"status": "ERROR", "error_code": "SOURCE_DOWN"}, "ToolResultError"),
    ],
)
def test_tool_callback_turns_error_results_into_execution_failure(
    tmp_path: Path, output: object, expected_type: str
) -> None:
    event_recorder = recorder(tmp_path)
    callback = ToolEventCallback(event_recorder, "transaction_agent")
    callback.on_tool_start({"name": "trace_funds"}, {}, run_id="run-1")
    callback.on_tool_end(output, run_id="run-1")

    with pytest.raises(ToolExecutionFailed, match="trace_funds") as raised:
        callback.raise_if_failed()

    assert raised.value.error_type == expected_type
    assert event_recorder.repository.latest_for_ticket("ticket-1").event_type is (
        InvestigationEventType.TOOL_FAILED
    )


def test_tool_callback_records_exception_type_without_error_text(tmp_path: Path) -> None:
    event_recorder = recorder(tmp_path)
    callback = ToolEventCallback(event_recorder, "kyc_agent")
    callback.on_tool_start({"name": "get_kyc"}, {}, run_id="run-1")
    callback.on_tool_error(
        RuntimeError("secret provider payload"),
        run_id="run-1",
    )

    event = event_recorder.repository.latest_for_ticket("ticket-1")
    assert event.event_type is InvestigationEventType.TOOL_FAILED
    assert event.payload == {"error_type": "RuntimeError"}
    assert "secret provider payload" not in str(event.to_dict())
