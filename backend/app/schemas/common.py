from enum import Enum
from typing import Any
from datetime import datetime
from pydantic import BaseModel, Field

class TransactionDirection(str, Enum):
    INTERNAL = "INTERNAL"
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"

class TraceDirection(str, Enum):
    BACKWARD = "BACKWARD"
    FORWARD = "FORWARD"

class PatternType(str, Enum):
    FAN_IN = "FAN_IN"
    FAN_OUT = "FAN_OUT"
    RAPID_PASS_THROUGH = "RAPID_PASS_THROUGH"
    GATHER_SCATTER = "GATHER_SCATTER"
    SCATTER_GATHER = "SCATTER_GATHER"
    COMMON_FUNDING_SOURCE = "COMMON_FUNDING_SOURCE"
    COMMON_DESTINATION = "COMMON_DESTINATION"
    CYCLE = "CYCLE"
    ROUND_TRIPPING = "ROUND_TRIPPING"
    COORDINATED_AMOUNTS = "COORDINATED_AMOUNTS"
    STRUCTURING = "STRUCTURING"

class NodeType(str, Enum):
    ACCOUNT = "ACCOUNT"
    PERSON = "PERSON"
    COMPANY = "COMPANY"
    BANK = "BANK"
    CRYPTO_PLATFORM = "CRYPTO_PLATFORM"
    DEVICE = "DEVICE"
    IP_ADDRESS = "IP_ADDRESS"
    ADDRESS = "ADDRESS"
    PHONE = "PHONE"

class EdgeType(str, Enum):
    TRANSFERRED_TO = "TRANSFERRED_TO"
    OWNS_ACCOUNT = "OWNS_ACCOUNT"
    USES_DEVICE = "USES_DEVICE"
    USES_IP = "USES_IP"
    SHARES_ADDRESS = "SHARES_ADDRESS"
    FUNDED_BY = "FUNDED_BY"
    BENEFICIARY_AT = "BENEFICIARY_AT"

class GraphNode(BaseModel):
    id: str
    node_type: NodeType
    attributes: dict[str, Any]

class GraphEdge(BaseModel):
    source: str
    target: str
    edge_type: EdgeType
    key: str | None = None
    attributes: dict[str, Any]

class GraphSnapshot(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    metadata: dict[str, Any] = Field(default_factory=dict)

class PatternFinding(BaseModel):
    finding_type: PatternType
    statement: str
    evidence_ids: list[str]
    confidence: float

class CounterpartySummary(BaseModel):
    account_id: str
    total_amount: float
    txn_count: int
    direction: TransactionDirection

class FundPath(BaseModel):
    path: list[str]
    transactions: list[str]
    total_amount: float
    timestamps: list[datetime]
