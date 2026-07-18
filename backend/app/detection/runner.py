"""Deferred execution of queued multi-agent investigations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .agent_adapter import case_id_for, to_investigation_input
from .contracts import RunTrigger

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunSummary:
    completed: int = 0
    failed: int = 0


def _default_workflow_factory() -> Any:
    from app.investigation_orchestrator import build_workflow

    return build_workflow()


class InvestigationQueueRunner:
    def __init__(
        self,
        repository: Any,
        workflow_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.repository = repository
        self.workflow_factory = workflow_factory or _default_workflow_factory

    def drain(self, trigger: RunTrigger) -> RunSummary:
        completed = failed = 0
        workflow = None
        while candidate := self.repository.claim_next(trigger):
            case_id = case_id_for(candidate)
            try:
                workflow = workflow or self.workflow_factory()
                workflow.invoke(
                    to_investigation_input(candidate),
                    config={"configurable": {"thread_id": case_id}},
                )
            except Exception as exc:
                failed += 1
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
            else:
                completed += 1
                self.repository.mark_completed(candidate.candidate_id, case_id)
                logger.info(
                    "investigation completed candidate_id=%s case_id=%s",
                    candidate.candidate_id,
                    case_id,
                )
        return RunSummary(completed=completed, failed=failed)
