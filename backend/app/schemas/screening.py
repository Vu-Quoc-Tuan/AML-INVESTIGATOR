"""Validated, JSON-safe contracts owned by the screening agent."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


EntityScope = Literal["SHB_INTERNAL", "EXTERNAL_OBSERVED"]
EntityType = Literal["INDIVIDUAL", "ORGANIZATION"]
ScreeningType = Literal["SANCTIONS", "PEP", "WATCHLIST", "ADVERSE_MEDIA"]
ScreeningStatus = Literal["SUCCESS", "NO_DATA", "INCONCLUSIVE", "ERROR"]
ScreeningConclusion = Literal[
    "CONFIRMED_MATCH",
    "POTENTIAL_MATCH",
    "NO_MATCH",
    "UNABLE_TO_SCREEN",
]
MatchBasis = Literal[
    "IDENTIFIER",
    "MULTI_ATTRIBUTE",
    "NAME_ONLY",
    "INSUFFICIENT_DATA",
]


class ScreeningSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1)
    entity_scope: EntityScope
    entity_type: EntityType
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    date_of_birth: date | None = None
    nationalities: list[str] = Field(default_factory=list)
    country: str | None = None
    national_id: str | None = None
    passport_number: str | None = None
    registration_number: str | None = None


class ScreeningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    subject: ScreeningSubject
    screening_types: list[ScreeningType] = Field(
        default_factory=lambda: ["SANCTIONS", "PEP"]
    )
    as_of_date: date
    candidate_limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def require_screening_type(self) -> "ScreeningRequest":
        if not self.screening_types:
            raise ValueError("screening_types must not be empty")
        return self


class ScreeningEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    visibility_level: EntityScope
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class ScreeningCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    list_type: ScreeningType
    source_name: str = Field(min_length=1)
    matched_name: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    match_basis: MatchBasis
    matched_attributes: list[str] = Field(default_factory=list)
    conflicting_attributes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ScreeningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    entity_scope: EntityScope
    status: ScreeningStatus
    conclusion: ScreeningConclusion
    candidates: list[ScreeningCandidate] = Field(default_factory=list)
    evidence: list[ScreeningEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None

    @model_validator(mode="after")
    def enforce_status_contract(self) -> "ScreeningResponse":
        if self.status == "ERROR" and not self.error_code:
            raise ValueError("ERROR responses require error_code")
        if self.status != "ERROR" and self.error_code:
            raise ValueError("error_code is only valid for ERROR responses")
        if self.conclusion == "CONFIRMED_MATCH" and not any(
            candidate.match_basis in {"IDENTIFIER", "MULTI_ATTRIBUTE"}
            for candidate in self.candidates
        ):
            raise ValueError("CONFIRMED_MATCH requires a strong candidate")
        return self
