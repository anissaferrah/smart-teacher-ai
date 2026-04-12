"""REST API endpoints for Smart Teacher."""

import logging
from typing import Optional
from fastapi import Request, UploadFile, File, Form, HTTPException
from handlers.session_manager import detect_subject, HTTP_SESSIONS

log = logging.getLogger("SmartTeacher.RestRoutes")


# Note: These functions will be called from main.py with app.post/app.get decorators
# This module groups the endpoint logic for clarity


async def handle_session_creation():
    """POST /session - Create session and generate auth token."""
    # Implemented in main.py - generates SESSION_TOKENS entry
    pass


async def handle_ask(
    request: Request,
    question: str,
    language: Optional[str] = None,
    session_id: Optional[str] = None,
    # Injected
    dialogue=None,
    csv_logger=None,
):
    """POST /ask - Answer text question immediately."""
    if not question or len(question.strip()) < 2:
        raise HTTPException(status_code=400, detail="Question too short")

    log.info(f"[{session_id}] ❓ Question: {question[:50]}...")

    history = HTTP_SESSIONS.get(session_id, {}).get("history", [])
    subject = detect_subject(question)

    # Will be orchestrated in main.py with brain.ask()
    return {
        "status": "processing",
        "question": question,
        "subject": subject,
        "language": language,
    }


async def handle_ingest(
    request: Request,
    course_name: str = Form(...),
    files: list[UploadFile] = File(...),
    # Injected
    rag=None,
):
    """POST /ingest - Ingest course materials."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    log.info(f"📂 Ingesting {len(files)} files into course: {course_name}")
    # Orchestration in main.py
    return {"status": "ingesting", "course": course_name, "file_count": len(files)}


async def handle_health_check():
    """GET /health - Health check."""
    return {"status": "ok", "service": "SmartTeacher"}


async def handle_rag_stats(course_id: Optional[str] = None):
    """GET /rag/stats - RAG statistics."""
    return {
        "status": "ok",
        "course_id": course_id,
        "chunks_total": 0,  # Will be calculated in main.py
    }


async def handle_session_get(session_id: str):
    """GET /session/{session_id} - Get session info."""
    session_data = HTTP_SESSIONS.get(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "history_turns": len(session_data.get("history", [])) // 2,
    }


async def handle_search_transcripts(
    query: str,
    session_id: Optional[str] = None,
    limit: int = 10,
):
    """GET /search/transcripts - Search transcripts."""
    if not query:
        raise HTTPException(status_code=400, detail="Query required")

    log.info(f"🔍 Searching transcripts: {query[:50]}...")
    return {"query": query, "results": [], "total": 0}
