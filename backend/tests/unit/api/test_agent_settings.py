from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.detection.repository import DetectionRepository
from app.investigation_control.repository import InvestigationControlRepository
from app.main import create_app


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_KEY", "k0")
    monkeypatch.setenv("BASE_URL", "https://a.example/v1")
    monkeypatch.setenv("MODEL_NAME", "mistral-large")
    monkeypatch.setenv("API_KEY_1", "k1")
    monkeypatch.setenv("API_URL_1", "http://b.example/v1")
    monkeypatch.setenv("MODEL_NAME_1", "sun_llm/gemma-4-12b")
    monkeypatch.setenv("DETECTION_DB_PATH", str(tmp_path / "api.db"))
    db = tmp_path / "api.db"
    DetectionRepository(db)
    InvestigationControlRepository(db)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_get_and_put_per_agent_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)

    loaded = await client.get("/api/v1/agent-settings")
    assert loaded.status_code == 200
    body = loaded.json()
    assert len(body["agents"]) == 6
    assert {a["id"] for a in body["agents"]} >= {
        "planner",
        "transaction",
        "report",
    }

    saved = await client.put(
        "/api/v1/agent-settings",
        json={
            "agents": [
                {
                    "id": "planner",
                    "model_id": "mistral-large",
                    "soft_prompt": " Plan carefully. ",
                },
                {
                    "id": "transaction",
                    "model_id": "sun_llm/gemma-4-12b",
                    "soft_prompt": "Trace hops.",
                },
            ]
        },
    )
    assert saved.status_code == 200
    by_id = {item["id"]: item for item in saved.json()["agents"]}
    assert by_id["planner"]["model_id"] == "mistral-large"
    assert by_id["planner"]["soft_prompt"] == "Plan carefully."
    assert by_id["transaction"]["model_id"] == "sun_llm/gemma-4-12b"
    assert by_id["kyc"]["model_id"] is None

    again = await client.get("/api/v1/agent-settings")
    assert again.json()["agents"][0]["soft_prompt"] == "Plan carefully."
