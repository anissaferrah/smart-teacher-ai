"""Hybrid retrieval with RRF fusion (dense + sparse)."""

from __future__ import annotations

import inspect
import logging
import asyncio as _asyncio
from typing import Any, Dict, List, Optional

log = logging.getLogger("SmartTeacher.HybridRetriever")


class HybridRetriever:
    """Combines the existing RAG engine with optional dense and sparse fallbacks."""

    def __init__(self, rag_system=None, vector_db=None, bm25=None):
        self.rag_system = rag_system or vector_db
        self.vector_db = vector_db or self.rag_system
        self.bm25 = bm25

    async def hybrid_retrieve(
        self,
        query: str,
        course_id: Optional[str] = None,
        k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Retrieve using the strongest available backend first."""
        try:
            engine_results = await self._from_rag_engine(query, course_id, k)
            if engine_results:
                log.info("Hybrid retrieval used the main RAG engine (%d results)", len(engine_results))
                return engine_results[:k]

            dense_results = await self._dense_search(query, course_id, k * 2)
            sparse_results = await self._sparse_search(query, course_id, k * 2)
            fused = self._rrf_fusion(dense_results, sparse_results, k)

            if fused:
                log.info(
                    "Hybrid retrieval: %d dense + %d sparse -> %d fused",
                    len(dense_results),
                    len(sparse_results),
                    len(fused),
                )
                return fused

            if dense_results:
                return dense_results[:k]
            if sparse_results:
                return sparse_results[:k]
            return []

        except Exception as exc:
            log.error("Hybrid retrieval failed: %s", exc)
            dense_results = await self._dense_search(query, course_id, k)
            return dense_results[:k]

    async def _from_rag_engine(self, query: str, course_id: Optional[str], k: int) -> List[Dict[str, Any]]:
        if not self.rag_system or not hasattr(self.rag_system, "retrieve_chunks"):
            return []

        raw_results = await _asyncio.to_thread(self.rag_system.retrieve_chunks, query, k=k, course_id=course_id)
        if inspect.isawaitable(raw_results):
            raw_results = await raw_results
        return [self._normalize_result(item, method="rag") for item in raw_results or []]

    async def _dense_search(self, query: str, course_id: Optional[str], k: int) -> List[Dict[str, Any]]:
        if not self.vector_db:
            return []

        if hasattr(self.vector_db, "retrieve_chunks"):
            raw_results = self.vector_db.retrieve_chunks(query, k=k, course_id=course_id)
            if inspect.isawaitable(raw_results):
                raw_results = await raw_results
            return [self._normalize_result(item, method="dense") for item in raw_results or []]

        if hasattr(self.vector_db, "search_similar"):
            raw_results = self.vector_db.search_similar(query, k=k, filters={"course_id": course_id} if course_id else None)
            if inspect.isawaitable(raw_results):
                raw_results = await raw_results
            return [self._normalize_result(item, method="dense") for item in raw_results or []]

        return []

    async def _sparse_search(self, query: str, course_id: Optional[str], k: int) -> List[Dict[str, Any]]:
        if not self.bm25:
            return []

        try:
            if hasattr(self.bm25, "invoke"):
                raw_results = self.bm25.invoke(query)
            elif hasattr(self.bm25, "get_relevant_documents"):
                raw_results = self.bm25.get_relevant_documents(query)
            else:
                raw_results = []

            normalized = [self._normalize_result(item, method="sparse") for item in raw_results or []]
            if course_id:
                normalized = [item for item in normalized if item.get("metadata", {}).get("course") == course_id]
            return normalized[:k]
        except Exception as exc:
            log.error("Sparse search failed: %s", exc)
            return []

    def _normalize_result(self, item: Any, method: str) -> Dict[str, Any]:
        if isinstance(item, tuple) and len(item) >= 3:
            document, score, source = item[:3]
            content = getattr(document, "page_content", str(document))
            metadata = dict(getattr(document, "metadata", {}) or {})
            return {
                "content": content,
                "score": float(score),
                "confidence": float(score),
                "source": source or metadata.get("source") or metadata.get("document_id") or "unknown",
                "metadata": metadata,
                "method": method,
            }

        if isinstance(item, dict):
            metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
            content = item.get("content") or item.get("page_content") or item.get("text") or str(item)
            return {
                "content": content,
                "score": float(item.get("score", item.get("confidence", 0.0)) or 0.0),
                "confidence": float(item.get("confidence", item.get("score", 0.0)) or 0.0),
                "source": item.get("source") or metadata.get("source") or metadata.get("document_id") or "unknown",
                "metadata": metadata,
                "method": item.get("method", method),
            }

        content = getattr(item, "page_content", str(item))
        metadata = dict(getattr(item, "metadata", {}) or {})
        return {
            "content": content,
            "score": float(getattr(item, "score", 0.0) or 0.0),
            "confidence": float(getattr(item, "confidence", getattr(item, "score", 0.0)) or 0.0),
            "source": metadata.get("source") or metadata.get("document_id") or "unknown",
            "metadata": metadata,
            "method": method,
        }

    def _result_key(self, result: Dict[str, Any]) -> str:
        metadata = result.get("metadata", {}) or {}
        return str(
            metadata.get("chunk_id")
            or metadata.get("content_hash")
            or result.get("source")
            or result.get("content", "")[:120]
        )

    def _rrf_fusion(
        self,
        dense_results: List[Dict[str, Any]],
        sparse_results: List[Dict[str, Any]],
        k: int,
    ) -> List[Dict[str, Any]]:
        """Reciprocal Rank Fusion: combines rankings from dense and sparse."""
        scores: Dict[str, float] = {}
        results_by_key: Dict[str, Dict[str, Any]] = {}
        constant = 60

        for rank, result in enumerate(dense_results):
            key = self._result_key(result)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rank + constant + 1)
            results_by_key[key] = result

        for rank, result in enumerate(sparse_results):
            key = self._result_key(result)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rank + constant + 1)
            results_by_key[key] = result

        ranked_keys = sorted(scores, key=lambda key: scores[key], reverse=True)
        fused: List[Dict[str, Any]] = []
        for key in ranked_keys[:k]:
            result = dict(results_by_key[key])
            result["rrf_score"] = scores[key]
            fused.append(result)

        log.debug("RRF fusion: %d/%d results ranked", len(fused), k)
        return fused[:k]
