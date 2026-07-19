from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.api.routes import investigation_control
from app.detection.contracts import RunMode, RunTrigger
from app.detection.repository import DetectionRepository
from app.investigation_control.repository import InvestigationControlRepository
from app.main import create_app


NOW = datetime(2026, 7, 19, 1, 0, tzinfo=UTC)


class FakeCoordinator:
    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute(self, run_id: str) -> None:
        self.executed.append(run_id)


def _client(tmp_path: Path):
    db_path = tmp_path / "api.db"
    candidates = DetectionRepository(db_path)
    repository = InvestigationControlRepository(db_path)
    coordinator = FakeCoordinator()
    app = create_app()

    async def control_repository_override():
        return repository

    async def candidate_repository_override():
        return candidates

    async def coordinator_override():
        return coordinator

    app.dependency_overrides[investigation_control.get_control_repository] = (
        control_repository_override
    )
    app.dependency_overrides[investigation_control.get_candidate_repository] = (
        candidate_repository_override
    )
    app.dependency_overrides[investigation_control.get_run_coordinator] = (
        coordinator_override
    )
    transport = httpx.ASGITransport(app=app)
    return (
        httpx.AsyncClient(transport=transport, base_url="http://test"),
        repository,
        coordinator,
        candidates,
    )


@pytest.mark.anyio
async def test_create_run_refuses_empty_queue_for_manual_only(
    tmp_path: Path,
) -> None:
    client, repository, coordinator, _ = _client(tmp_path)
    response = await client.post(
        "/api/v1/investigation-control/runs", json={"trigger": "MANUAL"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EMPTY_QUEUE"
    assert coordinator.executed == []

    repository.set_mode(RunMode.AUTO)
    auto = await client.post(
        "/api/v1/investigation-control/runs", json={"trigger": "AUTO"}
    )
    assert auto.status_code == 202
    assert coordinator.executed == [auto.json()["run_id"]]


@pytest.mark.anyio
async def test_summary_mode_and_configuration_endpoints(tmp_path: Path) -> None:
    client, _, _, _ = _client(tmp_path)

    summary = await client.get("/api/v1/investigation-control")
    assert summary.status_code == 200
    assert summary.json()["mode"] == "MANUAL"
    assert summary.json()["queue"] == {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "approved": 0,
        "rejected": 0,
        "false_positive": 0,
    }

    mode = await client.put(
        "/api/v1/investigation-control/mode", json={"mode": "AUTO"}
    )
    assert mode.status_code == 200
    assert mode.json() == {"mode": "AUTO"}

    saved = await client.put(
        "/api/v1/investigation-control/configuration",
        json={"soft_prompt": "  Focus on velocity.  "},
    )
    assert saved.status_code == 200
    assert saved.json()["soft_prompt"] == "Focus on velocity."
    loaded = await client.get("/api/v1/investigation-control/configuration")
    assert loaded.json()["soft_prompt"] == "Focus on velocity."
    reset = await client.put(
        "/api/v1/investigation-control/configuration", json={"soft_prompt": ""}
    )
    assert reset.json()["soft_prompt"] is None


@pytest.mark.anyio
async def test_create_returns_202_and_schedules_background_run(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from app.detection.contracts import DecisionKind, DetectionDecision
    from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1

    client, _, coordinator, candidates = _client(tmp_path)
    now = datetime(2026, 7, 19, tzinfo=UTC)
    candidates.enqueue_candidate(
        TransactionEventV1.model_validate(
            {
                "event_id": "e-run",
                "transaction_id": "t-run",
                "occurred_at": now,
                "ingested_at": now,
                "source_account_ref": "s",
                "destination_account_ref": "d",
                "source_bank_id": HOME_BANK_ID,
                "destination_bank_id": HOME_BANK_ID,
                "amount": 1,
                "currency": "VND",
                "direction": "INTERNAL",
                "data_visibility": "FULL_INTERNAL",
            }
        ),
        DetectionDecision(DecisionKind.QUEUED, 0.7, "m"),
    )

    response = await client.post(
        "/api/v1/investigation-control/runs", json={"trigger": "MANUAL"}
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "PENDING"
    assert payload["trigger"] == "MANUAL"
    assert coordinator.executed == [payload["run_id"]]


@pytest.mark.anyio
async def test_run_detail_history_and_missing(tmp_path: Path) -> None:
    client, repository, _, _ = _client(tmp_path)
    run = repository.create_run(RunTrigger.MANUAL, now=NOW)

    detail = await client.get(f"/api/v1/investigation-control/runs/{run.run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run.run_id
    assert "soft_prompt_snapshot" not in detail.json()

    history = await client.get("/api/v1/investigation-control/runs?limit=10")
    assert history.status_code == 200
    assert history.json()["items"][0]["run_id"] == run.run_id
    assert (
        await client.get("/api/v1/investigation-control/runs/missing")
    ).status_code == 404


@pytest.mark.anyio
async def test_conflicts_are_stable_and_do_not_create_runs(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from app.detection.contracts import DecisionKind, DetectionDecision
    from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1

    client, repository, _, candidates = _client(tmp_path)
    repository.set_mode(RunMode.AUTO)

    mismatch = await client.post(
        "/api/v1/investigation-control/runs", json={"trigger": "MANUAL"}
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "CONTROL_CONFLICT"
    assert repository.list_runs() == []

    repository.set_mode(RunMode.MANUAL)
    now = datetime(2026, 7, 19, tzinfo=UTC)
    candidates.enqueue_candidate(
        TransactionEventV1.model_validate(
            {
                "event_id": "e-dup",
                "transaction_id": "t-dup",
                "occurred_at": now,
                "ingested_at": now,
                "source_account_ref": "s",
                "destination_account_ref": "d",
                "source_bank_id": HOME_BANK_ID,
                "destination_bank_id": HOME_BANK_ID,
                "amount": 1,
                "currency": "VND",
                "direction": "INTERNAL",
                "data_visibility": "FULL_INTERNAL",
            }
        ),
        DetectionDecision(DecisionKind.QUEUED, 0.7, "m"),
    )
    repository.create_run(RunTrigger.MANUAL, now=NOW)
    duplicate = await client.post(
        "/api/v1/investigation-control/runs", json={"trigger": "MANUAL"}
    )
    assert duplicate.status_code == 409
    mode_change = await client.put(
        "/api/v1/investigation-control/mode", json={"mode": "AUTO"}
    )
    assert mode_change.status_code == 409


@pytest.mark.anyio
async def test_request_validation_rejects_unknown_fields_and_large_prompt(
    tmp_path: Path,
) -> None:
    client, _, _, _ = _client(tmp_path)
    assert (
        await client.post(
            "/api/v1/investigation-control/runs",
            json={"trigger": "MANUAL", "unexpected": True},
        )
    ).status_code == 422
    assert (
        await client.put(
            "/api/v1/investigation-control/configuration",
            json={"soft_prompt": "x" * 4_001},
        )
    ).status_code == 422
