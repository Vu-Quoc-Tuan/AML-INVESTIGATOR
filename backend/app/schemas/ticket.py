"""Pydantic schemas for the AML Alert Ticket system."""

from enum import Enum
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    """Alert severity level based on ML confidence score."""
    WARNING = "WARNING"       # 60% <= confidence < 95%
    DANGEROUS = "DANGEROUS"   # confidence >= 95%


class TicketCreate(BaseModel):
    """Schema for creating a new ticket from the Kafka consumer."""
    transaction_id: str
    confidence: float = Field(..., ge=0.0, le=1.0, description="ML model confidence (0.0-1.0)")
    is_suspicious: bool = Field(..., description="Final ML conclusion")
    status: TicketStatus
    transaction_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Original transaction data fields from CSV"
    )


class TicketResponse(BaseModel):
    """Schema for a single ticket returned by the API."""
    ticket_id: str = Field(..., description="Auto-generated ticket ID, e.g. TICKET-00001")
    transaction_id: str
    confidence: float
    is_suspicious: bool
    status: TicketStatus
    transaction_data: dict[str, Any]
    created_at: datetime


class TicketListResponse(BaseModel):
    """Paginated list of tickets."""
    total: int
    page: int
    page_size: int
    tickets: list[TicketResponse]


class TicketStatsResponse(BaseModel):
    """Aggregate statistics for the ticket dashboard."""
    total_tickets: int
    warning_count: int
    dangerous_count: int
    avg_confidence: float
    latest_ticket_at: datetime | None = None
