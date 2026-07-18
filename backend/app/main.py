"""Backend startup hooks and FastAPI initialization."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
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


def _cors_origins() -> list[str]:
    """Parse CORS_ORIGINS (comma-separated). Supports bare origins; patterns via allow_origin_regex."""
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000").strip()
    if not raw:
        return ["http://localhost:3000"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _cors_origin_regex() -> str | None:
    """Allow Vercel preview URLs when CORS_ORIGINS contains a vercel wildcard token."""
    raw = os.getenv("CORS_ORIGINS", "")
    if "*.vercel.app" in raw or "vercel.app" in raw:
        return r"https://.*\.vercel\.app"
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_backend()
    yield


app = FastAPI(
    title="AML Investigator Backend",
    description="Multi-agent backend for AML alert investigation",
    version="0.1.0",
    lifespan=lifespan,
)

_origins = [o for o in _cors_origins() if "*" not in o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["http://localhost:3000"],
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def read_root():
    return {"status": "ok", "message": "AML Investigator Backend is running"}


@app.get("/health")
def health():
    """Used by Docker healthcheck and Cloudflare Tunnel monitoring."""
    return {"status": "ok"}
