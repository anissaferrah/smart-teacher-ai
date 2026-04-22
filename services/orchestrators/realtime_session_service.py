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
import base64
from email.mime import message
import logging
import uuid
import secrets
import threading
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
from handlers.session_manager import audio_bytes_to_numpy
from modules.monitoring.dashboard import record_checkpoint_event, record_session_event
from services.analytics.clickhouse_events import get_analytics_sink
from services.app_state import transcription_service
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
        presentation_cancel_event: threading.Event = threading.Event()
        
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

        async def emit_step_status(step: dict[str, Any]) -> None:
            """Translate QA step payloads into visible status updates."""
            state = str(step.get("state", "processing") or "processing").lower()
            message = step.get("summary") or step.get("title") or step.get("key") or "Traitement…"
            await send({
                "type": "status_update",
                "state": state,
                "message": message,
                "reasoning_step": step,
            })

        async def send_audio_stream(
            audio_bytes: Optional[bytes],
            mime_type: Optional[str],
            *,
            turn_id: Optional[int] = None,
            stream_id: Optional[str] = None,
            clip: bool = True,
            is_final: bool = False,
        ) -> None:
            if audio_bytes is None and not is_final:
                return

            payload: dict[str, Any] = {
                "type": "audio_stream",
                "mime_type": mime_type or "audio/mpeg",
                "clip": clip,
                "is_final": is_final,
            }
            if turn_id is not None:
                payload["turn_id"] = turn_id
            if stream_id is not None:
                payload["stream_id"] = stream_id
            if audio_bytes:
                payload["audio_data"] = base64.b64encode(audio_bytes).decode("ascii")

            await send(payload)

        def _slide_session_key(slide: Optional[CourseSlide]) -> str:
            if not slide:
                return ""
            return f"{slide.course_id}:{slide.chapter_index}:{slide.section_index}"

        def _estimate_resume_cursor(
            presentation_text: str,
            playback_snapshot: Optional[dict[str, Any]] = None,
        ) -> int:
            if not presentation_text:
                return 0

            snapshot = playback_snapshot or {}
            kind = str(snapshot.get("kind", "presentation") or "presentation").lower()
            if kind not in {"presentation", "presenting"}:
                return 0

            current_time = snapshot.get("currentTime", snapshot.get("current_time", 0))
            duration = snapshot.get("duration", snapshot.get("audio_duration", 0))

            try:
                current_time_value = float(current_time or 0)
                duration_value = float(duration or 0)
            except (TypeError, ValueError):
                return 0

            if current_time_value <= 0 or duration_value <= 0:
                return 0

            ratio = max(0.0, min(current_time_value / duration_value, 1.0))
            return max(0, min(len(presentation_text), int(round(len(presentation_text) * ratio))))

        def _is_presentation_snapshot(playback_snapshot: Optional[dict[str, Any]]) -> bool:
            if not playback_snapshot:
                return True

            kind = str(playback_snapshot.get("kind", "presentation") or "presentation").lower()
            return kind in {"presentation", "presenting"}

        async def handle_presentation_turn(course_id: str, chapter_idx: int, section_idx: int) -> None:
            nonlocal ctx

            try:
                if presentation_cancel_event.is_set():
                    presentation_cancel_event.clear()

                slide = await self.presentation_service.load_slide(course_id, chapter_idx, section_idx)
                if not slide:
                    await send({"type": "error", "message": "Slide not found"})
                    return

                ctx.slide = slide
                ctx.narration_cursor = 0

                try:
                    await self.dialogue.save_course_position(
                        session_id=session_id,
                        course_id=slide.course_id,
                        chapter_index=slide.chapter_index,
                        section_index=slide.section_index,
                        char_pos=0,
                    )
                except Exception as exc:
                    log.debug(f"[{session_id[:8]}] Failed to save course position: {exc}")

                await send({
                    "type": "status_update",
                    "state": "presenting",
                    "message": "Chargement du cours…",
                })

                presentation_reasoning = [
                    {
                        "step": 1,
                        "title": "Chargement du cours",
                        "summary": f"Cours: {slide.course_title}",
                        "state": "presenting",
                        "status": "done",
                        "details": {
                            "chapter_number": slide.chapter_number,
                            "section_number": slide.section_number,
                            "chapter_title": slide.chapter_title,
                            "section_title": slide.section_title,
                            "course_id": course_id,
                        },
                    },
                    {
                        "step": 2,
                        "title": "Sélection du chapitre",
                        "summary": f"Chapitre {slide.chapter_number}: {slide.chapter_title}",
                        "state": "presenting",
                        "status": "done",
                        "details": {
                            "chapter_index": chapter_idx,
                            "chapter_number": slide.chapter_number,
                            "section_index": section_idx,
                            "section_number": slide.section_number,
                            "slide_path": slide.slide_path,
                        },
                    },
                    {
                        "step": 3,
                        "title": "Génération de l'explication",
                        "summary": "LLM Thinking…",
                        "state": "presenting",
                        "status": "running",
                        "details": {
                            "course_id": course_id,
                            "chapter_index": chapter_idx,
                            "chapter_number": slide.chapter_number,
                            "section_index": section_idx,
                            "section_number": slide.section_number,
                        },
                    },
                ]

                await send({
                    "type": "presentation_started",
                    "language": ctx.language,  
                    "course": slide.course_title,
                    "chapter": slide.chapter_title,
                    "chapter_number": slide.chapter_number,
                    "chapter_display": f"Chapter {slide.chapter_number}",
                    "section": slide.section_title,
                    "section_number": slide.section_number,
                    "image_url": slide.slide_path,
                    "slide_path": slide.slide_path,
                    "narration": slide.slide_content or "Présentation en cours…",
                    "audio_url": f"/media/slide_{course_id}_{chapter_idx}_{section_idx}.mp3",
                    "reasoning": {
                        "steps": presentation_reasoning,
                        "current_state": "presenting",
                        "current_stage": "presentation_started",
                    },
                })

                try:
                    from services.app_state import analytics_service

                    analytics_service.record_section(
                        session_id=session_id,
                        course_id=slide.course_id,
                        chapter_idx=slide.chapter_index,
                        section_idx=slide.section_index,
                        event_type="section_start",
                        language=ctx.language,
                    )
                except Exception as exc:
                    log.debug(f"[{session_id[:8]}] Analytics section_start record failed: {exc}")

                try:
                    record_session_event({
                        "session_id": session_id,
                        "language": ctx.language,
                        "subject": slide.course_domain or ctx.subject or "unknown",
                        "course_id": slide.course_id,
                        "chapter_index": slide.chapter_index,
                        "chapter_number": slide.chapter_number,
                        "chapter_title": slide.chapter_title,
                        "section_index": slide.section_index,
                        "section_number": slide.section_number,
                        "section_title": slide.section_title,
                        "slide_title": slide.section_title or slide.chapter_title or slide.course_title,
                        "total_time": 0.0,
                        "stt_time": 0.0,
                        "llm_time": 0.0,
                        "tts_time": 0.0,
                        "meets_kpi": True,
                        "confusion": False,
                        "confusion_reason": "",
                        "source": "presentation_start",
                    })
                except Exception as exc:
                    log.debug(f"[{session_id[:8]}] Dashboard presentation event failed: {exc}")

                log.info(f"📖 Presentation started: {slide.course_title}/{slide.chapter_title}")

                narration, audio_bytes = await self.presentation_service.explain_slide_focused(
                    slide,
                    ctx.student_profile,
                    ctx.language,
                    cancel_event=presentation_cancel_event,
                )

                if presentation_cancel_event.is_set():
                    log.info(f"[{session_id[:8]}] Presentation cancelled during generation")
                    return

                ctx.current_slide_narration = narration or slide.slide_content or "Présentation en cours…"

                try:
                    await self.dialogue.save_presentation_snapshot(
                        session_id=session_id,
                        slide_id=_slide_session_key(slide),
                        presentation_text=ctx.current_slide_narration,
                        presentation_cursor=ctx.narration_cursor,
                        slide_title=slide.section_title or slide.chapter_title or slide.course_title or "",
                    )
                except Exception as exc:
                    log.debug(f"[{session_id[:8]}] Failed to save presentation snapshot: {exc}")

                await send({
                    "type": "slide_data",
                    "course": slide.course_title,
                    "course_title": slide.course_title,
                    "chapter": slide.chapter_title,
                    "chapter_title": slide.chapter_title,
                    "chapter_number": slide.chapter_number,
                    "chapter_display": f"Chapter {slide.chapter_number}",
                    "section": slide.section_index + 1,
                    "section_number": slide.section_number,
                    "section_title": slide.section_title,
                    "title": slide.section_title or slide.chapter_title or slide.course_title,
                    "text": narration or slide.slide_content or "Présentation en cours…",
                    "narration": narration or slide.slide_content or "Présentation en cours…",
                    "image_url": slide.slide_path,
                    "slide_path": slide.slide_path,
                })

                await send({
                    "type": "status_update",
                    "state": "presenting",
                    "message": slide.section_title or slide.chapter_title or "Présentation en cours…",
                    "reasoning_step": {
                        "step": 3,
                        "title": "Génération de l'explication",
                        "summary": "Explication générée",
                        "state": "presenting",
                        "status": "done",
                    },
                })

                if audio_bytes:
                    await send_audio_stream(
                        audio_bytes,
                        "audio/mpeg",
                        clip=True,
                        is_final=False,
                    )

                await send({
                    "type": "status_update",
                    "state": "presenting",
                    "message": slide.section_title or slide.chapter_title or "Présentation en cours…",
                })
            except asyncio.CancelledError:
                log.info(f"[{session_id[:8]}] Presentation cancelled")
                return
            except Exception as exc:
                log.error(f"Presentation handling failed: {exc}")
                await send({"type": "error", "message": str(exc)})

        async def _resume_presentation_if_paused(trigger: str = "manual_resume") -> None:
            nonlocal ctx

            if not ctx:
                return

            dialogue_ctx = await self.dialogue.resume_session(session_id)
            paused_state = dialogue_ctx.paused_state if dialogue_ctx else {}
            if not paused_state:
                return

            slide_key = (
                paused_state.get("presentation_key")
                or paused_state.get("slide_id")
                or _slide_session_key(ctx.slide)
            )
            presentation_text = (
                paused_state.get("presentation_text")
                or ctx.current_slide_narration
                or (ctx.slide.slide_content if ctx.slide else "")
            )
            resume_text = presentation_text

            if presentation_text:
                try:
                    resume_text = await self.dialogue.get_resume_text(session_id, presentation_text)
                except Exception as exc:
                    log.debug(f"[{session_id[:8]}] Failed to build resume text: {exc}")

            resume_cursor = int(
                paused_state.get("presentation_cursor")
                or paused_state.get("char_offset")
                or (dialogue_ctx.char_position if dialogue_ctx else 0)
                or ctx.narration_cursor
                or 0
            )

            ctx.state = DialogState.PRESENTING.value
            ctx.narration_cursor = resume_cursor
            if presentation_text:
                ctx.current_slide_narration = presentation_text

            await send({
                "type": "resumed",
                "slide_id": slide_key,
                "resume_cursor": resume_cursor,
                "trigger": trigger,
            })

            try:
                if ctx.slide:
                    record_checkpoint_event({
                        "session_id": session_id,
                        "checkpoint_type": "resume",
                        "reason": trigger,
                        "language": ctx.language,
                        "subject": ctx.subject or ctx.slide.course_domain or "unknown",
                        "chapter_index": ctx.slide.chapter_index,
                        "section_index": ctx.slide.section_index,
                        "char_position": resume_cursor,
                        "slide_title": ctx.slide.section_title or ctx.slide.chapter_title or ctx.slide.course_title,
                    })
            except Exception as exc:
                log.debug(f"[{session_id[:8]}] Resume checkpoint event failed: {exc}")

            if resume_text and ctx.slide:
                await send({
                    "type": "status_update",
                    "state": "presenting",
                    "message": "Reprise de la présentation…",
                })

                await send({
                    "type": "slide_data",
                    "course": ctx.slide.course_title,
                    "course_title": ctx.slide.course_title,
                    "chapter": ctx.slide.chapter_title,
                    "chapter_title": ctx.slide.chapter_title,
                    "chapter_number": ctx.slide.chapter_number,
                    "chapter_display": f"Chapter {ctx.slide.chapter_number}",
                    "section": ctx.slide.section_index + 1,
                    "section_number": ctx.slide.section_number,
                    "section_title": ctx.slide.section_title,
                    "title": ctx.slide.section_title or ctx.slide.chapter_title or ctx.slide.course_title,
                    "text": resume_text,
                    "narration": resume_text,
                    "image_url": ctx.slide.slide_path,
                    "slide_path": ctx.slide.slide_path,
                })

                try:
                    audio_bytes, _, _, _, mime_type = await self.voice.generate_audio_async(
                        resume_text,
                        language=ctx.language,
                        rate_override="+10%" if settings.realtime_session.enable_rate_adaptation else "+0%",
                    )
                    if audio_bytes:
                        await send_audio_stream(
                            audio_bytes,
                            mime_type,
                            clip=True,
                            is_final=False,
                        )
                except Exception as exc:
                    log.debug(f"[{session_id[:8]}] Resume audio generation failed: {exc}")

            await send({
                "type": "status_update",
                "state": "presenting",
                "message": ctx.slide.section_title if ctx and ctx.slide else "Présentation en cours…",
            })

        async def handle_text_question_turn(
            question_text: str,
            language: str,
            subject: str,
            turn_id: Optional[int],
        ) -> None:
            nonlocal ctx

            try:
                await send({
                    "type": "status_update",
                    "state": "processing",
                    "message": "Traitement de la question…",
                })

                stream_id = uuid.uuid4().hex[:8]

                async def emit_audio_chunk(audio_bytes: Optional[bytes], mime_type: Optional[str], is_final: bool = False) -> None:
                    await send_audio_stream(
                        audio_bytes,
                        mime_type,
                        turn_id=turn_id,
                        stream_id=stream_id,
                        clip=True,
                        is_final=is_final,
                    )

                answer, _, metrics = await self.qa_service.process_text_question(
                    session_id=session_id,
                    question_text=question_text,
                    ctx=ctx,
                    history=history,
                    language=language,
                    subject=subject,
                    on_step=emit_step_status,
                    on_audio_chunk=emit_audio_chunk,
                )

                combined_reasoning = metrics.get("reasoning_trace", [])

                await send({
                    "type": "text_answer",
                    "content": answer,
                    "text": answer,
                    "metrics": {
                        "llm_time_ms": metrics.get("llm_time_ms", 0.0),
                        "tts_time_ms": metrics.get("tts_time_ms", 0.0),
                        "rag_chunks": metrics.get("rag_chunks", 0),
                        "confusion_detected": metrics.get("confusion_detected", False),
                    },
                    "reasoning": {
                        "steps": combined_reasoning,
                        "current_state": metrics.get("system_state", "idle"),
                        "current_stage": metrics.get("current_stage", "completed"),
                        "agentic_rag_state": metrics.get("agentic_rag_state", {}),
                    },
                })

                history.append({"role": "student", "content": question_text})
                history.append({"role": "assistant", "content": answer})

                await send({
                    "type": "status_update",
                    "state": "idle",
                    "message": "Réponse envoyée",
                })

                try:
                    llm_time_s = float(metrics.get("llm_time_ms", 0.0) or 0.0) / 1000.0
                    tts_time_s = float(metrics.get("tts_time_ms", 0.0) or 0.0) / 1000.0
                    total_time_s = llm_time_s + tts_time_s
                    record_session_event({
                        "session_id": session_id,
                        "language": language,
                        "subject": subject or (ctx.slide.course_domain if ctx and ctx.slide else "unknown"),
                        "question": question_text,
                        "answer": answer,
                        "course_id": ctx.slide.course_id if ctx and ctx.slide else "",
                        "chapter_index": ctx.slide.chapter_index if ctx and ctx.slide else None,
                        "chapter_title": ctx.slide.chapter_title if ctx and ctx.slide else "",
                        "section_index": ctx.slide.section_index if ctx and ctx.slide else None,
                        "section_title": ctx.slide.section_title if ctx and ctx.slide else "",
                        "slide_title": (ctx.slide.section_title if ctx and ctx.slide else "") or (ctx.slide.chapter_title if ctx and ctx.slide else ""),
                        "llm_time": round(llm_time_s, 3),
                        "stt_time": 0.0,
                        "tts_time": round(tts_time_s, 3),
                        "total_time": round(total_time_s, 3),
                        "meets_kpi": total_time_s <= 5.0,
                        "confusion": bool(metrics.get("confusion_detected", False)),
                        "confusion_reason": metrics.get("confusion_reason", ""),
                        "source": "ws_text_question",
                    })
                except Exception as exc:
                    log.debug(f"[{session_id[:8]}] Dashboard session event failed: {exc}")

                await _resume_presentation_if_paused(trigger="auto_after_answer")

                log.info(f"✅ Question answered ({metrics.get('llm_time_ms', 0):.0f}ms)")
            except asyncio.CancelledError:
                log.info(f"[{session_id[:8]}] Text question cancelled")
                return
            except Exception as exc:
                log.error(f"Text question handling failed: {exc}")
                await send({"type": "error", "message": str(exc)})

        async def handle_audio_question_turn(
            encoded_audio: str,
            question_language: Optional[str],
            subject: str,
            turn_id: Optional[int],
        ) -> None:
            nonlocal ctx

            try:
                await send({
                    "type": "status_update",
                    "state": "processing",
                    "message": "Transcription de la question…",
                })

                try:
                    audio_bytes = base64.b64decode(encoded_audio)
                except Exception:
                    await send({"type": "error", "message": "Invalid audio payload"})
                    return

                audio_np = audio_bytes_to_numpy(audio_bytes)
                text, stt_time, detected_language, lang_prob, _audio_duration = await asyncio.to_thread(
                    transcription_service.transcribe,
                    audio_np,
                    question_language,
                )
                effective_language = (
                    detected_language
                    if detected_language and detected_language != "unknown"
                    else (question_language or ctx.language)
                )

                if not text or not text.strip():
                    await send({
                        "type": "status_update",
                        "state": "idle",
                        "message": "Aucune voix détectée",
                    })
                    await send({"type": "error", "message": "Aucune voix détectée"})
                    return

                await send({
                    "type": "transcription",
                    "text": text,
                    "label": "Étudiant",
                    "is_final": True,
                    "language": effective_language,
                    "confidence": round(lang_prob, 2),
                })

                await send({
                    "type": "status_update",
                    "state": "processing",
                    "message": "Question transcrite",
                    "reasoning_step": {
                        "step": 0,
                        "title": "Transcription de la question",
                        "summary": "Question transcrite",
                        "state": "processing",
                        "status": "done",
                    },
                })

                stream_id = uuid.uuid4().hex[:8]

                async def emit_audio_chunk(audio_bytes: Optional[bytes], mime_type: Optional[str], is_final: bool = False) -> None:
                    await send_audio_stream(
                        audio_bytes,
                        mime_type,
                        turn_id=turn_id,
                        stream_id=stream_id,
                        clip=True,
                        is_final=is_final,
                    )

                answer, _, metrics = await self.qa_service.process_text_question(
                    session_id=session_id,
                    question_text=text,
                    ctx=ctx,
                    history=history,
                    language=effective_language,
                    subject=subject,
                    on_step=emit_step_status,
                    on_audio_chunk=emit_audio_chunk,
                )

                combined_reasoning = metrics.get("reasoning_trace", [])

                await send({
                    "type": "text_answer",
                    "content": answer,
                    "text": answer,
                    "metrics": {
                        "llm_time_ms": metrics.get("llm_time_ms", 0.0),
                        "tts_time_ms": metrics.get("tts_time_ms", 0.0),
                        "rag_chunks": metrics.get("rag_chunks", 0),
                        "confusion_detected": metrics.get("confusion_detected", False),
                    },
                    "reasoning": {
                        "steps": combined_reasoning,
                        "current_state": metrics.get("system_state", "idle"),
                        "current_stage": metrics.get("current_stage", "completed"),
                        "agentic_rag_state": metrics.get("agentic_rag_state", {}),
                    },
                })

                history.append({"role": "student", "content": text})
                history.append({"role": "assistant", "content": answer})

                await send({
                    "type": "status_update",
                    "state": "idle",
                    "message": "Réponse envoyée",
                })

                try:
                    stt_time_s = float(stt_time or 0.0) / 1000.0
                    llm_time_s = float(metrics.get("llm_time_ms", 0.0) or 0.0) / 1000.0
                    tts_time_s = float(metrics.get("tts_time_ms", 0.0) or 0.0) / 1000.0
                    total_time_s = stt_time_s + llm_time_s + tts_time_s
                    record_session_event({
                        "session_id": session_id,
                        "language": effective_language,
                        "subject": subject or (ctx.slide.course_domain if ctx and ctx.slide else "unknown"),
                        "question": text,
                        "stt_text": text,
                        "answer": answer,
                        "course_id": ctx.slide.course_id if ctx and ctx.slide else "",
                        "chapter_index": ctx.slide.chapter_index if ctx and ctx.slide else None,
                        "chapter_title": ctx.slide.chapter_title if ctx and ctx.slide else "",
                        "section_index": ctx.slide.section_index if ctx and ctx.slide else None,
                        "section_title": ctx.slide.section_title if ctx and ctx.slide else "",
                        "slide_title": (ctx.slide.section_title if ctx and ctx.slide else "") or (ctx.slide.chapter_title if ctx and ctx.slide else ""),
                        "llm_time": round(llm_time_s, 3),
                        "stt_time": round(stt_time_s, 3),
                        "tts_time": round(tts_time_s, 3),
                        "total_time": round(total_time_s, 3),
                        "meets_kpi": total_time_s <= 5.0,
                        "confusion": bool(metrics.get("confusion_detected", False)),
                        "confusion_reason": metrics.get("confusion_reason", ""),
                        "source": "ws_audio_question",
                    })
                except Exception as exc:
                    log.debug(f"[{session_id[:8]}] Dashboard audio event failed: {exc}")

                await _resume_presentation_if_paused(trigger="auto_after_answer")

                log.info(f"✅ Audio question answered ({metrics.get('llm_time_ms', 0):.0f}ms, STT={stt_time:.0f}ms)")
            except asyncio.CancelledError:
                log.info(f"[{session_id[:8]}] Audio question cancelled")
                return
            except Exception as exc:
                log.error(f"Audio question handling failed: {exc}")
                await send({"type": "error", "message": str(exc)})
        
        async def cancel_tasks() -> None:
            """Cancel all pending tasks."""
            nonlocal audio_stream_task, presentation_task, text_question_task, next_slide_prefetch_task

            presentation_cancel_event.set()
            
            for task in [audio_stream_task, presentation_task, text_question_task, next_slide_prefetch_task]:
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            audio_stream_task = None
            presentation_task = None
            text_question_task = None
            next_slide_prefetch_task = None
            presentation_cancel_event.clear()
        
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

                        try:
                            await self.dialogue.create_session(
                                session_id=session_id,
                                language=language,
                                student_level=profile.level if profile else "lycée",
                            )
                        except Exception as exc:
                            log.debug(f"[{session_id[:8]}] Dialogue session bootstrap failed: {exc}")
                        
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

                        await cancel_tasks()

                        course_id = message.get("course_id", "")
                        chapter_idx = message.get("chapter_index", 0)
                        section_idx = message.get("section_index", 0)
                        requested_language = str(message.get("language", "") or "").strip().lower()
                        if requested_language and requested_language != "auto":
                            ctx.language = requested_language
                        else:
                            # ✅ Sync session language to course language
                            try:
                                import uuid as _uuid
                                from database.core import AsyncSessionLocal
                                from database.repositories.crud import get_course
                                async with AsyncSessionLocal() as _db:
                                    _course = await get_course(_db, _uuid.UUID(course_id))
                                    if _course and _course.language:
                                        ctx.language = _course.language
                                        log.info(f"[{session_id[:8]}] Lang synced to course: {ctx.language}")
                            except Exception as _exc:
                                log.debug(f"[{session_id[:8]}] Could not sync course lang: {_exc}")

                        presentation_task = asyncio.create_task(
                            handle_presentation_turn(course_id, chapter_idx, section_idx)
                        )

                    # Audio question
                    elif msg_type in {"audio_question", "audio"}:
                        if not ctx:
                            await send({"type": "error", "message": "Session not initialized"})
                            continue

                        encoded_audio = message.get("audio_data") or message.get("data") or ""
                        requested_language = str(message.get("language", "")).strip().lower()
                        question_language = None if requested_language in {"", "auto"} else requested_language
                        subject = message.get("subject", "") or message.get("topic", "")

                        if not encoded_audio:
                            await send({"type": "error", "message": "Audio payload missing"})
                            continue

                        try:
                            base64.b64decode(encoded_audio)
                        except Exception:
                            await send({"type": "error", "message": "Invalid audio payload"})
                            continue

                        await cancel_tasks()

                        audio_stream_task = asyncio.create_task(
                            handle_audio_question_turn(
                                encoded_audio,
                                question_language,
                                subject,
                                message.get("turn_id"),
                            )
                        )

                    # Text question
                    elif msg_type in {"text_question", "question"}:
                        if not ctx:
                            await send({"type": "error", "message": "Session not initialized"})
                            continue

                        question = message.get("content") or message.get("text") or message.get("question") or ""
                        _msg_lang = str(message.get("language", "") or "").strip().lower()
                        if _msg_lang and _msg_lang not in ("auto", ""):
                            language = _msg_lang
                        else:
                            # Auto-detect language from the actual question text
                            try:
                                from langdetect import detect as _detect
                                _detected = _detect(question)
                                language = _detected[:2].lower() if _detected else ctx.language
                            except Exception:
                                language = ctx.language
                        subject = message.get("subject", "") or message.get("topic", "")

                        await cancel_tasks()

                        text_question_task = asyncio.create_task(
                            handle_text_question_turn(question, language, subject, message.get("turn_id"))
                        )

                    # Quiz generation
                    elif msg_type == "quiz":
                        if not ctx:
                            await send({"type": "error", "message": "Session not initialized"})
                            continue

                        await cancel_tasks()

                        language = message.get("language", ctx.language)
                        subject = (
                            message.get("subject", "")
                            or message.get("topic", "")
                            or (ctx.slide.course_domain if ctx.slide else "")
                        )
                        topic = (
                            message.get("topic")
                            or message.get("section_title")
                            or (ctx.slide.section_title if ctx.slide else "")
                            or subject
                        )

                        await send({
                            "type": "status_update",
                            "state": "processing",
                            "message": "Génération du quiz…",
                        })

                        quiz_question, metadata = await self.qa_service.process_quiz(
                            session_id=session_id,
                            ctx=ctx,
                            language=language,
                            subject=subject,
                            topic=topic,
                        )

                        quiz_payload = {
                            "title": f"Quiz - {ctx.slide.section_title if ctx.slide else 'Cours'}",
                            "topic": topic or subject,
                            "difficulty": ctx.student_profile.level if ctx.student_profile else ctx.language,
                            "chapter_title": ctx.slide.chapter_title if ctx.slide else "",
                            "section_title": ctx.slide.section_title if ctx.slide else "",
                            "questions": [],
                        }

                        if quiz_question:
                            quiz_payload["questions"] = [
                                {
                                    "question": quiz_question,
                                    "options": [],
                                    "explanation": "",
                                    "practical": "",
                                    "practical_answer": "",
                                }
                            ]

                        await send({
                            "type": "quiz_prompt",
                            "question": quiz_question,
                            "quiz": quiz_payload,
                            "metadata": metadata,
                        })

                        await send({
                            "type": "status_update",
                            "state": "idle",
                            "message": "Quiz prêt",
                        })

                    # Interruption / barge-in
                    elif msg_type == "interrupt":
                        reason = message.get("reason", "student_speaking")
                        playback_snapshot = message.get("playback_snapshot") or {}
                        await cancel_tasks()

                        if ctx and ctx.slide and reason in {"student_speaking", "typed_question"} and _is_presentation_snapshot(playback_snapshot):
                            presentation_text = ctx.current_slide_narration or ctx.slide.slide_content or ""
                            slide_key = _slide_session_key(ctx.slide)
                            slide_title = ctx.slide.section_title or ctx.slide.chapter_title or ctx.slide.course_title or ""
                            resume_cursor = _estimate_resume_cursor(presentation_text, playback_snapshot)

                            if resume_cursor <= 0 and ctx.narration_cursor:
                                resume_cursor = max(0, min(len(presentation_text), int(ctx.narration_cursor)))

                            ctx.narration_cursor = resume_cursor

                            try:
                                await self.dialogue.pause_session(
                                    session_id,
                                    slide_id=slide_key,
                                    char_offset=resume_cursor,
                                    presentation_text=presentation_text,
                                    presentation_cursor=resume_cursor,
                                    presentation_key=slide_key,
                                    slide_title=slide_title,
                                )
                            except Exception as exc:
                                log.debug(f"[{session_id[:8]}] Failed to persist interrupt state: {exc}")

                        if ctx:
                            ctx.state = DialogState.LISTENING.value

                        await send({
                            "type": "interrupt",
                            "reason": reason,
                            "resume_cursor": ctx.narration_cursor if ctx else 0,
                        })
                        await send({
                            "type": "status_update",
                            "state": "listening",
                            "message": "Interruption détectée",
                        })

                    # Pause presentation
                    elif msg_type == "pause":
                        if not ctx or not ctx.slide:
                            continue

                        await cancel_tasks()

                        playback_snapshot = message.get("playback_snapshot") or {}
                        reason = message.get("reason", "user_request")
                        presentation_text = ctx.current_slide_narration or ctx.slide.slide_content or ""
                        slide_key = _slide_session_key(ctx.slide)
                        slide_title = ctx.slide.section_title or ctx.slide.chapter_title or ctx.slide.course_title or ""
                        resume_cursor = _estimate_resume_cursor(presentation_text, playback_snapshot)

                        if resume_cursor <= 0 and ctx.narration_cursor and _is_presentation_snapshot(playback_snapshot):
                            resume_cursor = max(0, min(len(presentation_text), int(ctx.narration_cursor)))

                        ctx.narration_cursor = resume_cursor
                        ctx.state = DialogState.PAUSED.value

                        if _is_presentation_snapshot(playback_snapshot):
                            try:
                                await self.dialogue.pause_session(
                                    session_id,
                                    slide_id=slide_key,
                                    char_offset=resume_cursor,
                                    presentation_text=presentation_text,
                                    presentation_cursor=resume_cursor,
                                    presentation_key=slide_key,
                                    slide_title=slide_title,
                                )
                            except Exception as exc:
                                log.debug(f"[{session_id[:8]}] Failed to persist pause state: {exc}")

                        checkpoint = await self.presentation_service.handle_pause(ctx, reason)

                        try:
                            record_checkpoint_event({
                                "session_id": session_id,
                                "checkpoint_type": "pause",
                                "reason": reason,
                                "language": ctx.language,
                                "subject": ctx.subject or ctx.slide.course_domain or "unknown",
                                "chapter_index": ctx.slide.chapter_index,
                                "section_index": ctx.slide.section_index,
                                "char_position": resume_cursor,
                                "slide_title": slide_title,
                            })
                        except Exception as exc:
                            log.debug(f"[{session_id[:8]}] Pause checkpoint event failed: {exc}")

                        await send({
                            "type": "paused",
                            "checkpoint": checkpoint,
                            "resume_cursor": resume_cursor,
                            "slide_id": slide_key,
                        })

                    # Resume presentation
                    elif msg_type == "resume":
                        if not ctx:
                            await send({"type": "error", "message": "Session not initialized"})
                            continue

                        await _resume_presentation_if_paused(trigger="manual_resume")

                    # Ping (keep-alive)
                    elif msg_type == "ping":
                        await send({"type": "pong"})
                
                except asyncio.TimeoutError:
                    await send({"type": "status_update", "state": "idle", "message": "Session active (keepalive)"})
                    continue
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
