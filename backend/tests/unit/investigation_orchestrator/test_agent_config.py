from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.investigation_orchestrator.agent_config import (
    AgentSetting,
    AgentSettingsBundle,
)


def test_agent_settings_bundle_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate agent ids: planner"):
        AgentSettingsBundle(
            agents=[
                AgentSetting(id="planner", model_id="model-a"),
                AgentSetting(id="planner", model_id="model-b"),
            ]
        )


def test_agent_settings_bundle_keeps_unique_settings_by_id() -> None:
    bundle = AgentSettingsBundle(
        agents=[
            AgentSetting(id="planner", model_id="model-a"),
            AgentSetting(id="report", model_id="model-b"),
        ]
    )

    assert bundle.by_id()["planner"].model_id == "model-a"
    assert bundle.by_id()["report"].model_id == "model-b"
