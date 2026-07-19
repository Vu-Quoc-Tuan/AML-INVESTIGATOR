"""Deferred execution of queued multi-agent investigations."""

from __future__ import annotations

import logging
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.investigation_events import (
    ExecutionEventRecorder,
    InvestigationEventRepository,
    InvestigationEventType,
)

from .agent_adapter import case_id_for, summarize_result, to_investigation_input
from .contracts import RunTrigger

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunSummary:
    completed: int = 0
    failed: int = 0


def _default_workflow_factory(
    event_repository: InvestigationEventRepository | None = None,
) -> Any:
    from app.investigation_orchestrator import build_workflow

    return build_workflow(event_repository=event_repository)


class InvestigationQueueRunner:
    def __init__(
        self,
        repository: Any,
        workflow_factory: Callable[..., Any] | None = None,
        event_repository: InvestigationEventRepository | None = None,
    ) -> None:
        self.repository = repository
        self.workflow_factory = workflow_factory or _default_workflow_factory
        db_path = getattr(repository, "db_path", None)
        self.event_repository = event_repository or (
            InvestigationEventRepository(db_path) if db_path is not None else None
        )

    def _create_workflow(self) -> Any:
        parameters = inspect.signature(self.workflow_factory).parameters
        if "event_repository" in parameters:
            return self.workflow_factory(event_repository=self.event_repository)
        return self.workflow_factory()

    def drain(self, trigger: RunTrigger) -> RunSummary:
        completed = failed = 0
        workflow = None
        while candidate := self.repository.claim_next(trigger):
            ok = self._run_claimed(candidate, workflow_holder := {"wf": workflow})
            workflow = workflow_holder["wf"]
            if ok:
                completed += 1
            else:
                failed += 1
        return RunSummary(completed=completed, failed=failed)

    def run_one(self, candidate_id: str, trigger: RunTrigger) -> bool:
        """Claim and investigate a single ticket. Returns True on success."""

        candidate = self.repository.claim_candidate(candidate_id, trigger)
        return self.run_claimed(candidate)

    def run_claimed(self, candidate: Any) -> bool:
        """Investigate a candidate already claimed by the API or queue runner."""

        return self._run_claimed(candidate, {"wf": None})

    def _run_claimed(self, candidate: Any, workflow_holder: dict[str, Any]) -> bool:
        case_id = case_id_for(candidate)
        try:
            workflow = workflow_holder.get("wf") or self._create_workflow()
            workflow_holder["wf"] = workflow
            final_state = workflow.invoke(
                to_investigation_input(candidate),
                config={"configurable": {"thread_id": case_id}},
            )
        except Exception as exc:
            self.repository.mark_failed(
                candidate.candidate_id,
                f"{type(exc).__name__}: investigation execution failed",
            )
            logger.error(
                "investigation failed candidate_id=%s event_id=%s error_type=%s",
                candidate.candidate_id,
                candidate.event_id,
                type(exc).__name__,
            )
            if self.event_repository is not None:
                ExecutionEventRecorder(
                    self.event_repository,
                    ticket_id=candidate.candidate_id,
                    case_id=case_id,
                ).append(
                    InvestigationEventType.INVESTIGATION_FAILED,
                    status="FAILED",
                    summary="Investigation failed",
                    payload={"error_type": type(exc).__name__},
                )
            return False
        result = summarize_result(final_state, case_id)
        self.repository.mark_completed(
            candidate.candidate_id,
            case_id,
            result=result,
        )
        if self.event_repository is not None:
            ExecutionEventRecorder(
                self.event_repository,
                ticket_id=candidate.candidate_id,
                case_id=case_id,
            ).append(
                InvestigationEventType.INVESTIGATION_COMPLETED,
                status="COMPLETED",
                summary="Investigation completed",
                payload={"result": result},
            )
        logger.info(
            "investigation completed candidate_id=%s case_id=%s",
            candidate.candidate_id,
            case_id,
        )
        return True
