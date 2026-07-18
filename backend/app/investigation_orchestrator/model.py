"""LLM configuration loaded from the backend environment file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class ModelConfigurationError(RuntimeError):
    """Raised when required model configuration is unavailable or invalid."""


class ModelSettings(BaseSettings):
    """Settings for the project's OpenAI-compatible model endpoint."""

    api_key: SecretStr = Field(min_length=1, validation_alias="API_KEY")
    base_url: str = Field(min_length=1, validation_alias="BASE_URL")
    model_name: str = Field(
        default="glm-5.2-free", min_length=1, validation_alias="MODEL_NAME"
    )
    temperature: float = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=60, gt=0)
    max_retries: int = Field(default=2, ge=0)

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
        case_sensitive=True,
    )


@lru_cache(maxsize=1)
def get_model_settings() -> ModelSettings:
    """Load model settings without exposing secret values in errors."""

    try:
        return ModelSettings()
    except ValidationError as exc:
        missing = sorted(
            str(error["loc"][0]).upper()
            for error in exc.errors()
            if error.get("type") == "missing"
        )
        details = f" Missing: {', '.join(missing)}." if missing else ""
        raise ModelConfigurationError(
            f"Invalid LLM configuration in backend/.env.{details}"
        ) from None


def build_chat_model(settings: ModelSettings | None = None) -> ChatOpenAI:
    """Build one unbound chat model shared by the workflow's agents."""

    config = settings or get_model_settings()
    return ChatOpenAI(
        model=config.model_name,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )
