from __future__ import annotations

from fastapi import APIRouter

from modules.data.embedding_cache import embedding_cache
from services.app_state import knowledge_retrieval_engine

router = APIRouter(tags=["cache"])


@router.get("/cache/stats")
async def get_embedding_cache_statistics() -> dict:
    stats = embedding_cache.stats()
    rag_stats = knowledge_retrieval_engine.get_stats()

    return {
        "status": "ok",
        "embedding_cache": stats,
        "rag_status": {
            "total_docs": rag_stats.get("total_docs"),
            "collection": rag_stats.get("collection"),
            "bm25_ready": rag_stats.get("bm25_ready"),
        },
        "recommendations": {
            "note": "Cache hits > 60% = très bon. < 30% = peut indiquer queries très variées.",
            "redis_tip": "Assurez-vous que Redis est running: `redis-cli ping`",
        },
    }
