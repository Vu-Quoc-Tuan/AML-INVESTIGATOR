"""Dashboard metrics from durable detection/ticket storage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.detection.config import DetectionSettings
from app.detection.repository import DetectionRepository

router = APIRouter(prefix="/metrics", tags=["Metrics"])


def get_detection_repository() -> DetectionRepository:
    settings = DetectionSettings.from_env()
    return DetectionRepository(
        settings.db_path,
        initial_mode=settings.initial_run_mode,
        lease_seconds=settings.claim_lease_seconds,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
    )


@router.get("/flow-trends")
def flow_trends(
    days: int = Query(default=7, ge=1, le=90),
    repository: DetectionRepository = Depends(get_detection_repository),
) -> dict[str, Any]:
    """
    Daily detection outcomes for the dashboard chart.

    - ``flagged`` / ``queued``: investigation candidates created that day
    - ``blocked``: high-confidence blocked rows created that day
    - ``volume``: queued + blocked (durable outcomes; ALLOWED is not stored)
    """

    items = repository.flow_trends(days=days)
    return {"days": days, "items": items}
