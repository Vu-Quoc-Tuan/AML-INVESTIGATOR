"""Hybrid legal retrieval over the Vietnamese Penal Code corpus."""

from .config import LegalRagConfig
from .hybrid_retriever import HybridLegalRetriever, LegalHit, LegalRetriever
from .tool_adapter import build_legal_tools

__all__ = [
    "HybridLegalRetriever",
    "LegalHit",
    "LegalRagConfig",
    "LegalRetriever",
    "build_legal_tools",
]
