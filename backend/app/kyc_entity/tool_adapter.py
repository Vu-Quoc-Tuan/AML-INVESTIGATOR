"""LangChain boundary for backend-owned KYC and ownership capabilities."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.evidence import KycEvidence

from .exceptions import (
    EntityNotFoundError,
    EntityScopeViolationError,
    EvidenceConflictError,
    EvidenceContractError,
    KycEntityError,
    OwnershipTraversalError,
)
from .facade import KycEntityFacade


class StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyAsOfInput(StrictToolInput):
    company_id: str = Field(min_length=1)
    as_of_date: date


class EntityInput(StrictToolInput):
    entity_id: str = Field(min_length=1)


class OwnershipInput(CompanyAsOfInput):
    max_depth: int = Field(default=3, ge=1, le=5)


class UboInput(OwnershipInput):
    ownership_threshold: float = Field(default=0.25, gt=0, le=1)


class KycEvidenceBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    visibility_level: str = Field(min_length=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class KycToolBoundary(BaseModel):
    """Local mirror of the orchestrator's JSON-safe tool result contract."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["SUCCESS", "NO_DATA", "INCONCLUSIVE", "ERROR"]
    data: JsonValue = None
    evidence: list[KycEvidenceBoundary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None

    @model_validator(mode="after")
    def enforce_error_code(self) -> "KycToolBoundary":
        if self.status == "ERROR" and not self.error_code:
            raise ValueError("ERROR tool results require error_code")
        if self.status != "ERROR" and self.error_code:
            raise ValueError("error_code is only valid for ERROR tool results")
        return self


def _evidence(items: Sequence[KycEvidence]) -> list[KycEvidenceBoundary]:
    return [
        KycEvidenceBoundary(
            evidence_id=item.evidence_id,
            source_system=item.source_type,
            source_record_id=item.source_record_id,
            visibility_level=item.visibility_level,
            payload={
                "statement": item.statement,
                "attributes": item.model_dump(mode="json")["attributes"],
            },
        )
        for item in items
    ]


def _model_data(result: BaseModel) -> dict[str, JsonValue]:
    data = result.model_dump(mode="json")
    data.pop("evidence", None)
    return data


def _success(
    data: dict[str, JsonValue], evidence: Sequence[KycEvidence]
) -> KycToolBoundary:
    return KycToolBoundary(
        status="SUCCESS",
        data={"entity_scope": "SHB_INTERNAL", **data},
        evidence=_evidence(evidence),
    )


def _known_error(exc: KycEntityError) -> KycToolBoundary:
    if isinstance(exc, EntityNotFoundError):
        return KycToolBoundary(status="NO_DATA", warnings=["ENTITY_NOT_FOUND"])
    if isinstance(exc, OwnershipTraversalError):
        return KycToolBoundary(
            status="INCONCLUSIVE", warnings=["OWNERSHIP_TRAVERSAL_ERROR"]
        )

    code = "KYC_ENTITY_ERROR"
    if isinstance(exc, EntityScopeViolationError):
        code = "ENTITY_SCOPE_VIOLATION"
    elif isinstance(exc, EvidenceContractError):
        code = "EVIDENCE_CONTRACT_ERROR"
    elif isinstance(exc, EvidenceConflictError):
        code = "EVIDENCE_CONFLICT"
    return KycToolBoundary(
        status="ERROR",
        warnings=[code],
        error_code=code,
    )


def _tool_response(boundary: KycToolBoundary) -> tuple[str, dict[str, Any]]:
    artifact = boundary.model_dump(mode="json")
    return (
        json.dumps(artifact, ensure_ascii=False, sort_keys=True, allow_nan=False),
        artifact,
    )


def _invoke(operation: Callable[[], KycToolBoundary]) -> tuple[str, dict[str, Any]]:
    try:
        boundary = operation()
    except KycEntityError as exc:
        boundary = _known_error(exc)
    return _tool_response(boundary)


def build_kyc_tools(facade: KycEntityFacade | None = None) -> tuple[BaseTool, ...]:
    """Return the minimal approved KYC tool set for owner registration."""

    kyc_facade = facade or KycEntityFacade()

    def get_company_profile(
        company_id: str, as_of_date: date
    ) -> tuple[str, dict[str, Any]]:
        def operation() -> KycToolBoundary:
            result = kyc_facade.get_company_profile(company_id, as_of_date)
            return _success(_model_data(result), result.evidence)

        return _invoke(operation)

    def get_kyc_documents(entity_id: str) -> tuple[str, dict[str, Any]]:
        def operation() -> KycToolBoundary:
            result = kyc_facade.get_kyc_documents(entity_id)
            return _success(_model_data(result), result.evidence)

        return _invoke(operation)

    def build_ownership_graph(
        company_id: str, as_of_date: date, max_depth: int = 3
    ) -> tuple[str, dict[str, Any]]:
        def operation() -> KycToolBoundary:
            result = kyc_facade.build_ownership_graph(
                company_id, as_of_date, max_depth
            )
            return _success(_model_data(result), result.evidence)

        return _invoke(operation)

    def calculate_ubo(
        company_id: str,
        as_of_date: date,
        max_depth: int = 3,
        ownership_threshold: float = 0.25,
    ) -> tuple[str, dict[str, Any]]:
        def operation() -> KycToolBoundary:
            graph = kyc_facade.build_ownership_graph(
                company_id, as_of_date, max_depth
            )
            result = kyc_facade.calculate_ubo(graph, ownership_threshold)
            return _success(
                {"graph_id": graph.graph_id, **_model_data(result)},
                result.evidence,
            )

        return _invoke(operation)

    def find_ownership_gaps(
        company_id: str, as_of_date: date, max_depth: int = 3
    ) -> tuple[str, dict[str, Any]]:
        def operation() -> KycToolBoundary:
            graph = kyc_facade.build_ownership_graph(
                company_id, as_of_date, max_depth
            )
            gaps = kyc_facade.find_ownership_gaps(graph)
            return _success(
                {
                    "graph_id": graph.graph_id,
                    "root_company_id": graph.root_company_id,
                    "ownership_gaps": [gap.model_dump(mode="json") for gap in gaps],
                },
                graph.evidence,
            )

        return _invoke(operation)

    definitions = (
        (
            get_company_profile,
            "Retrieve the verified SHB company KYC profile as of a bounded date.",
            CompanyAsOfInput,
        ),
        (
            get_kyc_documents,
            "Retrieve KYC documents and evidence for one SHB-internal entity.",
            EntityInput,
        ),
        (
            build_ownership_graph,
            "Build a bounded ownership graph for one SHB-internal company.",
            OwnershipInput,
        ),
        (
            calculate_ubo,
            "Build a trusted ownership graph and calculate verified UBO candidates.",
            UboInput,
        ),
        (
            find_ownership_gaps,
            "Build a trusted ownership graph and identify evidence-backed gaps.",
            OwnershipInput,
        ),
    )
    return tuple(
        StructuredTool.from_function(
            func=function,
            name=function.__name__,
            description=description,
            args_schema=args_schema,
            response_format="content_and_artifact",
        )
        for function, description, args_schema in definitions
    )
