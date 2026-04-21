from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from config import Config
from database.core import check_db_connection, create_tables
from handlers.session_manager import get_redis
from services.app_state import analytics_service, media_service, transcript_search_service

log = logging.getLogger("SmartTeacher.Bootstrap")


async def log_backend_diagnostics() -> None:
    log.info("🔎 Diagnostic démarrage des services de données:")

    try:
        search_stats = transcript_search_service.get_stats()
        if search_stats.get("backend") == "elasticsearch":
            log.info("   • Elasticsearch: ✅ connecté (%s)", search_stats.get("host", "n/a"))
        else:
            log.info("   • Elasticsearch: ℹ️ recherche en mémoire (fallback actif)")
    except Exception as exc:
        log.info("   • Elasticsearch: ℹ️ recherche en mémoire (%s)", exc)

    try:
        storage_status = media_service.get_status()
        if storage_status.get("provider") == "minio":
            log.info("   • MinIO: ✅ connecté (%s)", storage_status.get("endpoint", "n/a"))
        else:
            log.info("   • MinIO: ℹ️ stockage local (%s)", storage_status.get("local_root", "media"))
    except Exception as exc:
        log.info("   • MinIO: ℹ️ stockage local (%s)", exc)

    try:
        analytics_service._init_ch()
        report = analytics_service.full_report()
        if report.get("backend") == "clickhouse":
            log.info("   • ClickHouse: ✅ connecté")
        else:
            log.info("   • ClickHouse: ℹ️ analytics CSV + mémoire")
    except Exception as exc:
        log.info("   • ClickHouse: ℹ️ analytics CSV + mémoire (%s)", exc)

    try:
        redis_client = await get_redis()
        await asyncio.wait_for(redis_client.ping(), timeout=2.0)
        redis_kwargs = getattr(redis_client.connection_pool, "connection_kwargs", {}) or {}
        redis_host = redis_kwargs.get("host", Config.REDIS_HOST)
        redis_port = redis_kwargs.get("port", Config.REDIS_PORT)
        log.info("   • Redis: ✅ connecté (%s:%s)", redis_host, redis_port)
    except Exception as exc:
        log.info("   • Redis: ⚠️ indisponible (%s)", exc)


async def store_media_bytes(object_name: str, data: bytes, content_type: str) -> None:
    try:
        await asyncio.to_thread(media_service.upload_bytes, data, object_name, content_type)
    except Exception as exc:
        log.debug("media save skipped (%s): %s", object_name, exc)


async def store_media_json(object_name: str, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    await store_media_bytes(object_name, data, "application/json")


@asynccontextmanager
async def create_application_lifespan(app: FastAPI):
    try:
        if await check_db_connection():
            await create_tables()
            log.info("✅ PostgreSQL tables créées/validées")
        else:
            log.info("ℹ️ PostgreSQL indisponible au démarrage — mode dégradé activé")
    except Exception as exc:
        log.info(f"ℹ️ PostgreSQL non disponible au démarrage ({exc}) — mode dégradé activé")

    await log_backend_diagnostics()
    yield
