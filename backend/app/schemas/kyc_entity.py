"""Strict input and output contracts for Person 3 capabilities."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence import KycEvidence


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObservedTransactionFeatures(StrictModel):
    entity_id: str
    window_start: datetime
    window_end: datetime
    account_ids: list[str] = Field(min_length=1)
    external_counterparty_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | bool | list[str]] = Field(min_length=1)
    metric_evidence_ids: dict[str, list[str]]

    @model_validator(mode="after")
    def validate_metric_evidence(self) -> ObservedTransactionFeatures:
        if self.window_end < self.window_start:
            raise ValueError("window_end must not precede window_start")
        missing = [key for key in self.metrics if not self.metric_evidence_ids.get(key)]
        if missing:
            raise ValueError(f"metrics missing evidence: {sorted(missing)}")
        return self


class NormalizedIdentity(StrictModel):
    display_name: str | None = None
    standardized_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    date_of_birth: str | None = None
    national_id: str | None = None
    passport: str | None = None
    registration_number: str | None = None
    phone: str | None = None
    email: str | None = None
    address_tokens: list[str] = Field(default_factory=list)
    external_account_id: str | None = None
    masked_account_number: str | None = None
    bank_id: str | None = None
    identity_scope: str = "FULL_INTERNAL"


class NormalizedEntity(StrictModel):
    resolution_id: str
    entity_id: str | None = None
    entity_type: str
    standardized_name: str
    confidence: float = Field(ge=0, le=1)
    decision: str
    identity_scope: str
    ubo_eligible: bool
    matched_fields: list[str] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)


class KycFinding(StrictModel):
    finding_id: str
    type: str
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    severity: str = "MEDIUM"


class ProfileMismatch(StrictModel):
    mismatch_id: str
    type: str
    declared_value: Any
    observed_value: Any
    evidence_ids: list[str] = Field(min_length=2)
    severity: str


class OwnershipNode(StrictModel):
    node_id: str
    entity_type: str
    display_name: str | None = None
    identity_scope: str = "FULL_INTERNAL"


class OwnershipEdge(StrictModel):
    ownership_id: str
    owned_company_id: str
    owner_entity_id: str
    owner_entity_type: str
    direct_percentage: float = Field(gt=0)
    verified: bool
    source_document_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class OwnershipGraphResult(StrictModel):
    graph_id: str
    root_company_id: str
    as_of_date: date
    max_depth: int = Field(ge=1)
    nodes: list[OwnershipNode] = Field(default_factory=list)
    edges: list[OwnershipEdge] = Field(default_factory=list)
    ownership_coverage_percentage: float = Field(ge=0)
    ownership_status: str
    ownership_cycle_detected: bool = False
    ownership_cycles: list[list[str]] = Field(default_factory=list)
    unresolved_relationship_ids: list[str] = Field(default_factory=list)
    evidence: list[KycEvidence] = Field(default_factory=list)


class IdentifiedUbo(StrictModel):
    ubo_result_id: str
    ubo_id: str
    ownership_percentage: float = Field(ge=0)
    verified: bool
    paths: list[list[str]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class OwnershipGap(StrictModel):
    gap_id: str
    type: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)


class MissingDocument(StrictModel):
    missing_document_id: str
    type: str
    description: str


class Contradiction(StrictModel):
    contradiction_id: str
    type: str
    field: str
    declared: Any
    observed: Any
    evidence_a: str
    evidence_b: str
    additional_evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def distinct_primary_evidence(self) -> Contradiction:
        if self.evidence_a == self.evidence_b:
            raise ValueError("contradiction requires two distinct evidence records")
        return self


class VisibilitySummary(StrictModel):
    internal_entities: list[str] = Field(default_factory=list)
    external_entities: list[str] = Field(default_factory=list)


class CustomerKycSnapshot(StrictModel):
    entity: dict[str, Any]
    address: dict[str, Any] | None
    accounts: list[dict[str, Any]]
    kyc_profile: dict[str, Any] | None
    documents: list[dict[str, Any]]
    missing_documents: list[MissingDocument] = Field(default_factory=list)
    evidence: list[KycEvidence] = Field(default_factory=list)
    visibility: str = "FULL_INTERNAL"


class CompanyProfileSnapshot(CustomerKycSnapshot):
    representative: dict[str, Any] | None
    direct_owners: list[dict[str, Any]]
    ownership_coverage_percentage: float
    ownership_status: str


class AccountOwnerSnapshot(StrictModel):
    account_id: str
    owner_entity_id: str
    owner_entity_type: str
    snapshot: CustomerKycSnapshot | CompanyProfileSnapshot
    evidence: list[KycEvidence] = Field(default_factory=list)


class DocumentValidity(StrictModel):
    document_id: str
    classification: str
    as_of_date: date
    evidence_id: str


class DocumentAnalysisResult(StrictModel):
    documents: list[dict[str, Any]] = Field(default_factory=list)
    validity: list[DocumentValidity] = Field(default_factory=list)
    findings: list[KycFinding] = Field(default_factory=list)
    missing_documents: list[MissingDocument] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    evidence: list[KycEvidence] = Field(default_factory=list)


class EntityResolutionResult(StrictModel):
    normalized_input: NormalizedIdentity
    candidates: list[NormalizedEntity] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    evidence: list[KycEvidence] = Field(default_factory=list)


class UboCalculationResult(StrictModel):
    identified_ubos: list[IdentifiedUbo] = Field(default_factory=list)
    ownership_gaps: list[OwnershipGap] = Field(default_factory=list)
    findings: list[KycFinding] = Field(default_factory=list)
    evidence: list[KycEvidence] = Field(default_factory=list)


class ProfileDeviationResult(StrictModel):
    profile_mismatches: list[ProfileMismatch] = Field(default_factory=list)
    evidence: list[KycEvidence] = Field(default_factory=list)
    visibility_summary: VisibilitySummary = Field(default_factory=VisibilitySummary)


class ContradictionResult(StrictModel):
    contradictions: list[Contradiction] = Field(default_factory=list)
    missing_documents: list[MissingDocument] = Field(default_factory=list)
    evidence: list[KycEvidence] = Field(default_factory=list)


class KycCaseContribution(StrictModel):
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
