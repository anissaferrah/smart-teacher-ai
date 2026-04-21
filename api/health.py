from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from config import Config
from services.app_state import analytics_service, knowledge_retrieval_engine, language_brain, media_service, transcript_search_service
from handlers.session_manager import HTTP_SESSIONS

router = APIRouter(tags=["health"])

FAVICON_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0%' stop-color='#7c6dfa'/><stop offset='100%' stop-color='#00e5b0'/></linearGradient></defs>
<rect width='64' height='64' rx='16' fill='#0b0d16'/><rect x='14' y='14' width='36' height='36' rx='10' fill='url(#g)' opacity='.95'/>
<path d='M22 24h20v4H22zm0 8h20v4H22zm0 8h14v4H22z' fill='#ffffff'/></svg>"""


@router.get("/favicon.ico", include_in_schema=False)
async def get_site_favicon() -> Response:
    return Response(content=FAVICON_SVG, media_type="image/svg+xml")


@router.get("/")
async def get_service_root_status() -> dict:
    return {
        "status": "running",
        "rag_ready": knowledge_retrieval_engine.is_ready,
        "tts": Config.TTS_PROVIDER,
        "model": Config.GPT_MODEL,
        "websocket": "ws://<host>:8000/ws/{session_id}",
    }


@router.get("/health")
async def get_service_health() -> dict:
    return {
        "server": "ok",
        "rag": {"ready": knowledge_retrieval_engine.is_ready, **knowledge_retrieval_engine.get_stats()},
        "whisper": Config.WHISPER_MODEL_SIZE,
        "llm": Config.GPT_MODEL,
        "tts": Config.TTS_PROVIDER,
        "sessions": len(HTTP_SESSIONS),
    }


@router.get("/dashboard/services")
async def get_dashboard_service_overview() -> dict:
    from sqlalchemy import text
    from database.core import AsyncSessionLocal
    from handlers.session_manager import get_redis
    import asyncio
    import time
    import requests

    services: dict[str, dict] = {}

    rag_status = knowledge_retrieval_engine.get_status()
    rag_stats = knowledge_retrieval_engine.get_stats()
    storage_status = media_service.get_status()
    services["rag"] = {
        "healthy": bool(rag_status.get("rag_ready")),
        "ready": bool(rag_status.get("rag_ready")),
        "embedding_source": rag_status.get("embedding_source"),
        "embedding_model": rag_status.get("embedding_model"),
        "docs_loaded": rag_status.get("docs_loaded"),
        "bm25_ready": rag_status.get("bm25_available"),
        "qdrant_connected": rag_status.get("qdrant_connected"),
        "vectorstore_available": rag_status.get("vectorstore_available"),
        "collection": rag_stats.get("collection"),
        "backend": rag_stats.get("backend"),
        "role": "Orchestre la recherche hybride et la génération de réponses",
        "retrieves": "Chunks vectoriels Qdrant, scores BM25 et cache d'embeddings",
        "used_in": "modules/multimodal_rag.py, main.py /ask, /course/build, /rag/stats, /debug/rag_test",
    }

    redis_status = {
        "connected": False,
        "endpoint": f"{Config.REDIS_HOST}:{Config.REDIS_PORT}/{Config.REDIS_DB}",
        "latency_ms": None,
    }
    try:
        redis_client = await get_redis()
        redis_kwargs = getattr(redis_client.connection_pool, "connection_kwargs", {}) or {}
        redis_host = redis_kwargs.get("host", Config.REDIS_HOST)
        redis_port = redis_kwargs.get("port", Config.REDIS_PORT)
        redis_db = redis_kwargs.get("db", Config.REDIS_DB)
        start = time.time()
        await asyncio.wait_for(redis_client.ping(), timeout=2.0)
        redis_status.update({
            "connected": True,
            "endpoint": f"{redis_host}:{redis_port}/{redis_db}",
            "latency_ms": round((time.time() - start) * 1000, 1),
        })
    except Exception as exc:
        redis_status["error"] = str(exc)
    redis_status.update({
        "role": "Cache et état temps réel",
        "retrieves": "Sessions WebSocket, état temporaire et latence de traitement",
        "used_in": "handlers/session_manager.py, modules/llm.py, main.py get_redis",
    })
    services["redis"] = redis_status

    postgres_status = {
        "connected": False,
        "endpoint": f"{Config.POSTGRES_HOST}:{Config.POSTGRES_PORT}/{Config.POSTGRES_DB}",
        "latency_ms": None,
    }
    try:
        start = time.time()
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        postgres_status.update({
            "connected": True,
            "latency_ms": round((time.time() - start) * 1000, 1),
        })
    except Exception as exc:
        postgres_status["error"] = str(exc)
    postgres_status.update({
        "role": "Persistance transactionnelle",
        "retrieves": "Sessions, interactions, profils étudiants et événements d'apprentissage",
        "used_in": "database/models.py, database/init_db.py, main.py /course/build, /session, /dashboard/stats",
    })
    services["postgres"] = postgres_status

    def _probe_ollama() -> dict:
        fallback = getattr(language_brain, "fallback", None)
        model_name = getattr(fallback, "model", "mistral")
        base_url = getattr(fallback, "base_url", "http://localhost:11434")
        endpoint = f"{base_url}/api/tags"
        try:
            response = requests.get(endpoint, timeout=2)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [str(m.get("name", "")).split(":")[0] for m in models]
                available = any(model_name in name for name in model_names)
                return {
                    "available": available,
                    "model": model_name,
                    "endpoint": endpoint,
                    "status": "✅ Ready" if available else "⚠️ Model missing",
                    "models": model_names,
                }
            return {
                "available": False,
                "model": model_name,
                "endpoint": endpoint,
                "status": f"❌ HTTP {response.status_code}",
            }
        except Exception as exc:
            return {
                "available": False,
                "model": model_name,
                "endpoint": endpoint,
                "status": "❌ Unavailable",
                "error": str(exc),
            }

    try:
        ollama_status = await asyncio.to_thread(_probe_ollama)
    except Exception as exc:
        ollama_status = {
            "available": False,
            "model": getattr(getattr(language_brain, "fallback", None), "model", "mistral"),
            "endpoint": getattr(getattr(language_brain, "fallback", None), "base_url", "http://localhost:11434") + "/api/tags",
            "status": "❌ Unavailable",
            "error": str(exc),
        }
    ollama_status.update({
        "role": "LLM local de secours",
        "retrieves": "Modèles disponibles via /api/tags et réponses locales via Ollama",
        "used_in": "modules/llm.py, main.py /ask, quiz fallback",
    })
    services["ollama"] = ollama_status

    try:
        search_stats = transcript_search_service.get_stats()
    except Exception as exc:
        search_stats = {
            "backend": "memory",
            "total": 0,
            "error": str(exc),
        }
    services["elasticsearch"] = {
        "available": search_stats.get("backend") == "elasticsearch",
        "backend": search_stats.get("backend"),
        "total": search_stats.get("total"),
        "host": search_stats.get("host"),
        "index": search_stats.get("index"),
        "note": search_stats.get("note"),
        "role": "Recherche full-text historique",
        "retrieves": "Questions, réponses et index texte des transcriptions",
        "used_in": "modules/transcript_search.py, main.py /dashboard/services",
    }

    services["minio"] = {
        "configured": storage_status.get("configured"),
        "active": storage_status.get("active"),
        "provider": storage_status.get("provider"),
        "endpoint": storage_status.get("endpoint"),
        "bucket": storage_status.get("bucket"),
        "secure": storage_status.get("secure"),
        "local_root": storage_status.get("local_root"),
        "role": "Stockage objet des médias",
        "retrieves": "PDF, slides, audio et objets listés via /media-list",
        "used_in": "modules/media_storage.py, main.py /media/{path}, /media-list, modules/course_builder.py",
    }

    return {
        "updated_at": __import__("time").time(),
        "services": services,
    }
