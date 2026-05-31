"""In-process BM25 sparse retriever.

Redis and PostgreSQL persistence are handled by ``RAGPipeline``. This class is a
small, fast runtime index over already-loaded chunks.
"""

from __future__ import annotations

import warnings
from typing import Any

import structlog
from rank_bm25 import BM25Okapi

from agent_hub.rag.vector_store import ChunkDoc, SearchResult

logger = structlog.get_logger(__name__)
_jieba: Any | None = None


def _jieba_cut(text: str) -> list[str]:
    global _jieba
    if _jieba is None:
        warnings.filterwarnings(
            "ignore",
            message="pkg_resources is deprecated as an API.*",
            category=UserWarning,
        )
        import jieba

        _jieba = jieba
    return list(_jieba.cut(text))


class SparseRetriever:
    """BM25 sparse retriever keyed by ``(user_id, namespace)``."""

    def __init__(self) -> None:
        self._indices: dict[tuple[str, str], tuple[BM25Okapi, list[ChunkDoc]]] = {}

    def build_index(
        self,
        user_id: str,
        namespace: str,
        chunks: list[ChunkDoc],
    ) -> None:
        chunks = [chunk for chunk in chunks if chunk.content.strip()]
        if not chunks:
            return

        tokenized = [_jieba_cut(chunk.content) for chunk in chunks]
        bm25 = BM25Okapi(tokenized)
        self._indices[(user_id, namespace)] = (bm25, list(chunks))
        logger.info(
            "sparse_index_built",
            user_id=user_id,
            namespace=namespace,
            doc_count=len(chunks),
        )

    def search(
        self,
        user_id: str,
        namespace: str,
        query: str,
        top_k: int = 5,
    ) -> list[SearchResult]:
        key = (user_id, namespace)
        if key not in self._indices:
            return []

        bm25, chunks = self._indices[key]
        query_tokens = _jieba_cut(query)
        scores = bm25.get_scores(query_tokens)
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[:top_k]

        results: list[SearchResult] = []
        for idx, score in ranked:
            if score <= 0:
                continue
            chunk = chunks[idx]
            metadata = dict(chunk.metadata)
            metadata.setdefault("namespace", namespace)
            metadata.setdefault("chunk_index", chunk.chunk_index)
            if chunk.document_id is not None:
                metadata.setdefault("document_id", chunk.document_id)
            chunk_id = self._coerce_chunk_id(metadata.get("chunk_id"), fallback=idx)
            results.append(
                SearchResult(
                    content=chunk.content,
                    score=float(score),
                    metadata=metadata,
                    chunk_id=chunk_id,
                    namespace=str(metadata.get("namespace", namespace)),
                    document_id=metadata.get("document_id"),
                )
            )
        return results

    def search_all_namespaces(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[SearchResult]:
        all_results: list[SearchResult] = []
        for uid, namespace in list(self._indices):
            if uid == user_id:
                all_results.extend(self.search(uid, namespace, query, top_k))

        all_results.sort(key=lambda result: result.score, reverse=True)
        return all_results[:top_k]

    def has_index(self, user_id: str, namespace: str) -> bool:
        return (user_id, namespace) in self._indices

    def namespaces(self, user_id: str) -> list[str]:
        return [namespace for uid, namespace in self._indices if uid == user_id]

    def remove_index(self, user_id: str, namespace: str) -> None:
        self._indices.pop((user_id, namespace), None)

    @staticmethod
    def _coerce_chunk_id(value: object, *, fallback: int) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return fallback
