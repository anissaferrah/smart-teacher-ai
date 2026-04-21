"""Retriever Agent - Multi-query retrieval with confidence scoring."""

import logging
import asyncio
from typing import Dict, Any, List
from infrastructure.logging import get_logger

log = get_logger(__name__)


async def retriever_agent_node(
    state: "AgenticRAGState",
    rag,
) -> Dict[str, Any]:
    """Multi-query retrieval with quality scoring and fallback.
    
    Args:
        state: Current workflow state
        rag: RAG retrieval engine
        
    Returns:
        Dict with retrieved_chunks, retrieval_confidence, and strategy
    """
    query = state.rewritten_query or state.query
    
    log.info(f"🔍 Retrieving context for: '{query}'")
    
    try:
        # Primary retrieval: vector search
        chunks = await asyncio.to_thread(
            rag.retrieve_chunks,
            query,
            course_id=state.course_id,
            top_k=8,
        )
        
        if not chunks or len(chunks) == 0:
            log.warning(f"⚠️  No results from primary retrieval - trying keyword search")
            # Fallback: keyword search
            chunks = await asyncio.to_thread(
                rag.retrieve_chunks,
                query,
                course_id=state.course_id,
                top_k=5,
                use_bm25=True,  # Fallback to BM25
            )
            retrieval_strategy = "bm25_fallback"
        else:
            retrieval_strategy = "vector_primary"
        
        # Calculate average confidence score
        if chunks:
            scores = [chunk.get("score", 0.0) for chunk in chunks]
            avg_confidence = sum(scores) / len(scores) if scores else 0.0
        else:
            avg_confidence = 0.0
        
        state.retrieved_chunks = chunks
        state.retrieval_confidence = avg_confidence
        state.retrieval_strategy = retrieval_strategy
        
        log.info(f"✅ Retrieved {len(chunks)} chunks (confidence: {avg_confidence:.2f}) using {retrieval_strategy}")
        
        # Record in metadata
        state.agent_metadata["retriever"] = {
            "chunk_count": len(chunks),
            "confidence": avg_confidence,
            "strategy": retrieval_strategy,
        }
    
    except Exception as e:
        log.error(f"Retrieval failed: {e}")
        state.retrieved_chunks = []
        state.retrieval_confidence = 0.0
        state.retrieval_strategy = "failed"
    
    return {
        "retrieved_chunks": state.retrieved_chunks,
        "retrieval_confidence": state.retrieval_confidence,
        "retrieval_strategy": state.retrieval_strategy,
        "agent_metadata": state.agent_metadata,
    }


__all__ = [
    "retriever_agent_node",
]
