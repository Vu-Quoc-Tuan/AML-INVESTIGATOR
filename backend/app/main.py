"""Backend startup hooks and FastAPI initialization."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI

from app.data.config import RepositoryConfig
from app.data.provider import initialize_data_repository
from app.data.repository import DataRepository
from app.api.router import api_router

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

app = FastAPI(
    title="AML Investigator Backend",
    description="Multi-agent backend for AML alert investigation",
    version="0.1.0",
    lifespan=lifespan
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "AML Investigator Backend is running"}
