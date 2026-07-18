"""Shared Case File state contracts."""

from pydantic import BaseModel, ConfigDict, Field

from .evidence import KycEvidence
from .kyc_entity import (
    Contradiction,
    IdentifiedUbo,
    KycFinding,
    MissingDocument,
    NormalizedEntity,
    OwnershipGap,
    OwnershipGraphResult,
    ProfileMismatch,
    VisibilitySummary,
)


class SharedCaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    revision: int = 0
    normalized_entities: list[NormalizedEntity] = Field(default_factory=list)
    kyc_findings: list[KycFinding] = Field(default_factory=list)
    profile_mismatches: list[ProfileMismatch] = Field(default_factory=list)
    ownership_graphs: list[OwnershipGraphResult] = Field(default_factory=list)
    identified_ubos: list[IdentifiedUbo] = Field(default_factory=list)
    ownership_gaps: list[OwnershipGap] = Field(default_factory=list)
    missing_documents: list[MissingDocument] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    evidence: list[KycEvidence] = Field(default_factory=list)
    visibility_summary: VisibilitySummary = Field(default_factory=VisibilitySummary)
