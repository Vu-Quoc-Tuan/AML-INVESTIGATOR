from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.detection.contracts import (
    DecisionKind,
    DetectionDecision,
    RunMode,
    RunTrigger,
)
from app.detection.repository import DetectionRepository
from app.investigation_control.contracts import ControlConfiguration, RunStatus
from app.investigation_control.repository import (
    ControlConflictError,
    InvestigationControlRepository,
)
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


NOW = datetime(2026, 7, 19, 1, 0, tzinfo=UTC)


def _repositories(tmp_path: Path):
    db_path = tmp_path / "control.db"
    candidate_repository = DetectionRepository(db_path)
    return candidate_repository, InvestigationControlRepository(db_path)


def _event(event_id: str) -> TransactionEventV1:
    return TransactionEventV1.model_validate(
        {
            "event_id": event_id,
            "transaction_id": f"tx-{event_id}",
            "occurred_at": NOW,
            "ingested_at": NOW,
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


def _queued() -> DetectionDecision:
    return DetectionDecision(DecisionKind.QUEUED, 0.8, "model-1")


def test_configuration_normalizes_blank_and_rejects_oversized_prompt() -> None:
    assert ControlConfiguration(soft_prompt="   ", updated_at=NOW).soft_prompt is None
    with pytest.raises(ValidationError):
        ControlConfiguration(soft_prompt="x" * 4_001, updated_at=NOW)


def test_configuration_trim_save_and_reset(tmp_path: Path) -> None:
    _, repository = _repositories(tmp_path)
    assert repository.get_configuration().soft_prompt is None

    saved = repository.set_soft_prompt("  Focus on velocity.  ", now=NOW)
    assert saved.soft_prompt == "Focus on velocity."
    assert saved.updated_at == NOW
    assert repository.get_configuration() == saved

    reset = repository.set_soft_prompt("   ", now=NOW)
    assert reset.soft_prompt is None


def test_summary_counts_candidates_by_status(tmp_path: Path) -> None:
    candidates, repository = _repositories(tmp_path)
    candidates.enqueue_candidate(_event("pending"), _queued())
    candidates.enqueue_candidate(_event("processing"), _queued())
    claimed = candidates.claim_next(RunTrigger.MANUAL, now=NOW)
    assert claimed is not None

    summary = repository.get_summary()

    assert summary.mode is RunMode.MANUAL
    assert summary.queue.pending == 1
    assert summary.queue.processing == 1
    assert summary.queue.completed == 0
    assert summary.queue.failed == 0
    assert summary.active_run is None


def test_create_run_snapshots_prompt_and_enforces_mode(tmp_path: Path) -> None:
    _, repository = _repositories(tmp_path)
    repository.set_soft_prompt("Current guidance", now=NOW)

    run = repository.create_run(RunTrigger.MANUAL, now=NOW)

    assert run.status is RunStatus.PENDING
    assert run.soft_prompt_snapshot == "Current guidance"
    with pytest.raises(ControlConflictError, match="active run"):
        repository.create_run(RunTrigger.MANUAL, now=NOW)

    repository.fail_run(run.run_id, "Stopped", now=NOW)
    repository.set_mode(RunMode.AUTO)
    with pytest.raises(ControlConflictError, match="mode"):
        repository.create_run(RunTrigger.MANUAL, now=NOW)


def test_concurrent_create_allows_exactly_one_active_run(tmp_path: Path) -> None:
    _, repository = _repositories(tmp_path)

    def create(_index: int):
        try:
            return repository.create_run(RunTrigger.MANUAL, now=NOW)
        except ControlConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, range(2)))

    assert sum(item is not None for item in results) == 1


def test_mode_cannot_change_while_run_is_active(tmp_path: Path) -> None:
    _, repository = _repositories(tmp_path)
    repository.create_run(RunTrigger.MANUAL, now=NOW)
    with pytest.raises(ControlConflictError, match="active run"):
        repository.set_mode(RunMode.AUTO)


def test_run_lifecycle_progress_history_and_safe_failure(tmp_path: Path) -> None:
    _, repository = _repositories(tmp_path)
    first = repository.create_run(RunTrigger.MANUAL, now=NOW)
    running = repository.start_run(first.run_id, now=NOW)
    assert running.status is RunStatus.RUNNING
    repository.increment_progress(first.run_id, completed=2, failed=1)
    completed = repository.complete_run(first.run_id, now=NOW)
    assert completed.status is RunStatus.COMPLETED_WITH_ERRORS
    assert completed.completed_count == 2
    assert completed.failed_count == 1

    second = repository.create_run(RunTrigger.MANUAL, now=NOW)
    failed = repository.fail_run(
        second.run_id, "RuntimeError: secret provider text", now=NOW
    )
    assert failed.status is RunStatus.FAILED
    assert failed.error == "RuntimeError"
    assert [item.run_id for item in repository.list_runs()] == [
        second.run_id,
        first.run_id,
    ]
    assert repository.get_run("missing") is None


def test_startup_reconciliation_interrupts_pending_and_running(tmp_path: Path) -> None:
    _, repository = _repositories(tmp_path)
    pending = repository.create_run(RunTrigger.MANUAL, now=NOW)
    assert repository.interrupt_active_runs(now=NOW) == 1
    assert repository.get_run(pending.run_id).status is RunStatus.INTERRUPTED

    running = repository.create_run(RunTrigger.MANUAL, now=NOW)
    repository.start_run(running.run_id, now=NOW)
    assert repository.interrupt_active_runs(now=NOW) == 1
    assert repository.get_run(running.run_id).status is RunStatus.INTERRUPTED


def test_prompt_is_snapshotted_per_run(tmp_path: Path) -> None:
    _, repository = _repositories(tmp_path)
    repository.set_soft_prompt("first", now=NOW)
    first = repository.create_run(RunTrigger.MANUAL, now=NOW)
    repository.fail_run(first.run_id, "Stopped", now=NOW)
    repository.set_soft_prompt("second", now=NOW)
    second = repository.create_run(RunTrigger.MANUAL, now=NOW)

    assert repository.get_run(first.run_id).soft_prompt_snapshot == "first"
    assert second.soft_prompt_snapshot == "second"
