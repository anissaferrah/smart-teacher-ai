"""
Stage 3: Retriever Agent
Performs dual retrieval (dense embeddings + sparse BM25) with RRF fusion.
Based on Repo 1 (agentic-rag-for-dummies) hybrid retrieval pattern.
"""

import logging
import time
from typing import List, Optional, Dict, Any

log = logging.getLogger("SmartTeacher.RetrieverAgent")


class RetrieverAgent:
    """
    Stage 3 of the agentic RAG pipeline.
    Hybrid retrieval using embeddings + BM25 with Reciprocal Rank Fusion.

    Pattern from Repo 1: Combines dense and sparse retrieval for better coverage.
    """

    def __init__(self, rag_system, hybrid_retriever=None):
        """
        Initialize retriever.

        Args:
            rag_system: Existing RAG system for embedding-based retrieval
            hybrid_retriever: Optional hybrid retriever module for RRF fusion
        """
        self.rag_system = rag_system
        self.hybrid_retriever = hybrid_retriever

    async def retrieve(
        self,
        query: str,
        course_id: Optional[str] = None,
        k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant chunks using hybrid approach.

        Args:
            query: Search query
            course_id: Optional course context
            k: Number of results to return

        Returns:
            List of top-k chunks with metadata and scores
        """
        start_time = time.time()

        try:
            if self.hybrid_retriever:
                # Use hybrid retriever with RRF fusion
                results = await self.hybrid_retriever.hybrid_retrieve(
                    query,
                    course_id=course_id,
                    k=k
                )
                if not results:
                    log.warning("Hybrid retriever returned no chunks; falling back to dense retrieval")
                    results = await self._dense_retrieval_only(query, course_id, k)
                log.info(f"Hybrid retrieval found {len(results)} chunks for '{query}'")
            else:
                # Fallback to dense retrieval only
                results = await self._dense_retrieval_only(query, course_id, k)
                log.info(f"Dense-only retrieval found {len(results)} chunks for '{query}'")

            duration_ms = (time.time() - start_time) * 1000
            log.debug(f"Retrieval completed in {duration_ms:.1f}ms")

            return results

        except Exception as e:
            log.error(f"Retrieval failed: {e}")
            return []

    async def _dense_retrieval_only(
        self,
        query: str,
        course_id: Optional[str],
        k: int
    ) -> List[Dict[str, Any]]:
        """
        Fallback to dense retrieval (embeddings) only.

        Args:
            query: Search query
            course_id: Course context
            k: Number of results

        Returns:
            Retrieved chunks with scores
        """
        try:
            chunks = await self.rag_system.retrieve_chunks(
                query,
                k=k,
                course_id=course_id
            )

            results = []
            for chunk in chunks:
                if isinstance(chunk, tuple) and len(chunk) >= 3:
                    document, score, source_info = chunk[:3]
                    content = getattr(document, "page_content", str(document))
                    metadata = dict(getattr(document, "metadata", {}) or {})
                    source = source_info or metadata.get("source", "unknown")
                    results.append({
                        "content": content,
                        "source": source,
                        "score": float(score),
                        "confidence": float(score),
                        "method": "dense",
                        "metadata": metadata,
                    })
                    continue

                if isinstance(chunk, dict):
                    metadata = dict(chunk.get("metadata", {})) if isinstance(chunk.get("metadata", {}), dict) else {}
                    results.append({
                        "content": chunk.get("content") or chunk.get("page_content") or chunk.get("text") or str(chunk),
                        "source": chunk.get("source") or metadata.get("source", "unknown"),
                        "score": float(chunk.get("score", 0.8) or 0.8),
                        "confidence": float(chunk.get("confidence", chunk.get("score", 0.8)) or 0.8),
                        "method": "dense",
                        "metadata": metadata,
                    })
                    continue

                results.append({
                    "content": chunk.page_content if hasattr(chunk, 'page_content') else str(chunk),
                    "source": getattr(chunk, 'metadata', {}).get('source', 'unknown'),
                    "score": 0.8,
                    "confidence": 0.8,
                    "method": "dense",
                    "metadata": getattr(chunk, 'metadata', {}) or {},
                })

            return results

        except Exception as e:
            log.error(f"Dense retrieval fallback failed: {e}")
            return []

    async def retrieve_with_trace(
        self,
        query: str,
        course_id: Optional[str] = None,
        k: int = 5
    ) -> dict:
        """
        Retrieve chunks and return detailed trace.

        Returns:
            Dictionary with retrieval results and metadata
        """
        start_time = time.time()
        chunks = await self.retrieve(query, course_id, k)
        duration_ms = (time.time() - start_time) * 1000

        return {
            "query": query,
            "chunks_retrieved": len(chunks),
            "chunks": chunks,
            "duration_ms": duration_ms,
            "course_id": course_id,
            "method": "hybrid" if self.hybrid_retriever else "dense"
        }
