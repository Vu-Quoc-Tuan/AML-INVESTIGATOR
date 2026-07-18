from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.detection.contracts import RunTrigger
from app.detection.repository import DetectionRepository
from app.investigation_control.contracts import RunStatus
from app.investigation_control.coordinator import (
    InvestigationRunCoordinator,
    ProgressTrackingRepository,
)
from app.investigation_control.repository import InvestigationControlRepository


NOW = datetime(2026, 7, 19, 1, 0, tzinfo=UTC)


class CandidateRepository:
    def __init__(self) -> None:
        self.completed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.failed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.fail_delegate = False

    def mark_completed(self, *args: Any, **kwargs: Any) -> None:
        if self.fail_delegate:
            raise RuntimeError("delegate failed")
        self.completed.append((args, kwargs))

    def mark_failed(self, *args: Any, **kwargs: Any) -> None:
        if self.fail_delegate:
            raise RuntimeError("delegate failed")
        self.failed.append((args, kwargs))

    def passthrough(self) -> str:
        return "delegated"


def _control(tmp_path: Path) -> InvestigationControlRepository:
    db_path = tmp_path / "control.db"
    DetectionRepository(db_path)
    return InvestigationControlRepository(db_path)


def test_progress_proxy_counts_only_successful_delegate_calls(tmp_path: Path) -> None:
    control = _control(tmp_path)
    run = control.create_run(RunTrigger.MANUAL, now=NOW)
    control.start_run(run.run_id, now=NOW)
    candidates = CandidateRepository()
    proxy = ProgressTrackingRepository(candidates, control, run.run_id)

    proxy.mark_completed("candidate-1", "case-1", result={"phase": "complete"})
    proxy.mark_failed("candidate-2", "RuntimeError", now=NOW)

    current = control.get_run(run.run_id)
    assert current.completed_count == 1
    assert current.failed_count == 1
    assert candidates.completed[0][1] == {"result": {"phase": "complete"}}
    assert candidates.failed[0][1] == {"now": NOW}
    assert proxy.passthrough() == "delegated"

    candidates.fail_delegate = True
    with pytest.raises(RuntimeError, match="delegate failed"):
        proxy.mark_completed("candidate-3", "case-3")
    assert control.get_run(run.run_id).completed_count == 1


class FakeRunner:
    def __init__(self, repository: Any, workflow_factory: Any, behavior: str) -> None:
        self.repository = repository
        self.workflow_factory = workflow_factory
        self.behavior = behavior

    def drain(self, trigger: RunTrigger) -> None:
        assert trigger is RunTrigger.MANUAL
        assert self.workflow_factory() == "workflow"
        if self.behavior == "complete":
            self.repository.mark_completed(
                "candidate-1", "case-1", result={"phase": "complete"}
            )
        elif self.behavior == "partial":
            self.repository.mark_completed("candidate-1", "case-1")
            self.repository.mark_failed("candidate-2", "RuntimeError")


def _coordinator(
    tmp_path: Path,
    *,
    behavior: str = "complete",
    workflow_error: Exception | None = None,
    captured_prompts: list[str | None] | None = None,
) -> tuple[InvestigationControlRepository, InvestigationRunCoordinator]:
    control = _control(tmp_path)
    candidates = CandidateRepository()

    def workflow_factory(soft_prompt: str | None) -> str:
        if captured_prompts is not None:
            captured_prompts.append(soft_prompt)
        if workflow_error:
            raise workflow_error
        return "workflow"

    def runner_factory(repository: Any, factory: Any) -> FakeRunner:
        return FakeRunner(repository, factory, behavior)

    return control, InvestigationRunCoordinator(
        control,
        candidates,
        workflow_factory=workflow_factory,
        runner_factory=runner_factory,
    )


def test_coordinator_completes_and_uses_prompt_snapshot(tmp_path: Path) -> None:
    captured: list[str | None] = []
    control, coordinator = _coordinator(tmp_path, captured_prompts=captured)
    control.set_soft_prompt("first", now=NOW)
    run = control.create_run(RunTrigger.MANUAL, now=NOW)
    control.set_soft_prompt("second", now=NOW)

    result = coordinator.execute(run.run_id)

    assert result.status is RunStatus.COMPLETED
    assert result.completed_count == 1
    assert captured == ["first"]


def test_coordinator_marks_completed_with_errors(tmp_path: Path) -> None:
    control, coordinator = _coordinator(tmp_path, behavior="partial")
    run = control.create_run(RunTrigger.MANUAL, now=NOW)

    result = coordinator.execute(run.run_id)

    assert result.status is RunStatus.COMPLETED_WITH_ERRORS
    assert result.completed_count == 1
    assert result.failed_count == 1


def test_workflow_construction_failure_is_redacted(tmp_path: Path) -> None:
    control, coordinator = _coordinator(
        tmp_path,
        workflow_error=RuntimeError("secret provider message"),
    )
    run = control.create_run(RunTrigger.MANUAL, now=NOW)

    result = coordinator.execute(run.run_id)

    assert result.status is RunStatus.FAILED
    assert result.error == "RuntimeError"


def test_unknown_run_fails_before_workflow_creation(tmp_path: Path) -> None:
    captured: list[str | None] = []
    _, coordinator = _coordinator(tmp_path, captured_prompts=captured)

    with pytest.raises(KeyError, match="run not found"):
        coordinator.execute("missing")
    assert captured == []
