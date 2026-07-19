from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.routes import tickets
from app.api.routes.tickets import ReviewRequest, _ticket_summary, review_ticket, run_ticket
from app.detection.contracts import DecisionKind, DetectionDecision, RunTrigger
from app.detection.repository import DetectionRepository
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


def _event(event_id: str) -> TransactionEventV1:
    now = datetime(2026, 7, 19, tzinfo=UTC)
    return TransactionEventV1.model_validate(
        {
            "event_id": event_id,
            "transaction_id": f"tx-{event_id}",
            "occurred_at": now,
            "ingested_at": now,
            "source_account_ref": "src",
            "destination_account_ref": "dst",
            "source_bank_id": HOME_BANK_ID,
            "destination_bank_id": HOME_BANK_ID,
            "amount": 100,
            "currency": "VND",
            "direction": "INTERNAL",
            "data_visibility": "FULL_INTERNAL",
        }
    )


def _enqueue(repository: DetectionRepository, event_id: str) -> str:
    return repository.enqueue_candidate(
        _event(event_id),
        DetectionDecision(DecisionKind.QUEUED, 0.8, "m1"),
    )


def test_run_ticket_claims_before_202_and_prevents_overlapping_runs(
    tmp_path: Path,
) -> None:
    repository = DetectionRepository(tmp_path / "queue.db")
    first_id = _enqueue(repository, "evt-1")
    second_id = _enqueue(repository, "evt-2")
    background_tasks = BackgroundTasks()

    response = run_ticket(first_id, background_tasks, repository)

    claimed = repository.get_candidate(first_id)
    assert response["status"] == "ACCEPTED"
    assert claimed is not None
    assert claimed.status.value == "PROCESSING"
    assert claimed.attempts == 1
    assert len(background_tasks.tasks) == 1

    with pytest.raises(HTTPException) as duplicate:
        run_ticket(first_id, BackgroundTasks(), repository)
    assert duplicate.value.status_code == 409
    assert duplicate.value.detail["code"] == "NOT_RUNNABLE"

    with pytest.raises(HTTPException) as overlap:
        run_ticket(second_id, BackgroundTasks(), repository)
    assert overlap.value.status_code == 409
    assert overlap.value.detail["code"] == "ALREADY_RUNNING"


def test_failed_ticket_is_retryable_only_while_attempts_remain(tmp_path: Path) -> None:
    repository = DetectionRepository(tmp_path / "queue.db", max_attempts=2)
    candidate_id = _enqueue(repository, "evt-1")
    first = repository.claim_candidate(candidate_id, RunTrigger.MANUAL)
    repository.mark_failed(first.candidate_id, "tool failed")

    failed = repository.get_candidate(candidate_id)
    assert failed is not None
    assert _ticket_summary(failed, max_attempts=2)["can_run"] is True

    second = repository.claim_candidate(candidate_id, RunTrigger.MANUAL)
    repository.mark_failed(second.candidate_id, "tool failed again")
    exhausted = repository.get_candidate(candidate_id)
    assert exhausted is not None
    assert _ticket_summary(exhausted, max_attempts=2)["can_run"] is False


def test_review_stays_persisted_when_audit_event_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DetectionRepository(tmp_path / "queue.db")
    candidate_id = _enqueue(repository, "evt-1")
    claimed = repository.claim_candidate(candidate_id, RunTrigger.MANUAL)
    repository.mark_completed(
        candidate_id,
        "case-1",
        result={"overall_risk_level": "HIGH", "recommended_action": "ESCALATE"},
    )

    class BrokenEventRepository:
        def __init__(self, db_path: Path) -> None:
            del db_path

        def append(self, **kwargs):
            del kwargs
            raise OSError("event store unavailable")

    monkeypatch.setattr(tickets, "InvestigationEventRepository", BrokenEventRepository)

    response = review_ticket(
        candidate_id,
        ReviewRequest(decision="APPROVED"),
        repository,
    )

    assert response["review_decision"] == "APPROVED"
    stored = repository.get_candidate(claimed.candidate_id)
    assert stored is not None
    assert stored.review_decision is not None
    assert stored.review_decision.value == "APPROVED"
