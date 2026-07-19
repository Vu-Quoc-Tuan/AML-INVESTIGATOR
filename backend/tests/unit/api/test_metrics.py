from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.detection.contracts import DecisionKind, DetectionDecision
from app.detection.repository import DetectionRepository
from app.main import create_app
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


def _event(event_id: str, when: datetime) -> TransactionEventV1:
    return TransactionEventV1.model_validate(
        {
            "event_id": event_id,
            "transaction_id": f"tx-{event_id}",
            "occurred_at": when,
            "ingested_at": when,
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


@pytest.mark.anyio
async def test_flow_trends_from_detection_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "metrics.db"
    monkeypatch.setenv("DETECTION_DB_PATH", str(db))
    repo = DetectionRepository(db)
    day0 = datetime(2026, 7, 17, 12, tzinfo=UTC)
    day1 = datetime(2026, 7, 18, 12, tzinfo=UTC)
    # Patch created_at by direct SQL after enqueue for deterministic days.
    repo.enqueue_candidate(
        _event("q1", day1), DetectionDecision(DecisionKind.QUEUED, 0.7, "m1")
    )
    repo.enqueue_candidate(
        _event("q2", day1), DetectionDecision(DecisionKind.QUEUED, 0.8, "m1")
    )
    repo.record_blocked(
        _event("b1", day1), DetectionDecision(DecisionKind.BLOCKED, 0.99, "m1")
    )
    with repo._connect() as connection:
        connection.execute(
            "UPDATE investigation_candidates SET created_at=? WHERE event_id='q1'",
            ((day0).isoformat(),),
        )
        connection.execute(
            "UPDATE investigation_candidates SET created_at=? WHERE event_id='q2'",
            ((day1).isoformat(),),
        )
        connection.execute(
            "UPDATE blocked_transactions SET created_at=? WHERE event_id='b1'",
            ((day1).isoformat(),),
        )
        connection.commit()

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/metrics/flow-trends?days=2")
    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 2
    # Endpoint uses "now"; for stable assert use repository method directly.
    points = repo.flow_trends(days=2, now=day1)
    assert len(points) == 2
    assert points[0]["date"] == "2026-07-17"
    assert points[0]["queued"] == 1
    assert points[0]["volume"] == 1
    assert points[0]["flagged"] == 1
    assert points[1]["date"] == "2026-07-18"
    assert points[1]["queued"] == 1
    assert points[1]["blocked"] == 1
    assert points[1]["volume"] == 2
    assert points[1]["flagged"] == 1
