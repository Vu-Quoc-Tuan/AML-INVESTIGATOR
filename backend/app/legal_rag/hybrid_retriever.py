"""Hybrid dense + BM25 + rerank retrieval for penal-code passages."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from .config import LegalRagConfig


@dataclass(frozen=True, slots=True)
class LegalHit:
    article: str
    article_number: int | None
    chapter: str
    section: str
    document: str
    score: float
    hybrid_score: float | None = None
    chunk_id: str | None = None

    @property
    def stable_chunk_id(self) -> str:
        if self.chunk_id:
            return self.chunk_id
        digest = hashlib.sha1(
            f"{self.article}|{self.document[:200]}".encode("utf-8")
        ).hexdigest()[:12]
        return f"chunk-{digest}"


class LegalRetriever(Protocol):
    def retrieve(self, query_text: str, *, top_k: int = 3) -> list[LegalHit]:
        """Return ranked penal-code hits for one natural-language query."""


class LegalRagUnavailableError(RuntimeError):
    """Raised when hybrid retrieval dependencies or credentials are missing."""


class StaticLegalRetriever:
    """Deterministic retriever for unit/integration tests."""

    def __init__(self, hits_by_query: dict[str, list[LegalHit]] | None = None):
        self.hits_by_query = hits_by_query or {}
        self.default_hits = [
            LegalHit(
                article="Điều 324",
                article_number=324,
                chapter="Chương các tội phạm về kinh tế",
                section="Mục rửa tiền",
                document=(
                    "Điều 324. Tội rửa tiền\n"
                    "1. Người nào thực hiện một trong các hành vi sau đây..."
                ),
                score=0.91,
                hybrid_score=0.15,
                chunk_id="chunk-324-demo",
            )
        ]

    def retrieve(self, query_text: str, *, top_k: int = 3) -> list[LegalHit]:
        normalized = unicodedata.normalize("NFC", query_text.strip())
        hits = self.hits_by_query.get(normalized, self.default_hits)
        return list(hits[:top_k])


class HybridLegalRetriever:
    """Live Qdrant hybrid search (dense + sparse RRF) with NVIDIA rerank.

    Heavy dependencies are imported lazily so the package remains importable
    in environments without Qdrant/NVIDIA SDKs installed.
    """

    def __init__(self, config: LegalRagConfig | None = None):
        self.config = config or LegalRagConfig.from_env()
        self._client = None
        self._dense = None
        self._sparse = None
        self._reranker = None

    def _ensure_clients(self) -> None:
        if self._client is not None:
            return
        if not self.config.is_configured():
            raise LegalRagUnavailableError(
                "Legal RAG credentials missing "
                "(QRANT_URL/QRANT_API and NVIDIA_API required)"
            )
        try:
            from qdrant_client import QdrantClient
            from fastembed import SparseTextEmbedding
            from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings, NVIDIARerank
        except ImportError as exc:
            raise LegalRagUnavailableError(
                f"Legal RAG dependencies not installed: {exc}"
            ) from exc

        self._client = QdrantClient(
            url=self.config.qdrant_url,
            api_key=self.config.qdrant_api_key,
            timeout=30,
        )
        self._dense = NVIDIAEmbeddings(
            model=self.config.dense_model,
            api_key=self.config.nvidia_api_key,
            truncate="NONE",
        )
        self._sparse = SparseTextEmbedding(model_name=self.config.sparse_model)
        self._reranker = NVIDIARerank(
            model=self.config.rerank_model,
            api_key=self.config.nvidia_api_key,
        )

    def retrieve(self, query_text: str, *, top_k: int = 3) -> list[LegalHit]:
        from qdrant_client.http import models
        from langchain_core.documents import Document

        self._ensure_clients()
        assert self._client is not None
        assert self._dense is not None
        assert self._sparse is not None
        assert self._reranker is not None

        query_text = unicodedata.normalize("NFC", query_text.strip())
        if not query_text:
            return []

        dense_vector = self._dense.embed_query(query_text)
        sparse_vec = list(self._sparse.embed([query_text]))[0]
        sparse_qdrant = models.SparseVector(
            indices=sparse_vec.indices.tolist(),
            values=sparse_vec.values.tolist(),
        )
        prefetch = [
            models.Prefetch(
                query=dense_vector,
                using="dense",
                limit=self.config.prefetch_limit,
            ),
            models.Prefetch(
                query=sparse_qdrant,
                using="sparse-bm25",
                limit=self.config.prefetch_limit,
            ),
        ]
        hybrid_results = self._client.query_points(
            collection_name=self.config.collection_name,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=self.config.prefetch_limit,
        )

        documents: list[Document] = []
        hybrid_scores: list[float] = []
        for hit in hybrid_results.points:
            payload = hit.payload or {}
            documents.append(
                Document(
                    page_content=str(payload.get("document", "")),
                    metadata={
                        "chapter": payload.get("chapter", "N/A"),
                        "section": payload.get("section", "N/A"),
                        "article": payload.get("article", "N/A"),
                        "article_number": payload.get("article_number"),
                        "hybrid_score": hit.score,
                        "point_id": str(hit.id),
                    },
                )
            )
            hybrid_scores.append(float(hit.score or 0.0))

        if not documents:
            return []

        reranked = self._reranker.compress_documents(
            query=query_text, documents=documents
        )
        limit = top_k or self.config.top_k
        scored_docs: list[tuple[float, object]] = []
        for doc in reranked:
            meta = doc.metadata or {}
            score = float(meta.get("relevance_score", 0.0) or 0.0)
            if (
                self.config.min_relevance_score is not None
                and score < self.config.min_relevance_score
            ):
                continue
            scored_docs.append((score, doc))
        # Keep highest relevance first; NVIDIA scores may be negative.
        scored_docs.sort(key=lambda item: item[0], reverse=True)

        hits: list[LegalHit] = []
        for score, doc in scored_docs[:limit]:
            meta = doc.metadata or {}
            article = str(meta.get("article") or "N/A")
            article_number = meta.get("article_number")
            if article_number is None:
                match = re.search(r"(\d+)", article)
                article_number = int(match.group(1)) if match else None
            hits.append(
                LegalHit(
                    article=article,
                    article_number=int(article_number)
                    if article_number is not None
                    else None,
                    chapter=str(meta.get("chapter") or "N/A"),
                    section=str(meta.get("section") or "N/A"),
                    document=doc.page_content,
                    score=score,
                    hybrid_score=meta.get("hybrid_score"),
                    chunk_id=str(meta.get("point_id") or ""),
                )
            )
        return hits
