"""Configuration for penal-code hybrid retrieval."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _load_backend_env() -> None:
    """Load backend/.env into process env once when present."""

    if not _ENV_FILE.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional helper
        return
    load_dotenv(_ENV_FILE, override=False)


@dataclass(frozen=True, slots=True)
class LegalRagConfig:
    collection_name: str = "luat_hinh_su"
    source_system: str = "VN_PENAL_CODE_RAG"
    prefetch_limit: int = 30
    top_k: int = 3
    # NVIDIA rerank scores can be negative; default does not filter by score.
    # Set LEGAL_RAG_MIN_RERANK_SCORE only when you want an explicit floor.
    min_relevance_score: float | None = None
    dense_model: str = "nvidia/nv-embedcode-7b-v1"
    sparse_model: str = "Qdrant/bm25"
    rerank_model: str = "nv-rerank-qa-mistral-4b:1"
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    nvidia_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "LegalRagConfig":
        _load_backend_env()
        return cls(
            collection_name=os.getenv("LEGAL_RAG_COLLECTION", "luat_hinh_su"),
            prefetch_limit=int(os.getenv("LEGAL_RAG_PREFETCH", "30")),
            top_k=int(os.getenv("LEGAL_RAG_TOP_K", "3")),
            min_relevance_score=(
                float(os.environ["LEGAL_RAG_MIN_RERANK_SCORE"])
                if os.getenv("LEGAL_RAG_MIN_RERANK_SCORE") not in (None, "")
                else None
            ),
            qdrant_url=os.getenv("QRANT_URL") or os.getenv("QDRANT_URL"),
            qdrant_api_key=os.getenv("QRANT_API") or os.getenv("QDRANT_API"),
            nvidia_api_key=os.getenv("NVIDIA_API")
            or os.getenv("NVIDIA_API_KEY")
            or "",
        )

    def is_configured(self) -> bool:
        return bool(self.qdrant_url and self.qdrant_api_key and self.nvidia_api_key)
