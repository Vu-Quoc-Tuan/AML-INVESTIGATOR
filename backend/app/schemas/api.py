from pydantic import BaseModel, Field
from typing import List, Optional

class AccountRequest(BaseModel):
    account_id: str = Field(..., description="The ID of the account to analyze")
    time_window_hours: float = Field(default=24.0, description="Time window in hours")

class MultiAccountRequest(BaseModel):
    account_ids: List[str] = Field(..., description="List of account IDs to analyze")
    time_window_hours: float = Field(default=24.0, description="Time window in hours")

class TraceFundsRequest(BaseModel):
    seed_account_ids: List[str] = Field(..., description="Accounts to trace from")
    direction: str = Field(..., description="FORWARD or BACKWARD")
    max_depth: int = Field(default=3, description="Maximum hops to trace")
    start_time: Optional[str] = None
    end_time: Optional[str] = None

class GraphRiskRequest(BaseModel):
    graph_snapshot: dict = Field(..., description="Graph snapshot dictionary")

class SubgraphRequest(BaseModel):
    seed_entity_ids: List[str] = Field(..., description="Entities to build graph around")
    max_depth: int = Field(default=2)
