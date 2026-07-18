"""Live capability gate for the configured OpenAI-compatible model."""

from pathlib import Path

import pytest
from dotenv import dotenv_values
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel


pytestmark = pytest.mark.live_llm
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class CapabilityResponse(BaseModel):
    status: str


def _model() -> ChatOpenAI:
    values = dotenv_values(ENV_FILE)
    api_key = values.get("API_KEY")
    base_url = values.get("BASE_URL")
    if not api_key or not base_url:
        raise AssertionError("backend/.env must define API_KEY and BASE_URL")
    return ChatOpenAI(
        model=values.get("MODEL_NAME") or "glm-5.2-free",
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=60,
        max_retries=2,
    )


def _redacted_invoke(callable_, input_):
    try:
        return callable_.invoke(input_)
    except Exception as exc:  # pragma: no cover - exercised only on provider failure
        raise AssertionError(f"LLM capability call failed: {type(exc).__name__}") from None


def test_basic_chat() -> None:
    response = _redacted_invoke(_model(), "Reply with exactly: READY")
    assert response.content


def test_tool_calling() -> None:
    @tool
    def echo_case(case_id: str) -> dict[str, str]:
        """Return the supplied AML case identifier."""

        return {"case_id": case_id}

    model = _model().bind_tools([echo_case], tool_choice="required")
    response = _redacted_invoke(
        model,
        "Call echo_case exactly once with case_id CASE-CAPABILITY.",
    )
    assert response.tool_calls
    assert response.tool_calls[0]["name"] == "echo_case"
    assert response.tool_calls[0]["args"]["case_id"] == "CASE-CAPABILITY"


def test_tool_strategy_structured_output() -> None:
    agent = create_agent(
        model=_model(),
        tools=[],
        response_format=ToolStrategy(CapabilityResponse),
    )
    result = _redacted_invoke(
        agent,
        {"messages": [{"role": "user", "content": "Return status READY."}]},
    )
    structured = result.get("structured_response")
    assert isinstance(structured, CapabilityResponse)
    assert structured.status == "READY"
