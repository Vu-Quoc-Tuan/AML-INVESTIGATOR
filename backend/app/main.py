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
    yield
    # Clean up on shutdown if necessary


def _parse_cors_origins(raw_origins: str) -> list[str]:
    """Return unique, non-empty origins while preserving configured order."""

    return list(
        dict.fromkeys(origin.strip() for origin in raw_origins.split(",") if origin.strip())
    )


def create_app(cors_origins: str | None = None) -> FastAPI:
    """Build the FastAPI app from explicit input or the process environment."""

    configured_origins = _parse_cors_origins(
        os.getenv("CORS_ORIGINS", "") if cors_origins is None else cors_origins
    )
    application = FastAPI(
        title="AML Investigator Backend",
        description="Multi-agent backend for AML alert investigation",
        version="0.1.0",
        lifespan=lifespan,
    )

    if configured_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=configured_origins,
            allow_credentials=configured_origins != ["*"],
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
