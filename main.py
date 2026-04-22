"""
SmartTeacher — Professeur IA Vocal
Main FastAPI application and startup.

This file now only contains:
- FastAPI app initialization
- Lifespan management (startup/shutdown)
- Router registration
- Middleware configuration

All business logic has been moved to service modules:
- services.orchestrators.realtime_session_service (WebSocket orchestrator)
- services.orchestrators.presentation_service (slide narration)
- services.orchestrators.qa_service (Q&A + confusion detection)
- infrastructure.config (centralized settings)
- infrastructure.logging (logging setup)
- services.analytics.clickhouse_events (unified analytics)
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from config import Config
from infrastructure.config import settings
from infrastructure.logging import setup_logging, get_logger
from services.bootstrap import log_backend_diagnostics
from services.app_state import (
    dialogue_manager,
    knowledge_retrieval_engine,
    language_brain,
    speech_synthesizer,
    student_profile_manager,
    transcript_search_service,
    analytics_service,
    media_service,
    course_analyzer_service,
    confusion_detector,
)
from database.core import AsyncSessionLocal, check_db_connection, create_tables
from api.ws_router import router as ws_router, set_session_service
from services.orchestrators.realtime_session_service import create_session_service
from api import analytics as analytics_api
from api import auth as auth_api
from api import cache as cache_api
from api import course as course_api
from api import health as health_api
from api import media as media_api
from api import profile as profile_api
from api import search as search_api
from api import sessions as sessions_api
from modules.monitoring.dashboard import router as dashboard_router

# Setup logging
setup_logging(level=settings.analytics.log_level)
log = get_logger("SmartTeacher.Main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic.
    
    Startup:
    - Verify database connectivity
    - Initialize analytics sink
    - Create core service orchestrators
    - Register WebSocket service
    
    Shutdown:
    - Cleanup resources
    """
    log.info("🚀 Starting SmartTeacher...")
    
    try:
        # Database check
        if await check_db_connection():
            await create_tables()
            log.info("✅ PostgreSQL connected and tables created")
        else:
            log.warning("⚠️ PostgreSQL unavailable — degraded mode")
    except Exception as exc:
        log.warning(f"⚠️ PostgreSQL unavailable ({exc}) — degraded mode")
    
    # Log diagnostics
    await log_backend_diagnostics()
    
    # Initialize WebSocket service with all dependencies
    session_service = create_session_service(
        dialogue_mgr=dialogue_manager,
        rag=knowledge_retrieval_engine,
        llm=language_brain,
        voice=speech_synthesizer,
        confusion_detector=confusion_detector,
        transcript_search=transcript_search_service,
        analytics_engine=analytics_service,
        profile_mgr=student_profile_manager,
        media_service=media_service,
        course_analyzer=course_analyzer_service,
    )
    set_session_service(session_service)
    
    log.info("✅ All services initialized")
    log.info(f"🌐 Starting on http://{Config.SERVER_HOST}:{Config.SERVER_PORT}")
    
    yield
    
    log.info("🛑 Shutting down SmartTeacher...")


# Create FastAPI app
app = FastAPI(
    title="Smart Teacher API",
    description="Professeur IA Vocal — WebSocket + REST | STT+RAG+LLM+TTS",
    version="3.0.0",
    lifespan=lifespan,
)


# Middleware
@app.middleware("http")
async def disable_html_cache(request: Request, call_next):
    """Disable caching for HTML responses (UI updates)."""
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Static files
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")


# Register routers
app.include_router(ws_router, prefix="", tags=["websocket"])
app.include_router(dashboard_router, tags=["monitoring"])
app.include_router(health_api.router, prefix="/health", tags=["health"])
app.include_router(auth_api.router, prefix="/auth", tags=["auth"])
app.include_router(sessions_api.router, prefix="/sessions", tags=["sessions"])
app.include_router(search_api.router, prefix="/search", tags=["search"])
app.include_router(analytics_api.router, prefix="/analytics", tags=["analytics"])
app.include_router(cache_api.router, prefix="/cache", tags=["cache"])
app.include_router(media_api.router, tags=["media"])
app.include_router(profile_api.router, prefix="/profile", tags=["profile"])
app.include_router(course_api.router, prefix="", tags=["course"])


@app.get("/dashboard/services")
async def dashboard_services_alias():
    """Compatibility alias for the dashboard services overview."""
    return await health_api.get_dashboard_service_overview()


@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "name": "Smart Teacher API",
        "version": "3.0.0",
        "docs_url": "/docs",
        "status": "running",
    }


@app.get("/config/app-version")
async def get_app_version():
    """Get app version and settings summary."""
    return {
        "version": "3.0.0",
        "rag_enabled": settings.rag.enabled,
        "confusion_detection_enabled": settings.confusion.enabled,
        "rate_adaptation_enabled": settings.realtime_session.enable_rate_adaptation,
        "analytics_clickhouse_enabled": settings.analytics.clickhouse_enabled,
    }


if __name__ == "__main__":
    log.info("")
    log.info("═" * 60)
    log.info("           🎓 SMART TEACHER — PROFESSEUR IA VOCAL")
    log.info("═" * 60)
    log.info("")
    log.info(f"UI               : http://localhost:{Config.SERVER_PORT}/static/index.html")
    log.info(f"API Docs         : http://localhost:{Config.SERVER_PORT}/docs")
    log.info(f"WebSocket        : ws://localhost:{Config.SERVER_PORT}/ws/{{session_id}}")
    log.info("")
    log.info("Press Ctrl+C to stop")
    log.info("")
    
    try:
        uvicorn.run(
            app,
            host=Config.SERVER_HOST,
            port=Config.SERVER_PORT,
            reload=False,
            log_config=None,  # Use our logging setup
        )
    except OSError as exc:
        log.error(f"Failed to bind to {Config.SERVER_HOST}:{Config.SERVER_PORT}: {exc}")
        exit(1)
