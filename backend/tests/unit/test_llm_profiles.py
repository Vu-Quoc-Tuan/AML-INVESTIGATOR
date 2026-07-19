from __future__ import annotations

from pathlib import Path

import pytest

from app.investigation_control.repository import InvestigationControlRepository
from app.investigation_orchestrator import model as model_mod


def test_discover_primary_and_numbered_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "k0")
    monkeypatch.setenv("BASE_URL", "https://a.example/v1")
    monkeypatch.setenv("MODEL_NAME", "mistral-large")
    monkeypatch.setenv("API_KEY_1", "k1")
    monkeypatch.setenv("API_URL_1", "http://b.example/v1")
    monkeypatch.setenv("MODEL_NAME_1", "sun_llm/gemma-4-12b")

    profiles = model_mod.discover_llm_profiles()
    assert [p.id for p in profiles] == ["mistral-large", "sun_llm/gemma-4-12b"]
    assert profiles[1].base_url == "http://b.example/v1"
    assert "k1" not in profiles[1].public_dict().values()


def test_selected_profile_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "k0")
    monkeypatch.setenv("BASE_URL", "https://a.example/v1")
    monkeypatch.setenv("MODEL_NAME", "mistral-large")
    monkeypatch.setenv("API_KEY_1", "k1")
    monkeypatch.setenv("API_URL_1", "http://b.example/v1")
    monkeypatch.setenv("MODEL_NAME_1", "gemma-local")
    monkeypatch.setenv("DETECTION_DB_PATH", str(tmp_path / "q.db"))

    selected = model_mod.set_selected_profile_id("gemma-local")
    assert selected == "gemma-local"
    assert model_mod.get_selected_profile_id() == "gemma-local"
    assert model_mod.get_llm_profile().id == "mistral-large"
    assert model_mod.get_llm_profile("gemma-local").model_name == "gemma-local"


def test_unknown_profile_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "k0")
    monkeypatch.setenv("BASE_URL", "https://a.example/v1")
    monkeypatch.setenv("MODEL_NAME", "mistral-large")
    with pytest.raises(model_mod.ModelConfigurationError):
        model_mod.get_llm_profile("does-not-exist")
