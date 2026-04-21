from __future__ import annotations

import secrets
import uuid
from collections import deque

from fastapi import APIRouter, HTTPException, Request

from config import Config
from handlers.session_manager import HTTP_SESSIONS, SESSION_TOKENS
from services.app_state import dialogue_manager

router = APIRouter(tags=["sessions"])


@router.post("/session")
async def create_session_token() -> dict:
    session_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    SESSION_TOKENS[session_id] = token
    return {"session_id": session_id, "token": token}


@router.get("/session/{session_id}")
async def get_session_overview(session_id: str) -> dict:
    session = await dialogue_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    return await dialogue_manager.get_stats(session_id)


@router.post("/session/clear")
async def clear_http_session(request: Request) -> dict:
    sid = request.headers.get("X-Session-ID", "")
    if sid and sid in HTTP_SESSIONS:
        HTTP_SESSIONS[sid].clear()
    if sid:
        await dialogue_manager.end_session(sid)
    return {"status": "cleared", "session_id": sid}
