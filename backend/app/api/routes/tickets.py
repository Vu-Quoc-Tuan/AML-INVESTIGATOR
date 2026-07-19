"""Ticket API over investigation_candidates + single-run and analyst review."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.detection.agent_adapter import is_laundering_suspect
from app.detection.config import DetectionSettings
from app.detection.contracts import CandidateRecord, CandidateStatus, ReviewDecision, RunTrigger
from app.detection.repository import (
    CandidateBusyError,
    DetectionRepository,
    ModeMismatchError,
)
from app.detection.runner import InvestigationQueueRunner
from app.investigation_control.repository import InvestigationControlRepository
from app.investigation_orchestrator import build_workflow
from app.investigation_events import (
    ExecutionEventRecorder,
    InvestigationEvent,
    InvestigationEventRepository,
    InvestigationEventType,
)

router = APIRouter(tags=["Tickets"])
logger = logging.getLogger(__name__)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVED", "REJECTED", "FALSE"]


def get_detection_repository() -> DetectionRepository:
    settings = DetectionSettings.from_env()
    return DetectionRepository(
        settings.db_path,
        initial_mode=settings.initial_run_mode,
        lease_seconds=settings.claim_lease_seconds,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
    )


def _ticket_message(record: CandidateRecord) -> str:
    """Human-readable list message for History UI.

    Preference order:
    1. Free-text on the transaction snapshot (description / memo / …) if present
    2. Investigation risk_rationale after multi-agent
    3. Detection rule hit reasons
    4. Compact amount + accounts fallback
    """

    snapshot = record.transaction_snapshot or {}
    for key in ("description", "narrative", "memo", "remark", "purpose"):
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:240]

    result = record.result or {}
    rationale = result.get("risk_rationale")
    if isinstance(rationale, str) and rationale.strip():
        return " ".join(rationale.split())[:240]

    if record.decision.rule_hits:
        reasons = [
            hit.reason.strip()
            for hit in record.decision.rule_hits
            if hit.reason and hit.reason.strip()
        ]
        if reasons:
            return "; ".join(reasons[:2])[:240]

    amount = snapshot.get("amount")
    currency = snapshot.get("currency") or "VND"
    source = snapshot.get("source_account_ref")
    destination = snapshot.get("destination_account_ref")
    parts: list[str] = []
    if isinstance(amount, (int, float)):
        parts.append(f"{amount:,.0f} {currency}")
    elif amount is not None:
        parts.append(f"{amount} {currency}")
    if source and destination:
        parts.append(f"{source} → {destination}")
    return " · ".join(parts) if parts else "No transaction description"


def _display_status(record: CandidateRecord, *, suspect: bool, review: str | None) -> str:
    """UI-facing status separate from raw queue status."""

    if review == "APPROVED":
        return "APPROVED"
    if review == "REJECTED":
        return "REJECTED"
    if review == "FALSE":
        return "FALSE"
    if record.status is CandidateStatus.PENDING:
        return "PENDING"
    if record.status is CandidateStatus.PROCESSING:
        return "RUNNING"
    if record.status is CandidateStatus.FAILED:
        return "FAILED"
    if record.status is CandidateStatus.COMPLETED and suspect and review is None:
        return "AWAITING_REVIEW"
    if record.status is CandidateStatus.COMPLETED:
        return "COMPLETED"
    return record.status.value


def _ticket_summary(record: CandidateRecord, *, max_attempts: int) -> dict[str, Any]:
    snapshot = record.transaction_snapshot or {}
    result = record.result or {}
    suspect = bool(result.get("is_laundering_suspect"))
    if not suspect and result:
        suspect = is_laundering_suspect(
            result.get("overall_risk_level"), result.get("recommended_action")
        )
    review = record.review_decision.value if record.review_decision else None
    can_review = (
        record.status is CandidateStatus.COMPLETED
        and review is None
        and suspect
    )
    return {
        "ticket_id": record.candidate_id,
        "event_id": record.event_id,
        "transaction_id": snapshot.get("transaction_id"),
        "status": record.status.value,
        "display_status": _display_status(record, suspect=suspect, review=review),
        "attempts": record.attempts,
        "case_id": record.case_id,
        "ml_confidence": record.decision.confidence,
        "overall_risk_level": result.get("overall_risk_level"),
        "is_laundering_suspect": suspect,
        "review_decision": review,
        "message": _ticket_message(record),
        "can_run": record.status in {CandidateStatus.PENDING, CandidateStatus.FAILED}
        and record.attempts < max_attempts,
        "can_review": can_review,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _ticket_detail(record: CandidateRecord, *, max_attempts: int) -> dict[str, Any]:
    decision = record.decision
    return {
        **_ticket_summary(record, max_attempts=max_attempts),
        "last_error": record.last_error,
        "transaction": record.transaction_snapshot,
        "detection": {
            "decision": decision.kind.value,
            "ml_confidence": decision.confidence,
            "model_version": decision.model_version,
            "rule_hits": [
                {
                    "rule_id": hit.rule_id,
                    "reason": hit.reason,
                    "evidence": hit.evidence,
                }
                for hit in decision.rule_hits
            ],
            "imputed_features": list(decision.imputed_features),
        },
        "result": record.result,
    }


@router.get("/tickets")
def list_tickets(
    status: CandidateStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repository: DetectionRepository = Depends(get_detection_repository),
) -> dict[str, Any]:
    items = repository.list_candidates(status=status, limit=limit, offset=offset)
    return {
        "items": [
            _ticket_summary(item, max_attempts=repository.max_attempts)
            for item in items
        ],
        "limit": limit,
        "offset": offset,
        "count": len(items),
    }


@router.get("/tickets/{ticket_id}")
def get_ticket(
    ticket_id: str,
    repository: DetectionRepository = Depends(get_detection_repository),
) -> dict[str, Any]:
    record = repository.get_candidate(ticket_id)
    if record is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return _ticket_detail(record, max_attempts=repository.max_attempts)


def get_event_repository() -> InvestigationEventRepository:
    settings = DetectionSettings.from_env()
    return InvestigationEventRepository(settings.db_path)


def format_sse_event(event: InvestigationEvent) -> str:
    payload = json.dumps(event.to_dict(), separators=(",", ":"), sort_keys=True)
    return f"id: {event.id}\nevent: investigation\ndata: {payload}\n\n"


async def stream_ticket_events(
    request: Request,
    repository: InvestigationEventRepository,
    ticket_id: str,
    *,
    after_id: int = 0,
    poll_seconds: float = 0.5,
    heartbeat_seconds: float = 15.0,
):
    cursor = after_id
    last_emit = time.monotonic()
    while not await request.is_disconnected():
        events = repository.list_after(ticket_id, after_id=cursor)
        terminal_seen = False
        for event in events:
            cursor = event.id
            last_emit = time.monotonic()
            yield format_sse_event(event)
            if event.terminal:
                terminal_seen = True
        if terminal_seen:
            yield "event: stream_end\ndata: {}\n\n"
            return
        if time.monotonic() - last_emit >= heartbeat_seconds:
            yield ": heartbeat\n\n"
            last_emit = time.monotonic()
        await asyncio.sleep(poll_seconds)


@router.get("/tickets/{ticket_id}/events")
async def ticket_events(
    ticket_id: str,
    request: Request,
    after_id: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    detection_repository: DetectionRepository = Depends(get_detection_repository),
    event_repository: InvestigationEventRepository = Depends(get_event_repository),
) -> StreamingResponse:
    if detection_repository.get_candidate(ticket_id) is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    cursor = after_id
    if last_event_id:
        try:
            cursor = max(cursor, int(last_event_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid Last-Event-ID") from exc
    return StreamingResponse(
        stream_ticket_events(
            request,
            event_repository,
            ticket_id,
            after_id=cursor,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _run_ticket_job(candidate: CandidateRecord) -> None:
    settings = DetectionSettings.from_env()
    repository = DetectionRepository(
        settings.db_path,
        initial_mode=settings.initial_run_mode,
        lease_seconds=settings.claim_lease_seconds,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
    )
    control = InvestigationControlRepository(settings.db_path)
    agent_settings = control.get_agent_settings()

    def workflow_factory(event_repository=None) -> Any:
        return build_workflow(
            agent_settings=agent_settings,
            event_repository=event_repository,
        )

    runner = InvestigationQueueRunner(repository, workflow_factory)
    runner.run_claimed(candidate)


@router.post("/tickets/{ticket_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_ticket(
    ticket_id: str,
    background_tasks: BackgroundTasks,
    repository: DetectionRepository = Depends(get_detection_repository),
) -> dict[str, Any]:
    """Start multi-agent for exactly one PENDING ticket (MANUAL mode, one-at-a-time)."""

    record = repository.get_candidate(ticket_id)
    if record is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    if record.status not in {CandidateStatus.PENDING, CandidateStatus.FAILED}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "NOT_RUNNABLE",
                "message": (
                    f"only PENDING or retryable FAILED tickets can be run manually "
                    f"(got {record.status.value})"
                ),
            },
        )
    if record.attempts >= repository.max_attempts:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RETRY_LIMIT_REACHED",
                "message": "ticket reached the maximum investigation attempts",
            },
        )
    try:
        claimed = repository.claim_candidate(
            ticket_id,
            RunTrigger.MANUAL,
            require_idle=True,
        )
    except ModeMismatchError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "MODE_MISMATCH", "message": str(exc)},
        ) from exc
    except CandidateBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ALREADY_RUNNING",
                "message": str(exc),
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "NOT_RUNNABLE", "message": str(exc)},
        ) from exc

    try:
        background_tasks.add_task(_run_ticket_job, claimed)
    except Exception as exc:
        repository.mark_failed(
            claimed.candidate_id,
            f"{type(exc).__name__}: background scheduling failed",
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SCHEDULING_FAILED",
                "message": "could not schedule investigation",
            },
        ) from exc
    return {
        "ticket_id": ticket_id,
        "status": "ACCEPTED",
        "message": "investigation started in background",
    }


@router.post("/tickets/{ticket_id}/review")
def review_ticket(
    ticket_id: str,
    request: ReviewRequest,
    repository: DetectionRepository = Depends(get_detection_repository),
) -> dict[str, Any]:
    decision = ReviewDecision(request.decision)
    try:
        record = repository.set_review_decision(ticket_id, decision)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ticket not found") from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "REVIEW_CONFLICT", "message": str(exc)},
        ) from exc
    if record.case_id:
        try:
            ExecutionEventRecorder(
                InvestigationEventRepository(repository.db_path),
                ticket_id=record.candidate_id,
                case_id=record.case_id,
            ).append(
                InvestigationEventType.REVIEW_DECIDED,
                status=decision.value,
                summary=f"Review decision: {decision.value}",
                payload={"decision": decision.value},
            )
        except Exception as exc:
            logger.error(
                "review event append failed ticket_id=%s error_type=%s",
                record.candidate_id,
                type(exc).__name__,
            )
    return _ticket_detail(record, max_attempts=repository.max_attempts)
