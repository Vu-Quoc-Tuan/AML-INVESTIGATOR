"""Backend startup hooks and FastAPI initialization."""

from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.data.config import RepositoryConfig
from app.data.provider import initialize_data_repository
from app.data.repository import DataRepository
from app.detection.config import DetectionSettings
from app.detection.repository import DetectionRepository
from app.investigation_control.repository import InvestigationControlRepository


def initialize_backend(
    data_path: str | Path | None = None,
    config: RepositoryConfig | None = None,
) -> DataRepository:
    """Warm and validate shared backend data explicitly at process startup."""
    return initialize_data_repository(data_path=data_path, config=config)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the repository on startup
    initialize_backend()
    detection_settings = DetectionSettings.from_env()
    DetectionRepository(
        detection_settings.db_path,
        initial_mode=detection_settings.initial_run_mode,
        lease_seconds=detection_settings.claim_lease_seconds,
        retry_delay_seconds=detection_settings.retry_delay_seconds,
        max_attempts=detection_settings.max_attempts,
    )
    InvestigationControlRepository(
        detection_settings.db_path
    ).interrupt_active_runs()
    yield
    # Clean up on shutdown if necessary


def _parse_cors_origins(raw_origins: str) -> list[str]:
    """Return unique, non-empty origins while preserving configured order."""

    return list(
        dict.fromkeys(origin.strip() for origin in raw_origins.split(",") if origin.strip())
    )


def _exact_cors_origins(raw_origins: str) -> list[str]:
    """Origins safe for allow_origins (Starlette does not expand host wildcards)."""

    return [origin for origin in _parse_cors_origins(raw_origins) if "*" not in origin]


def _cors_origin_regex(raw_origins: str) -> str | None:
    """Allow Vercel preview/prod hosts when CORS_ORIGINS mentions vercel.app."""

    if "*.vercel.app" in raw_origins or "vercel.app" in raw_origins:
        return r"https://.*\.vercel\.app"
    return None


def create_app(cors_origins: str | None = None) -> FastAPI:
    """Build the FastAPI app from explicit input or the process environment."""

    # Default allows local Next.js; override with CORS_ORIGINS in production
    # (Vercel origin(s) + optional https://*.vercel.app for previews).
    raw_origins = (
        os.getenv("CORS_ORIGINS", "http://localhost:3000")
        if cors_origins is None
        else cors_origins
    )
    exact_origins = _exact_cors_origins(raw_origins)
    origin_regex = _cors_origin_regex(raw_origins)
    application = FastAPI(
        title="AML Investigator Backend",
        description="Multi-agent backend for AML alert investigation",
        version="0.1.0",
        lifespan=lifespan,
    )

    if exact_origins or origin_regex:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=exact_origins,
            allow_origin_regex=origin_regex,
            allow_credentials=exact_origins != ["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    application.include_router(api_router, prefix="/api/v1")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/")
    def read_root() -> dict[str, str]:
        return {"status": "ok", "message": "AML Investigator Backend is running"}

    return application


app = create_app()
