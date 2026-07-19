"""List and select OpenAI-compatible LLM profiles for multi-agent runs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.investigation_orchestrator.model import (
    ModelConfigurationError,
    discover_llm_profiles,
    get_selected_profile_id,
    set_selected_profile_id,
)

router = APIRouter(prefix="/models", tags=["Models"])


class ModelItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    model_name: str
    base_url: str


class ModelsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ModelItem]
    selected_id: str | None = None


class SelectModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)


class SelectModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_id: str


@router.get("", response_model=ModelsResponse)
def list_models() -> ModelsResponse:
    profiles = discover_llm_profiles()
    items = [
        ModelItem(id=p.id, model_name=p.model_name, base_url=p.base_url)
        for p in profiles
    ]
    selected = get_selected_profile_id()
    if selected is None and items:
        selected = items[0].id
    elif selected is not None and selected not in {item.id for item in items}:
        selected = items[0].id if items else None
    return ModelsResponse(items=items, selected_id=selected)


@router.put("/selected", response_model=SelectModelResponse)
def select_model(request: SelectModelRequest) -> SelectModelResponse:
    try:
        selected = set_selected_profile_id(request.id.strip())
    except ModelConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MODEL_NOT_FOUND", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return SelectModelResponse(selected_id=selected)
