from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.api.routes import investigation_control
from app.detection.contracts import (
    CandidateStatus,
    DecisionKind,
    DetectionDecision,
)
from app.detection.repository import DetectionRepository
from app.investigation_control.contracts import RunStatus
from app.investigation_control.coordinator import InvestigationRunCoordinator
from app.investigation_control.repository import InvestigationControlRepository
from app.main import create_app
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


NOW = datetime(2026, 7, 19, tzinfo=UTC)


def _event(index: int) -> TransactionEventV1:
    return TransactionEventV1.model_validate(
        {
            "event_id": f"evt-control-{index}",
            "transaction_id": f"tx-control-{index}",
            "occurred_at": NOW,
            "ingested_at": NOW,
            "source_account_ref": f"src-{index}",
            "destination_account_ref": f"dst-{index}",
            "source_bank_id": HOME_BANK_ID,
            "destination_bank_id": HOME_BANK_ID,
            "amount": 100_000 + index,
            "currency": "VND",
            "direction": "INTERNAL",
            "data_visibility": "FULL_INTERNAL",
        }
    )


class FakeWorkflow:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    def invoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("provider detail must not escape")
        return {
            **state,
            "phase": "complete",
            "report": {"overall_risk_level": "MEDIUM"},
        }


def _queue(repository: DetectionRepository, count: int = 2) -> list[str]:
    return [
        repository.enqueue_candidate(
            _event(index),
            DetectionDecision(DecisionKind.QUEUED, 0.8, "integration-model"),
        )
        for index in range(count)
    ]


def _app(
    candidate_repository: DetectionRepository,
    control_repository: InvestigationControlRepository,
    workflow: FakeWorkflow,
):
    coordinator = InvestigationRunCoordinator(
        control_repository,
        candidate_repository,
        workflow_factory=lambda agent_settings: workflow,
    )

    class AsyncCoordinator:
        async def execute(self, run_id: str) -> None:
            coordinator.execute(run_id)

    async def control_override():
        return control_repository

    async def coordinator_override():
        return AsyncCoordinator()

    async def candidate_override():
        return candidate_repository

    app = create_app()
    app.dependency_overrides[investigation_control.get_control_repository] = (
        control_override
    )
    app.dependency_overrides[investigation_control.get_candidate_repository] = (
        candidate_override
    )
    app.dependency_overrides[investigation_control.get_run_coordinator] = (
        coordinator_override
    )
    return app


@pytest.mark.anyio
async def test_api_run_drains_real_queue_and_keeps_prompt_snapshot(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pipeline.db"
    candidates = DetectionRepository(db_path)
    control = InvestigationControlRepository(db_path)
    candidate_ids = _queue(candidates)
    control.set_soft_prompt("Focus on velocity", now=NOW)
    app = _app(candidates, control, FakeWorkflow())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/investigation-control/runs", json={"trigger": "MANUAL"}
        )

    assert response.status_code == 202
    run = control.get_run(response.json()["run_id"])
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.completed_count == 2
    assert run.failed_count == 0
    assert run.soft_prompt_snapshot == "Focus on velocity"
    assert all(
        candidates.get_candidate(candidate_id).status is CandidateStatus.COMPLETED
        for candidate_id in candidate_ids
    )


@pytest.mark.anyio
async def test_candidate_failure_completes_run_without_provider_message(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "partial.db"
    candidates = DetectionRepository(db_path)
    control = InvestigationControlRepository(db_path)
    _queue(candidates)
    app = _app(candidates, control, FakeWorkflow(fail_on_call=1))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/investigation-control/runs", json={"trigger": "MANUAL"}
        )

    run = control.get_run(response.json()["run_id"])
    assert run is not None
    assert run.status is RunStatus.COMPLETED_WITH_ERRORS
    assert run.completed_count == 1
    assert run.failed_count == 1
    assert "provider detail" not in (run.error or "")
