"""WebSocket API router for realtime session handling.

This router provides the /ws/{session_id} endpoint and delegates to the
RealtimeSessionService orchestrator.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import logging

from services.orchestrators.realtime_session_service import (
    RealtimeSessionService,
    SESSION_TOKENS,
)
from infrastructure.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["websocket"])

# Service instance (injected from main.py)
_session_service: RealtimeSessionService = None


def set_session_service(service: RealtimeSessionService) -> None:
    """Set the session service instance.
    
    Called from main.py after service initialization.
    
    Args:
        service: Initialized RealtimeSessionService
    """
    global _session_service
    _session_service = service


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Main WebSocket endpoint for realtime sessions.
    
    Args:
        websocket: WebSocket connection
        session_id: Session identifier
    """
    if _session_service is None:
        await websocket.close(code=1011, reason="Service not initialized")
        log.error("Session service not initialized")
        return
    
    await _session_service.handle(websocket, session_id)


@router.post("/session")
async def create_session():
    """Create a new session with authentication token.
    
    Returns:
        {"session_id": str, "token": str}
    
    The client must use this token in the start_session message:
        {"type": "start_session", "token": "...", "language": "fr"}
    """
    import uuid
    import secrets
    
    session_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)  # 256-bit secure random token
    SESSION_TOKENS[session_id] = token
    
    log.info(f"✅ Session created: {session_id[:8]} with auth token")
    return {"session_id": session_id, "token": token}


__all__ = [
    "router",
    "set_session_service",
    "websocket_endpoint",
    "create_session",
]
