"""LLM configuration: multi-endpoint profiles from backend/.env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class ModelConfigurationError(RuntimeError):
    """Raised when required model configuration is unavailable or invalid."""


class ModelSettings(BaseSettings):
    """Primary OpenAI-compatible endpoint (legacy single-profile settings)."""

    api_key: SecretStr = Field(min_length=1, validation_alias="API_KEY")
    base_url: str = Field(min_length=1, validation_alias="BASE_URL")
    model_name: str = Field(
        default="mistral-large", min_length=1, validation_alias="MODEL_NAME"
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


@dataclass(frozen=True)
class LlmProfile:
    """One selectable chat endpoint (secrets stay in-process only)."""

    id: str
    model_name: str
    base_url: str
    api_key: str
    temperature: float = 0.0
    timeout_seconds: float = 60.0
    max_retries: int = 2

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "model_name": self.model_name,
            "base_url": self.base_url,
        }


def _load_dotenv_file() -> None:
    """Load backend/.env into os.environ without overwriting existing values."""

    if not ENV_FILE.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ENV_FILE, override=False)


def discover_llm_profiles() -> tuple[LlmProfile, ...]:
    """
    Discover chat profiles from environment.

    Primary:
      API_KEY, BASE_URL, MODEL_NAME
    Additional (n = 1, 2, ...):
      API_KEY_n, MODEL_NAME_n, and API_URL_n or BASE_URL_n
    """

    _load_dotenv_file()
    profiles: list[LlmProfile] = []
    seen_ids: set[str] = set()

    def _add(index: int | None, api_key: str, base_url: str, model_name: str) -> None:
        key = api_key.strip()
        base = base_url.strip().rstrip("/")
        name = model_name.strip()
        if not key or not base or not name:
            return
        profile_id = name if name not in seen_ids else f"{index if index is not None else 0}:{name}"
        seen_ids.add(profile_id)
        profiles.append(
            LlmProfile(
                id=profile_id,
                model_name=name,
                base_url=base,
                api_key=key,
            )
        )

    primary_key = os.getenv("API_KEY", "")
    primary_base = os.getenv("BASE_URL", "")
    primary_name = os.getenv("MODEL_NAME", "")
    if primary_key and primary_base and primary_name:
        _add(0, primary_key, primary_base, primary_name)

    for index in range(1, 21):
        key = os.getenv(f"API_KEY_{index}", "")
        base = os.getenv(f"API_URL_{index}", "") or os.getenv(f"BASE_URL_{index}", "")
        name = os.getenv(f"MODEL_NAME_{index}", "")
        if key and base and name:
            _add(index, key, base, name)

    return tuple(profiles)



def get_llm_profile(profile_id: str | None = None) -> LlmProfile:
    """Resolve a profile by id, or the first discovered profile."""

    profiles = discover_llm_profiles()
    if not profiles:
        raise ModelConfigurationError(
            "No LLM profiles configured. Set API_KEY, BASE_URL, MODEL_NAME "
            "(and optionally API_KEY_1 / API_URL_1 / MODEL_NAME_1)."
        )
    if profile_id is None or profile_id == "":
        return profiles[0]
    for profile in profiles:
        if profile.id == profile_id:
            return profile
    raise ModelConfigurationError(f"Unknown LLM profile id: {profile_id}")


def get_selected_profile_id() -> str | None:
    """Read selected profile id from the detection SQLite settings, if any."""

    try:
        from app.detection.config import DetectionSettings
        from app.investigation_control.repository import InvestigationControlRepository
    except Exception:
        return None
    try:
        settings = DetectionSettings.from_env()
        repo = InvestigationControlRepository(settings.db_path)
        return repo.get_selected_llm_id()
    except Exception:
        return None


def set_selected_profile_id(profile_id: str) -> str:
    """Persist selected profile id after validating it exists."""

    profile = get_llm_profile(profile_id)
    from app.detection.config import DetectionSettings
    from app.investigation_control.repository import InvestigationControlRepository

    settings = DetectionSettings.from_env()
    repo = InvestigationControlRepository(settings.db_path)
    return repo.set_selected_llm_id(profile.id)


@lru_cache(maxsize=1)
def get_model_settings() -> ModelSettings:
    """Load primary model settings without exposing secret values in errors."""

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


def build_chat_model(
    settings: ModelSettings | None = None,
    *,
    profile_id: str | None = None,
) -> ChatOpenAI:
    """
    Build a chat model for agents.

    Resolution order when ``settings`` is omitted:
    1. explicit ``profile_id``
    2. selected id stored in SQLite (if any)
    3. first discovered env profile
    4. legacy ``ModelSettings`` primary env block
    """

    if settings is not None:
        return ChatOpenAI(
            model=settings.model_name,
            api_key=settings.api_key,
            base_url=settings.base_url,
            temperature=settings.temperature,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
        )

    resolved_id = profile_id
    if resolved_id is None:
        resolved_id = get_selected_profile_id()

    try:
        profile = get_llm_profile(resolved_id)
        return ChatOpenAI(
            model=profile.model_name,
            api_key=profile.api_key,
            base_url=profile.base_url,
            temperature=profile.temperature,
            timeout=profile.timeout_seconds,
            max_retries=profile.max_retries,
        )
    except ModelConfigurationError:
        config = get_model_settings()
        return ChatOpenAI(
            model=config.model_name,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )
