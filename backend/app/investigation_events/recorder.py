"""Safe node/tool event recording without model messages or chain-of-thought."""

from __future__ import annotations

import re
from dataclasses import dataclass
from threading import Lock
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import ToolMessage
from pydantic import BaseModel

from .contracts import InvestigationEvent, InvestigationEventType
from .repository import InvestigationEventRepository


_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "set_cookie",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "credential",
        "credentials",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "messages",
        "prompt",
        "system_prompt",
        "user_prompt",
        "chain_of_thought",
        "reasoning",
    }
)


class ToolExecutionFailed(RuntimeError):
    def __init__(self, tool_name: str, error_type: str) -> None:
        super().__init__(f"tool execution failed: {tool_name}")
        self.tool_name = tool_name
        self.error_type = error_type


@dataclass(frozen=True)
class ExecutionEventRecorder:
    repository: InvestigationEventRepository
    ticket_id: str
    case_id: str

    @classmethod
    def from_state(
        cls, repository: InvestigationEventRepository, state: dict[str, Any]
    ) -> "ExecutionEventRecorder":
        case_id = str(state.get("case_id") or "unknown-case")
        alert = state.get("alert") if isinstance(state.get("alert"), dict) else {}
        ticket_id = str(alert.get("candidate_id") or case_id)
        return cls(repository, ticket_id=ticket_id, case_id=case_id)

    def append(
        self,
        event_type: InvestigationEventType,
        *,
        status: str,
        summary: str,
        agent_id: str | None = None,
        tool_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> InvestigationEvent:
        safe_payload = _safe_mapping(payload) if payload is not None else None
        return self.repository.append(
            ticket_id=self.ticket_id,
            case_id=self.case_id,
            agent_id=agent_id,
            event_type=event_type,
            status=status,
            summary=summary,
            tool_name=tool_name,
            payload=safe_payload,
        )


class ToolEventCallback(BaseCallbackHandler):
    """Record only tool boundaries; deliberately ignore model/chain callbacks."""

    run_inline = True

    def __init__(self, recorder: ExecutionEventRecorder, agent_id: str) -> None:
        self.recorder = recorder
        self.agent_id = agent_id
        self._tool_names: dict[str, str] = {}
        self._failures: dict[str, ToolExecutionFailed] = {}
        self._lock = Lock()

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: Any,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        del kwargs
        name = str(serialized.get("name") or "unknown_tool")
        key = str(run_id)
        with self._lock:
            self._tool_names[key] = name
        tool_input = input_str if isinstance(input_str, dict) else {"value": input_str}
        self.recorder.append(
            InvestigationEventType.TOOL_STARTED,
            agent_id=self.agent_id,
            tool_name=name,
            status="RUNNING",
            summary=f"Tool {name} started",
            payload={"input": tool_input},
        )

    def on_tool_end(self, output: Any, *, run_id: Any, **kwargs: Any) -> None:
        del kwargs
        key = str(run_id)
        name = self._tool_name(key, output)
        result = _tool_output(output)
        error_type = _tool_result_error_type(output, result)
        if error_type is not None:
            self._record_failure(key, name, error_type)
            return
        self.recorder.append(
            InvestigationEventType.TOOL_SUCCEEDED,
            agent_id=self.agent_id,
            tool_name=name,
            status="COMPLETED",
            summary=f"Tool {name} completed",
            payload={"result": result},
        )

    def on_tool_error(
        self, error: BaseException, *, run_id: Any, **kwargs: Any
    ) -> None:
        del kwargs
        key = str(run_id)
        self._record_failure(key, self._tool_name(key), type(error).__name__)

    def raise_if_failed(self) -> None:
        with self._lock:
            failure = next(iter(self._failures.values()), None)
        if failure is not None:
            raise failure

    def _tool_name(self, key: str, output: Any = None) -> str:
        with self._lock:
            known = self._tool_names.get(key)
        if known:
            return known
        if isinstance(output, ToolMessage) and output.name:
            return output.name
        return "unknown_tool"

    def _record_failure(self, key: str, name: str, error_type: str) -> None:
        failure = ToolExecutionFailed(name, error_type)
        with self._lock:
            if key in self._failures:
                return
            self._failures[key] = failure
        self.recorder.append(
            InvestigationEventType.TOOL_FAILED,
            agent_id=self.agent_id,
            tool_name=name,
            status="FAILED",
            summary=f"Tool {name} failed",
            payload={"error_type": error_type},
        )


def _tool_output(output: Any) -> Any:
    if isinstance(output, ToolMessage):
        if output.artifact is not None:
            return _safe_value(output.artifact)
        return _safe_value(output.content)
    return _safe_value(output)


def _tool_result_error_type(output: Any, result: Any) -> str | None:
    if isinstance(output, ToolMessage) and output.status == "error":
        return "ToolMessageError"
    if isinstance(result, dict) and str(result.get("status", "")).upper() == "ERROR":
        return "ToolResultError"
    return None


def _safe_mapping(value: dict[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): _safe_value(item)
        for key, item in (value or {}).items()
        if _normalized_key(key) not in _SENSITIVE_KEYS
    }


def _normalized_key(value: Any) -> str:
    key = re.sub(r"(?<!^)(?=[A-Z])", "_", str(value))
    return key.replace("-", "_").casefold()


def _safe_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _safe_value(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return _safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)[:500]
