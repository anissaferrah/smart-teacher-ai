"""Realtime session orchestrator service.

This service manages the complete WebSocket session lifecycle:
- Session initialization and authentication
- State transitions
- Coordination of STT/RAG/LLM/TTS pipeline
- Task management (streaming, prefetch, etc.)
- Error recovery and graceful degradation

This is the central orchestration point that replaces the monolithic
websocket_endpoint function in main.py.
"""

import asyncio
import logging
import uuid
import secrets
from typing import Optional, Dict, Any, Callable, Deque
from collections import deque
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect
import json

from domain.session_state import (
    SessionContext, DialogState, StudentProfile, CourseSlide, can_transition
)
from infrastructure.config import settings
from infrastructure.logging import get_logger
from services.analytics.clickhouse_events import get_analytics_sink
from services.orchestrators.presentation_service import PresentationService
from services.orchestrators.qa_service import QAService

log = get_logger(__name__)


# Global session token registry (temporary; replace with DB in production)
SESSION_TOKENS: Dict[str, str] = {}
HTTP_SESSIONS: Dict[str, Dict[str, Any]] = {}


class RealtimeSessionService:
    """Orchestrates a complete realtime WebSocket session."""
    
    def __init__(
        self,
        dialogue_mgr,
        rag,
        llm,
        voice,
        confusion_detector,
        transcript_search,
        analytics_engine,
        profile_mgr,
        media_service,
        course_analyzer,
    ):
        """Initialize the realtime session service.
        
        Args:
            dialogue_mgr: Dialogue manager
            rag: RAG retrieval engine
            llm: Language model
            voice: TTS synthesizer
            confusion_detector: Confusion detection model
            transcript_search: Transcript search service
            analytics_engine: Analytics engine
            profile_mgr: Student profile manager
            media_service: Media storage service
            course_analyzer: Course analyzer
        """
        self.dialogue = dialogue_mgr
        self.rag = rag
        self.llm = llm
        self.voice = voice
        self.confusion_detector = confusion_detector
        self.transcript_search = transcript_search
        self.analytics_engine = analytics_engine
        self.profile_mgr = profile_mgr
        self.media = media_service
        self.course_analyzer = course_analyzer
        self.analytics = get_analytics_sink()
        
        # Services
        self.presentation_service = PresentationService(
            dialogue_mgr=dialogue_mgr,
            rag=rag,
            llm=llm,
            voice=voice,
        )
        self.qa_service = QAService(
            rag=rag,
            llm=llm,
            voice=voice,
            confusion_detector=confusion_detector,
            analytics_sink=self.analytics,
        )
    
    async def handle(self, websocket: WebSocket, session_id: str) -> None:
        """Main WebSocket session handler.
        
        Args:
            websocket: FastAPI WebSocket connection
            session_id: Session identifier
        """
        await websocket.accept()
        log.info(f"🔌 WebSocket connected: {session_id[:8]}")
        
        # Session state
        ctx: Optional[SessionContext] = None
        websocket_closed = False
        send_lock = asyncio.Lock()
        
        # Task management
        audio_stream_task: Optional[asyncio.Task] = None
        presentation_task: Optional[asyncio.Task] = None
        text_question_task: Optional[asyncio.Task] = None
        next_slide_prefetch_task: Optional[asyncio.Task] = None
        
        # Conversat history
        history: list[dict] = []
        
        async def send(data: dict) -> None:
            """Send message to client (thread-safe)."""
            if websocket_closed:
                return
            async with send_lock:
                try:
                    await websocket.send_json(data)
                except Exception as e:
                    log.error(f"Failed to send: {e}")
        
        async def cancel_tasks() -> None:
            """Cancel all pending tasks."""
            nonlocal audio_stream_task, presentation_task, text_question_task, next_slide_prefetch_task
            
            for task in [audio_stream_task, presentation_task, text_question_task, next_slide_prefetch_task]:
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
        
        try:
            # Main message loop
            while not websocket_closed:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=300,  # 5 minute timeout
                    )
                    
                    msg_type = message.get("type", "")
                    
                    # Authentication/session start
                    if msg_type == "start_session":
                        token = message.get("token", "")
                        language = message.get("language", "fr")
                        
                        # Verify token
                        if session_id not in SESSION_TOKENS or SESSION_TOKENS[session_id] != token:
                            await send({"type": "error", "message": "Invalid token"})
                            await websocket.close(code=1008)  # Policy violation
                            return
                        
                        # Initialize session context
                        student_id = message.get("student_id")
                        profile = None
                        if student_id:
                            profile = await self.profile_mgr.get_or_create(student_id)
                        
                        ctx = SessionContext.create(
                            student_id=student_id,
                            profile=profile,
                            language=language,
                        )
                        
                        await send({
                            "type": "session_started",
                            "session_id": session_id,
                            "language": language,
                        })
                        log.info(f"✅ Session started: {session_id[:8]}, student: {student_id}")
                    
                    # Presentation request
                    elif msg_type == "start_presentation":
                        if not ctx:
                            await send({"type": "error", "message": "Session not initialized"})
                            continue
                        
                        course_id = message.get("course_id", "")
                        chapter_idx = message.get("chapter_index", 0)
                        section_idx = message.get("section_index", 0)
                        
                        # Load slide
                        slide = await self.presentation_service.load_slide(
                            course_id, chapter_idx, section_idx
                        )
                        
                        if not slide:
                            await send({"type": "error", "message": "Slide not found"})
                            continue
                        
                        # Update context
                        ctx.slide = slide
                        
                        # Generate narration
                        narration, audio_bytes = await self.presentation_service.explain_slide_focused(
                            slide, ctx.student_profile, ctx.language
                        )
                        
                        ctx.current_slide_narration = narration
                        
                        # Send presentation to client
                        await send({
                            "type": "presentation_started",
                            "course": slide.course_title,
                            "chapter": slide.chapter_title,
                            "section": slide.section_title,
                            "narration": narration,
                            "audio_url": f"/media/slide_{course_id}_{chapter_idx}_{section_idx}.mp3",
                        })
                        
                        log.info(f"📖 Presentation started: {slide.course_title}/{slide.chapter_title}")
                    
                    # Text question
                    elif msg_type == "text_question":
                        if not ctx:
                            await send({"type": "error", "message": "Session not initialized"})
                            continue
                        
                        question = message.get("content", "")
                        language = message.get("language", ctx.language)
                        subject = message.get("subject", "")
                        
                        # Process question
                        answer, audio_bytes, metrics = await self.qa_service.process_text_question(
                            session_id=session_id,
                            question_text=question,
                            ctx=ctx,
                            language=language,
                            subject=subject,
                        )
                        
                        # Send response
                        await send({
                            "type": "text_answer",
                            "content": answer,
                            "metrics": {
                                "llm_time_ms": metrics.get("llm_time_ms", 0.0),
                                "tts_time_ms": metrics.get("tts_time_ms", 0.0),
                                "rag_chunks": metrics.get("rag_chunks", 0),
                                "confusion_detected": metrics.get("confusion_detected", False),
                            },
                        })
                        
                        history.append({
                            "role": "student",
                            "content": question,
                        })
                        history.append({
                            "role": "assistant",
                            "content": answer,
                        })
                        
                        log.info(f"✅ Question answered ({metrics.get('llm_time_ms', 0):.0f}ms)")
                    
                    # Pause presentation
                    elif msg_type == "pause":
                        if not ctx or not ctx.slide:
                            continue
                        
                        reason = message.get("reason", "user_request")
                        checkpoint = await self.presentation_service.handle_pause(ctx, reason)
                        
                        await send({
                            "type": "paused",
                            "checkpoint": checkpoint,
                        })
                    
                    # Resume presentation
                    elif msg_type == "resume":
                        await send({
                            "type": "resumed",
                        })
                    
                    # Ping (keep-alive)
                    elif msg_type == "ping":
                        await send({"type": "pong"})
                
                except asyncio.TimeoutError:
                    await send({"type": "timeout", "message": "Session inactive"})
                    break
                except WebSocketDisconnect:
                    websocket_closed = True
                    break
                except Exception as e:
                    log.error(f"Error processing message: {e}")
                    await send({"type": "error", "message": str(e)})
        
        finally:
            # Cleanup
            websocket_closed = True
            await cancel_tasks()
            
            # Log session end
            if ctx:
                self.analytics.record('session_ended', {
                    'duration_minutes': (datetime.utcnow() - ctx.created_at).total_seconds() / 60,
                    'interaction_count': ctx.interaction_count,
                }, session_id=session_id)
            
            log.info(f"🔌 WebSocket disconnected: {session_id[:8]}")


def create_session_service(
    dialogue_mgr,
    rag,
    llm,
    voice,
    confusion_detector,
    transcript_search,
    analytics_engine,
    profile_mgr,
    media_service,
    course_analyzer,
) -> RealtimeSessionService:
    """Factory function to create session service with all dependencies.
    
    Args:
        dialogue_mgr: Dialogue manager instance
        rag: RAG retrieval engine
        llm: Language model
        voice: TTS synthesizer
        confusion_detector: Confusion detection model
        transcript_search: Transcript search service
        analytics_engine: Analytics engine
        profile_mgr: Student profile manager
        media_service: Media storage service
        course_analyzer: Course analyzer
        
    Returns:
        RealtimeSessionService: Initialized service
    """
    return RealtimeSessionService(
        dialogue_mgr=dialogue_mgr,
        rag=rag,
        llm=llm,
        voice=voice,
        confusion_detector=confusion_detector,
        transcript_search=transcript_search,
        analytics_engine=analytics_engine,
        profile_mgr=profile_mgr,
        media_service=media_service,
        course_analyzer=course_analyzer,
    )


__all__ = [
    "RealtimeSessionService",
    "create_session_service",
    "SESSION_TOKENS",
    "HTTP_SESSIONS",
]
