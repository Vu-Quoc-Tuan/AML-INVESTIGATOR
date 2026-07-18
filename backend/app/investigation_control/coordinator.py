"""Background coordination without duplicating candidate-runner behavior."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.detection.runner import InvestigationQueueRunner
from app.investigation_orchestrator import build_workflow

from .contracts import InvestigationRun
from .repository import InvestigationControlRepository

logger = logging.getLogger(__name__)

WorkflowFactory = Callable[[str | None], Any]
RunnerFactory = Callable[[Any, Callable[[], Any]], Any]


class ProgressTrackingRepository:
    """Proxy candidate writes and update persisted run counters afterward."""

    def __init__(
        self,
        candidate_repository: Any,
        control_repository: InvestigationControlRepository,
        run_id: str,
    ) -> None:
        self._candidate_repository = candidate_repository
        self._control_repository = control_repository
        self._run_id = run_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._candidate_repository, name)

    def mark_completed(
        self, candidate_id: str, case_id: str, **kwargs: Any
    ) -> None:
        self._candidate_repository.mark_completed(candidate_id, case_id, **kwargs)
        self._control_repository.increment_progress(self._run_id, completed=1)

    def mark_failed(self, candidate_id: str, error: str, **kwargs: Any) -> None:
        self._candidate_repository.mark_failed(candidate_id, error, **kwargs)
        self._control_repository.increment_progress(self._run_id, failed=1)


def _build_workflow(soft_prompt: str | None) -> Any:
    return build_workflow(soft_prompt=soft_prompt)


def _build_runner(repository: Any, workflow_factory: Callable[[], Any]) -> Any:
    return InvestigationQueueRunner(repository, workflow_factory)


class InvestigationRunCoordinator:
    def __init__(
        self,
        control_repository: InvestigationControlRepository,
        candidate_repository: Any,
        *,
        workflow_factory: WorkflowFactory = _build_workflow,
        runner_factory: RunnerFactory = _build_runner,
    ) -> None:
        self.control_repository = control_repository
        self.candidate_repository = candidate_repository
        self.workflow_factory = workflow_factory
        self.runner_factory = runner_factory

    def execute(self, run_id: str) -> InvestigationRun:
        pending = self.control_repository.get_run(run_id)
        if pending is None:
            raise KeyError("run not found")

        running = self.control_repository.start_run(run_id)
        try:
            workflow = self.workflow_factory(running.soft_prompt_snapshot)
            proxy = ProgressTrackingRepository(
                self.candidate_repository,
                self.control_repository,
                run_id,
            )
            runner = self.runner_factory(proxy, lambda: workflow)
            runner.drain(running.trigger)
        except Exception as exc:
            error_type = type(exc).__name__
            logger.error(
                "background investigation run failed run_id=%s error_type=%s",
                run_id,
                error_type,
            )
            return self.control_repository.fail_run(run_id, error_type)
        return self.control_repository.complete_run(run_id)

