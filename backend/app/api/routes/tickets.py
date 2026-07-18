"""FastAPI router for AML Alert Tickets.

Provides REST endpoints so the frontend can query tickets created
by the Kafka consumer / ML inference pipeline.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.db.ticket_repository import get_ticket_repository
from app.schemas.ticket import (
    TicketListResponse,
    TicketResponse,
    TicketStatsResponse,
    TicketStatus,
)

router = APIRouter(prefix="/tickets", tags=["Tickets"])


@router.get("/stats", response_model=TicketStatsResponse)
def get_ticket_stats():
    """Return aggregate ticket statistics for the dashboard."""
    repo = get_ticket_repository()
    return repo.get_stats()


@router.get("", response_model=TicketListResponse)
def list_tickets(
    status: Optional[TicketStatus] = Query(None, description="Filter by ticket status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """List tickets with optional status filter and pagination."""
    repo = get_ticket_repository()
    tickets, total = repo.get_tickets(status=status, page=page, page_size=page_size)
    return TicketListResponse(
        total=total,
        page=page,
        page_size=page_size,
        tickets=tickets,
    )


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(ticket_id: str):
    """Retrieve a single ticket by its ID."""
    repo = get_ticket_repository()
    ticket = repo.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    return ticket
