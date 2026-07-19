"""Per-agent model + soft-prompt configuration API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.detection.config import DetectionSettings
from app.detection.repository import DetectionRepository
from app.investigation_control.repository import InvestigationControlRepository
from app.investigation_orchestrator.agent_config import (
    AGENT_LABELS,
    AgentSetting,
    AgentSettingsBundle,
)
from app.investigation_orchestrator.model import (
    ModelConfigurationError,
    discover_llm_profiles,
    get_llm_profile,
)

router = APIRouter(prefix="/agent-settings", tags=["Agent Settings"])


class AgentSettingView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    model_id: str | None = None
    soft_prompt: str | None = None


class AgentSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[AgentSettingView]


class AgentSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[AgentSetting] = Field(min_length=1)


def get_control_repository() -> InvestigationControlRepository:
    settings = DetectionSettings.from_env()
    DetectionRepository(
        settings.db_path,
        initial_mode=settings.initial_run_mode,
        lease_seconds=settings.claim_lease_seconds,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
    )
    return InvestigationControlRepository(settings.db_path)


def _validate_model_ids(bundle: AgentSettingsBundle) -> None:
    known = {profile.id for profile in discover_llm_profiles()}
    for agent in bundle.agents:
        if agent.model_id is None:
            continue
        if known and agent.model_id not in known:
            # still allow if profile resolves (unique id)
            try:
                get_llm_profile(agent.model_id)
            except ModelConfigurationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "UNKNOWN_MODEL",
                        "message": (
                            f"agent {agent.id}: model_id {agent.model_id!r} "
                            f"is not in configured env profiles"
                        ),
                    },
                ) from exc


def _to_response(bundle: AgentSettingsBundle) -> AgentSettingsResponse:
    return AgentSettingsResponse(
        agents=[
            AgentSettingView(
                id=item.id,
                label=AGENT_LABELS.get(item.id, item.id),
                model_id=item.model_id,
                soft_prompt=item.soft_prompt,
            )
            for item in bundle.agents
        ]
    )


@router.get("", response_model=AgentSettingsResponse)
def get_agent_settings(
    repository: InvestigationControlRepository = Depends(get_control_repository),
) -> AgentSettingsResponse:
    return _to_response(repository.get_agent_settings())


@router.put("", response_model=AgentSettingsResponse)
def put_agent_settings(
    request: AgentSettingsUpdateRequest,
    repository: InvestigationControlRepository = Depends(get_control_repository),
) -> AgentSettingsResponse:
    from app.investigation_orchestrator.agent_config import AGENT_IDS

    current = repository.get_agent_settings().by_id()
    for item in request.agents:
        current[item.id] = item
    ordered = [
        current.get(agent_id) or AgentSetting(id=agent_id) for agent_id in AGENT_IDS
    ]
    bundle = AgentSettingsBundle(agents=ordered)
    _validate_model_ids(bundle)
    return _to_response(repository.set_agent_settings(bundle))
