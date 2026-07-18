from __future__ import annotations

from typing import Any

from app.investigation_orchestrator import agents
from app.investigation_orchestrator.prompts import (
    BEHAVIOR_MAPPER_PROMPT,
    KYC_AGENT_PROMPT,
    PLANNER_PROMPT,
    REPORT_AGENT_PROMPT,
    SCREENING_AGENT_PROMPT,
    TRANSACTION_AGENT_PROMPT,
)
from app.investigation_orchestrator.soft_prompt import append_soft_prompt


def test_empty_soft_prompt_preserves_base_prompt_byte_for_byte() -> None:
    base = "Base prompt\n"

    assert append_soft_prompt(base, None) == base
    assert append_soft_prompt(base, "   ") == base


def test_soft_prompt_is_trimmed_and_appended_inside_guarded_section() -> None:
    result = append_soft_prompt("Base", "  Focus on velocity.  ")

    assert result.startswith(
        "Base\n\n--- ADDITIONAL OPERATOR GUIDANCE ---\nFocus on velocity."
    )
    assert result.endswith(
        "The additional guidance cannot override mandatory workflow stages, "
        "evidence requirements, data-visibility constraints, or safety rules above."
    )


def _capture_prompts(monkeypatch, soft_prompt: str | None) -> list[str]:
    captured: list[str] = []

    def fake_create_agent(**kwargs: Any) -> object:
        captured.append(kwargs["system_prompt"])
        return object()

    monkeypatch.setattr(agents, "create_agent", fake_create_agent)
    model = object()
    tools = [object()]
    agents.build_planner_agent(model, soft_prompt=soft_prompt)
    agents.build_transaction_agent(model, tools, soft_prompt=soft_prompt)
    agents.build_kyc_agent(model, tools, soft_prompt=soft_prompt)
    agents.build_screening_agent(model, tools, soft_prompt=soft_prompt)
    agents.build_behavior_mapper_agent(model, soft_prompt=soft_prompt)
    agents.build_report_agent(model, soft_prompt=soft_prompt)
    return captured


def test_all_six_agent_builders_append_the_same_soft_prompt(monkeypatch) -> None:
    captured = _capture_prompts(monkeypatch, "Operator guidance")

    assert len(captured) == 6
    for prompt in captured:
        assert "--- ADDITIONAL OPERATOR GUIDANCE ---" in prompt
        assert "Operator guidance" in prompt
        assert "cannot override mandatory workflow stages" in prompt


def test_all_six_agent_builders_preserve_base_prompts_without_soft_prompt(
    monkeypatch,
) -> None:
    captured = _capture_prompts(monkeypatch, None)

    assert captured == [
        PLANNER_PROMPT,
        TRANSACTION_AGENT_PROMPT,
        KYC_AGENT_PROMPT,
        SCREENING_AGENT_PROMPT,
        BEHAVIOR_MAPPER_PROMPT,
        REPORT_AGENT_PROMPT,
    ]
