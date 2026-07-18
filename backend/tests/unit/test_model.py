"""Secret-safe model settings tests."""

from app.investigation_orchestrator.model import ModelSettings


def test_settings_accept_documented_environment_names_and_default_model() -> None:
    settings = ModelSettings(
        API_KEY="test-only-secret",
        BASE_URL="https://example.invalid/v1",
        _env_file=None,
    )

    assert settings.model_name == "glm-5.2-free"
    assert settings.api_key.get_secret_value() == "test-only-secret"
    assert "test-only-secret" not in repr(settings)
