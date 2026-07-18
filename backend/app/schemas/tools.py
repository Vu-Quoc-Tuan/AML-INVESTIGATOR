"""Strict backend-owned tool input and context contracts."""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .common import CounterpartySummary, FundPath, GraphSnapshot, PatternFinding
from .kyc_entity import ObservedTransactionFeatures, OwnershipGraphResult


class GetAccountTransactionsOutput(BaseModel):
    transactions: list[dict[str, Any]]
    counterparty_summary: list[CounterpartySummary]
    total_inbound_amount: float
    total_outbound_amount: float
    net_flow: float
    count: int


class TraceFundsOutput(BaseModel):
    paths: list[FundPath]
    visited_accounts: list[str]
    graph_snapshot: GraphSnapshot


class DetectFanInOutOutput(BaseModel):
    fan_in_findings: list[PatternFinding]
    fan_out_findings: list[PatternFinding]


class DetectRapidPassThroughOutput(BaseModel):
    pass_through_findings: list[PatternFinding]


class DetectStructuringOutput(BaseModel):
    structuring_findings: list[PatternFinding]


class DetectCyclesOutput(BaseModel):
    cycles: list[list[str]]
    cycle_findings: list[PatternFinding]


class FindCommonSourcesOutput(BaseModel):
    common_sources: list[str]
    findings: list[PatternFinding]


class FindCommonDestinationsOutput(BaseModel):
    common_destinations: list[str]
    findings: list[PatternFinding]


class FindSharedIdentifiersOutput(BaseModel):
    shared_devices: list[str]
    shared_ips: list[str]
    shared_addresses: list[str]
    findings: list[PatternFinding]


class FindCoordinatedAmountsOutput(BaseModel):
    findings: list[PatternFinding]


class DetectRoundTrippingOutput(BaseModel):
    findings: list[PatternFinding]


class CalculateGraphRiskOutput(BaseModel):
    risk_scores: dict[str, float]
    network_metrics: dict[str, float]
    findings: list[PatternFinding]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KycToolContext(ToolInput):
    case_id: str
    as_of_date: date


class AccountOwnerInput(ToolInput):
    account_id: str


class CustomerInput(ToolInput):
    customer_id: str


class CompanyInput(ToolInput):
    company_id: str


class EntityInput(ToolInput):
    entity_id: str


class DocumentInput(ToolInput):
    document_id: str


class DocumentsValidityInput(ToolInput):
    document_ids: list[str]
    as_of_date: date


class ProfileComparisonInput(ToolInput):
    entity_id: str
    observed_transaction_features: ObservedTransactionFeatures


class NormalizeIdentityInput(ToolInput):
    raw_identity: dict[str, Any]


class ResolveEntityInput(ToolInput):
    input_entity: dict[str, Any]
    candidate_entities: list[dict[str, Any]]


class OwnershipGraphInput(ToolInput):
    company_id: str
    max_depth: int = Field(default=3, ge=1)


class CalculateUboInput(ToolInput):
    ownership_graph: OwnershipGraphResult
    ownership_threshold: float = Field(default=0.25, gt=0, le=1)


class OwnershipGraphPayloadInput(ToolInput):
    ownership_graph: OwnershipGraphResult


class FlagUnverifiedUboInput(ToolInput):
    company_id: str
    max_depth: int = Field(default=3, ge=1)
