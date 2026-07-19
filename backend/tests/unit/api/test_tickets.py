from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.detection.contracts import DecisionKind, DetectionDecision, RunTrigger
from app.detection.repository import DetectionRepository
from app.main import create_app
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


def _event(event_id: str = "evt-1") -> TransactionEventV1:
    now = datetime(2026, 7, 19, tzinfo=UTC)
    return TransactionEventV1.model_validate({
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
    })


def test_tickets_list_and_get(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "queue.db"
    monkeypatch.setenv("DETECTION_DB_PATH", str(db_path))
    repository = DetectionRepository(db_path)
    ticket_id = repository.enqueue_candidate(
        _event(), DetectionDecision(DecisionKind.QUEUED, 0.8, "m1")
    )
    claimed = repository.claim_next(RunTrigger.MANUAL)
    assert claimed is not None
    repository.mark_completed(
        claimed.candidate_id,
        f"AML-{claimed.candidate_id}",
        result={"overall_risk_level": "MEDIUM", "phase": "complete"},
    )

    client = TestClient(create_app())
    listed = client.get("/api/v1/tickets")
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 1
    assert body["items"][0]["ticket_id"] == ticket_id
    assert body["items"][0]["status"] == "COMPLETED"
    assert body["items"][0]["overall_risk_level"] == "MEDIUM"

    detail = client.get(f"/api/v1/tickets/{ticket_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["transaction"]["transaction_id"] == "tx-evt-1"
    assert payload["result"]["phase"] == "complete"
    assert payload["detection"]["ml_confidence"] == 0.8

    missing = client.get("/api/v1/tickets/does-not-exist")
    assert missing.status_code == 404
