"""LangChain tool boundary owned by the standalone screening agent."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.screening import (
    ScreeningEvidence,
    ScreeningRequest,
    ScreeningResponse,
    ScreeningSubject,
    ScreeningType,
)

from .facade import ScreeningFacade


class ScreeningToolBoundary(BaseModel):
    """Local mirror of the orchestrator's JSON tool contract.

    Keeping the model here prevents the screening domain from importing
    orchestrator implementation while contract tests can still validate the
    serialized result against ``ToolResult``.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["SUCCESS", "NO_DATA", "INCONCLUSIVE", "ERROR"]
    data: JsonValue = None
    evidence: list[ScreeningEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None

    @model_validator(mode="after")
    def enforce_error_code(self) -> "ScreeningToolBoundary":
        if self.status == "ERROR" and not self.error_code:
            raise ValueError("ERROR tool results require error_code")
        if self.status != "ERROR" and self.error_code:
            raise ValueError("error_code is only valid for ERROR tool results")
        return self


def _orchestrator_scope(scope: str) -> str:
    return "EXTERNAL" if scope == "EXTERNAL_OBSERVED" else scope


def _orchestrator_match_basis(match_basis: str) -> str:
    return "NAME" if match_basis == "NAME_ONLY" else match_basis


def _decisive_candidate(response: ScreeningResponse):
    if response.conclusion == "CONFIRMED_MATCH":
        return next(
            (
                candidate
                for candidate in response.candidates
                if candidate.match_basis in {"IDENTIFIER", "MULTI_ATTRIBUTE"}
                and not candidate.conflicting_attributes
            ),
            None,
        )
    return response.candidates[0] if response.candidates else None


def adapt_screening_response(response: ScreeningResponse) -> ScreeningToolBoundary:
    """Translate domain semantics without leaking orchestration into scoring."""

    decisive = _decisive_candidate(response)
    match_basis = (
        _orchestrator_match_basis(decisive.match_basis)
        if decisive is not None
        else "INSUFFICIENT_DATA"
    )
    if response.status == "INCONCLUSIVE" and response.conclusion == "POTENTIAL_MATCH":
        tool_status = "SUCCESS"
    else:
        tool_status = response.status
    available = tool_status == "SUCCESS"
    data: dict[str, JsonValue] = {
        "request_id": response.request_id,
        "subject_id": response.subject_id,
        "available": available,
        "entity_scope": _orchestrator_scope(response.entity_scope),
        "conclusion": response.conclusion,
        "match_basis": match_basis,
        "candidates": [
            candidate.model_dump(mode="json") for candidate in response.candidates
        ],
    }
    return ScreeningToolBoundary(
        status=tool_status,
        data=data,
        evidence=response.evidence,
        warnings=response.warnings,
        error_code=response.error_code,
    )


def build_screening_tools(
    facade: ScreeningFacade | None = None,
) -> tuple[BaseTool, ...]:
    """Return tools for explicit registration under the ``screening`` owner."""

    screening_facade = facade or ScreeningFacade()

    def screen_subject_against_watchlists(
        request_id: str,
        subject: ScreeningSubject,
        screening_types: list[ScreeningType],
        as_of_date: date,
        candidate_limit: int = 20,
    ) -> tuple[str, dict[str, Any]]:
        request = ScreeningRequest(
            request_id=request_id,
            subject=subject,
            screening_types=screening_types,
            as_of_date=as_of_date,
            candidate_limit=candidate_limit,
        )
        boundary = adapt_screening_response(screening_facade.screen(request))
        artifact = boundary.model_dump(mode="json")
        return json.dumps(artifact, ensure_ascii=False, sort_keys=True), artifact

    tool = StructuredTool.from_function(
        func=screen_subject_against_watchlists,
        name="screen_subject_against_watchlists",
        description=(
            "Screen one internal or externally observed subject against bounded "
            "sanctions, PEP, watchlist, and adverse-media candidates."
        ),
        args_schema=ScreeningRequest,
        response_format="content_and_artifact",
    )
    return (tool,)
