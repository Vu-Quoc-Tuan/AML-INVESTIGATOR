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
    monkeypatch.setenv("API_URL_1", "http://b.example/openai/v1")
    monkeypatch.setenv("MODEL_NAME_1", "sun_llm/gemma-4-12b")
    monkeypatch.setenv("DETECTION_DB_PATH", str(tmp_path / "api.db"))

    db_path = tmp_path / "api.db"
    DetectionRepository(db_path)
    InvestigationControlRepository(db_path)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_list_and_select_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)

    listed = await client.get("/api/v1/models")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["model_name"] == "mistral-large"
    assert body["items"][1]["model_name"] == "sun_llm/gemma-4-12b"
    assert "api_key" not in body["items"][0]
    assert body["selected_id"] in {item["id"] for item in body["items"]}

    selected = await client.put(
        "/api/v1/models/selected",
        json={"id": "sun_llm/gemma-4-12b"},
    )
    assert selected.status_code == 200
    assert selected.json()["selected_id"] == "sun_llm/gemma-4-12b"

    again = await client.get("/api/v1/models")
    assert again.json()["selected_id"] == "sun_llm/gemma-4-12b"

    missing = await client.put("/api/v1/models/selected", json={"id": "nope"})
    assert missing.status_code == 404
