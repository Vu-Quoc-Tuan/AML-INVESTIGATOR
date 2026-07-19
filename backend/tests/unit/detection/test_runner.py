from pathlib import Path

import pytest

from app.detection.contracts import DecisionKind, DetectionDecision, RunMode, RunTrigger
from app.detection.repository import DetectionRepository, ModeMismatchError
from app.detection.runner import InvestigationQueueRunner
from app.investigation_events import (
    InvestigationEventRepository,
    InvestigationEventType,
)
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1
from datetime import UTC, datetime


def event(event_id="evt-1"):
    now = datetime(2026, 7, 19, tzinfo=UTC)
    return TransactionEventV1.model_validate({
        "event_id": event_id, "transaction_id": f"tx-{event_id}",
        "occurred_at": now, "ingested_at": now, "source_account_ref": "src",
        "destination_account_ref": "dst", "source_bank_id": HOME_BANK_ID,
        "destination_bank_id": HOME_BANK_ID, "amount": 100, "currency": "VND",
        "direction": "INTERNAL", "data_visibility": "FULL_INTERNAL",
    })


def queued(): return DetectionDecision(DecisionKind.QUEUED, 0.7, "m1")


class Workflow:
    def __init__(self, error=None, final_state=None):
        self.calls = []
        self.error = error
        self.final_state = final_state if final_state is not None else {
            "phase": "complete",
            "report": {
                "overall_risk_level": "HIGH",
                "risk_rationale": "layered transfers",
            },
            "agent_outputs": {"tx": {"status": "ok"}},
            "errors": [],
        }

    def invoke(self, state, config):
        self.calls.append((state, config))
        if self.error:
            raise self.error
        return self.final_state


def test_manual_runner_drains_candidate_and_marks_complete(tmp_path: Path) -> None:
    repository = DetectionRepository(tmp_path / "q.db")
    candidate_id = repository.enqueue_candidate(event(), queued())
    workflow = Workflow()
    summary = InvestigationQueueRunner(repository, lambda: workflow).drain(RunTrigger.MANUAL)
    assert summary.completed == 1 and summary.failed == 0
    assert workflow.calls[0][1]["configurable"]["thread_id"].startswith("AML-")
    assert repository.claim_next(RunTrigger.MANUAL) is None
    stored = repository.get_candidate(candidate_id)
    assert stored is not None
    assert stored.status.value == "COMPLETED"
    assert stored.result is not None
    assert stored.result["overall_risk_level"] == "HIGH"
    assert stored.result["agent_statuses"] == {"tx": "ok"}
    events = InvestigationEventRepository(repository.db_path).list_after(candidate_id)
    assert events[-1].event_type is InvestigationEventType.INVESTIGATION_COMPLETED
    assert events[-1].payload["result"]["overall_risk_level"] == "HIGH"


def test_failure_is_recorded_without_immediate_retry_storm(tmp_path: Path) -> None:
    repository = DetectionRepository(tmp_path / "q.db", max_attempts=2)
    candidate_id = repository.enqueue_candidate(event(), queued())
    workflow = Workflow(RuntimeError("LLM token must not be logged"))
    summary = InvestigationQueueRunner(repository, lambda: workflow).drain(RunTrigger.MANUAL)
    assert summary.failed == 1
    assert len(workflow.calls) == 1
    stored = repository.get_candidate(candidate_id)
    assert stored is not None and stored.status.value == "FAILED"
    events = InvestigationEventRepository(repository.db_path).list_after(candidate_id)
    assert events[-1].event_type is InvestigationEventType.INVESTIGATION_FAILED
    assert events[-1].payload == {"error_type": "RuntimeError"}


def test_manual_refuses_before_workflow_creation_in_auto_mode(tmp_path: Path) -> None:
    repository = DetectionRepository(tmp_path / "q.db")
    repository.enqueue_candidate(event(), queued())
    repository.set_mode(RunMode.AUTO)
    created = []
    with pytest.raises(ModeMismatchError):
        InvestigationQueueRunner(repository, lambda: created.append(1)).drain(
            RunTrigger.MANUAL
        )
    assert created == []


def test_auto_is_noop_when_manual_mode_is_active(tmp_path: Path) -> None:
    repository = DetectionRepository(tmp_path / "q.db")
    repository.enqueue_candidate(event(), queued())
    summary = InvestigationQueueRunner(repository, lambda: Workflow()).drain(RunTrigger.AUTO)
    assert summary.completed == summary.failed == 0
