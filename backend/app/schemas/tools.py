from typing import Any
from pydantic import BaseModel, Field

from .common import (
    GraphSnapshot,
    PatternFinding,
    CounterpartySummary,
    FundPath,
)

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
