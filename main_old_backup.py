import asyncio
import base64
import json
import hashlib
import io
import logging
import os
import socket
import tempfile
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, Request, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from langdetect import detect

from config import Config
from handlers.session_manager import HTTP_SESSIONS, SESSION_TOKENS, detect_lang_text, audio_bytes_to_numpy, detect_subject, get_http_session
from handlers.audio_pipeline import run_pipeline_streaming, run_pipeline
from api import analytics as analytics_api
from api import cache as cache_api
from api import course as course_api
from api import health as health_api
from api import media as media_api
from api import profile as profile_api
from api import search as search_api
from api import sessions as sessions_api
from modules.pedagogy.dialogue import DialogueManager, DialogState, SessionContext, get_redis
from modules.monitoring.dashboard import router as dashboard_router, record_checkpoint_event, record_session_event, record_trace_event
from services.bootstrap import log_backend_diagnostics
from services.app_state import (
    analytics_service,
    dialogue_manager,
    knowledge_retrieval_engine,
    language_brain,
    media_service,
    speech_synthesizer,
    student_profile_manager,
    transcript_search_service,
    course_analyzer_service,
)
from database.core import AsyncSessionLocal, check_db_connection, create_tables
from database.repositories.crud import (
    create_learning_session,
    get_session_stats,
    log_interaction,
    log_learning_event,
    update_session_state,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s ΓÇö %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SmartTeacher.Main")

rag = knowledge_retrieval_engine
voice = speech_synthesizer
brain = language_brain
dialogue = dialogue_manager
profile_mgr = student_profile_manager
transcript_searcher = transcript_search_service
analytics_engine = analytics_service
media_storage = media_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialisation légère au démarrage, avec dégradation si PostgreSQL est indisponible."""
    try:
        if await check_db_connection():
            await create_tables()
            log.info("✅ PostgreSQL tables créées/validées")
        else:
            log.info("⚠️ PostgreSQL indisponible au démarrage — mode dégradé activé")
    except Exception as exc:
        log.info(f"⚠️ PostgreSQL non disponible au démarrage ({exc}) — mode dégradé activé")

    await log_backend_diagnostics()

    yield


app = FastAPI(
    title="Smart Teacher API",
    description="Professeur IA Vocal — WebSocket + REST | STT+RAG+LLM+TTS",
    version="3.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def disable_html_cache(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")


app.include_router(dashboard_router)
app.include_router(health_api.router)
app.include_router(sessions_api.router)
app.include_router(search_api.router)
app.include_router(analytics_api.router)
app.include_router(cache_api.router)
app.include_router(media_api.router)
app.include_router(profile_api.router)
app.include_router(course_api.router)


async def save_media_bytes(object_name: str, data: bytes, content_type: str) -> None:
    try:
        await asyncio.to_thread(media_storage.upload_bytes, data, object_name, content_type)
    except Exception as exc:
        log.debug("media save skipped (%s): %s", object_name, exc)


async def save_media_json(object_name: str, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    await save_media_bytes(object_name, data, "application/json")


async def load_course_slide_context(course_id: str, chapter_index: int, section_index: int) -> dict | None:
    """Charge la slide courante d'un cours depuis PostgreSQL."""
    if not course_id:
        return None

    try:
        from database.repositories.crud import get_course_with_structure
        import uuid

        async with AsyncSessionLocal() as db:
            course = await get_course_with_structure(db, uuid.UUID(course_id))
            if not course:
                return None

            chapters = sorted(course.chapters, key=lambda ch: ch.order or 0)
            if chapter_index < 0 or chapter_index >= len(chapters):
                return None

            chapter = chapters[chapter_index]
            sections = sorted(chapter.sections, key=lambda sec: sec.order or 0)
            if section_index < 0 or section_index >= len(sections):
                return None

            section = sections[section_index]
            slide_path = section.image_url or (
                section.image_urls[0]
                if getattr(section, "image_urls", None)
                else ""
            )

            total_sections = sum(len(sorted(ch.sections, key=lambda sec: sec.order or 0)) for ch in chapters)
            global_slide_index = sum(len(sorted(ch.sections, key=lambda sec: sec.order or 0)) for ch in chapters[:chapter_index]) + section_index
            progress_pct = 0
            if total_sections > 1:
                progress_pct = round(global_slide_index / max(total_sections - 1, 1) * 100)

            return {
                "course_id": str(course.id),
                "course_title": course.title,
                "course_subject": course.subject,
                "course_domain": course.domain or "general",
                "language": course.language,
                "level": course.level,
                "chapter_index": chapter_index,
                "chapter_order": chapter.order or chapter_index + 1,
                "chapter_title": chapter.title,
                "section_index": section_index,
                "section_order": section.order or section_index + 1,
                "section_title": section.title,
                "content": section.content or "",
                "slide_path": slide_path,
                "image_url": slide_path,
                "slide_index": global_slide_index,
                "slide_type": "image" if slide_path else "section",
                "keywords": [c.term for c in section.concepts if c.term],
                "concepts": [
                    {
                        "term": c.term,
                        "definition": c.definition,
                        "example": c.example,
                        "type": c.concept_type,
                    }
                    for c in section.concepts
                ],
                "progress_pct": progress_pct,
            }
    except Exception as exc:
        log.debug(
            "Unable to load slide context for course %s ch=%s sec=%s: %s",
            course_id,
            chapter_index,
            section_index,
            exc,
        )
        return None


# ═══════════════════════════════════════════════════════════════════════
#  WEBSOCKET — Pipeline Vocal Temps Réel
# ═══════════════════════════════════════════════════════════════════════

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint principal.
    Gère le cycle complet : présentation → écoute → réponse → reprise.
    """
    await websocket.accept()
    log.info(f"🔌 WebSocket connecté : {session_id[:8]}")

    ctx: SessionContext | None = None
    audio_buffer: list[bytes] = []
    history: list[dict]       = []
    session_lang:  str         = "fr"
    session_level: str         = "lycée"
    saved_chi:     int         = 0      # position chapitre sauvegardée
    saved_si:      int         = 0      # position section sauvegardée
    in_course:     bool        = False  # étudiant en cours de présentation
    send_lock:     asyncio.Lock = asyncio.Lock()
    audio_stream_task: asyncio.Task | None = None
    current_stream_id: int = 0
    presentation_task: asyncio.Task | None = None
    next_slide_prefetch_task: asyncio.Task | None = None
    current_presentation_key: tuple[str, int, int] | None = None
    current_presentation_text: str = ""
    current_presentation_cursor: int = 0
    current_chapter_title: str = ""
    current_section_title: str = ""
    websocket_closed = False
    student_profile: dict = {}  # ✅ Profil de l'étudiant pour timing adaptatif
    interrupt_audio: bool = False  # 🚨 Flag pour interrompre le TTS en temps réel
    presentation_start_time: float = 0.0  # ✅ NOUVEAU: Timestamp quand présentation commence
    learning_session_db_id: uuid.UUID | None = None
    text_question_task: asyncio.Task | None = None
    active_text_turn_id: int = 0
    text_turn_seq: int = 0

    async def send(data: dict):
        nonlocal websocket_closed
        if websocket_closed:
            return False
        async with send_lock:
            if websocket_closed:
                return False
            try:
                await websocket.send_json(data)
                return True
            except (WebSocketDisconnect, RuntimeError) as exc:
                websocket_closed = True
                log.info(f"[{session_id[:8]}] WebSocket fermÃ© pendant send: {exc}")
                return False

    async def send_state(state: DialogState, substep: str = "", details: dict = None, metrics: dict = None, turn_id: int | None = None):
        """
        ✅ ULTIME v2: État ENRICHI COMPLET avec tous les sous-états et métriques temps réel.
        
        Livre un message formaté parfait avec:
        - État principal (8 états)
        - Sous-étape TRÈS détaillée (16+ substeps)
        - Métriques temps réel complètes
        
        Examples:
            await send_state(DialogState.PROCESSING, "rag_search", {}, {"chunks":5, "elapsed":0.3})
            await send_state(DialogState.PROCESSING, "llm_thinking", {}, {"tokens":145, "llm_time":1.2})
            await send_state(DialogState.PROCESSING, "confusion_detected", {"reason":"prosody_slow_speech"}, {"confidence":0.82})
        """
        
        # ═══════════════════════════════════════════════════════════════════════
        # DICTIONNAIRE COMPLET DES 16+ SOUS-ÉTAPES
        # ═══════════════════════════════════════════════════════════════════════
        substep_full = {
            # Audio Capture
            "stt_language_detection": {"emoji": "🌍", "step": "Language Detection", "desc": "Language identification", "detail": "(FR/EN auto-detect)"},
            "prosody_analysis": {"emoji": "📊", "step": "Prosody Analysis", "desc": "Speech rate, hesitations, intonation", "detail": "(Emotion & confusion detection)"},
            
            # RAG Phase
            "rag_search": {"emoji": "🔍", "step": "Document Search", "desc": "Vector search + BM25", "detail": "(Course documents)"},
            "rag_ranking": {"emoji": "📑", "step": "Ranking Results", "desc": "Sort by relevance", "detail": "(Calculated score)"},
            
            # Confusion Detection
            "confusion_analyzing": {"emoji": "🧠", "step": "Confusion Analysis", "desc": "Comprehension check", "detail": "(8-level detection)"},
            "confusion_detected": {"emoji": "🤔", "step": "CONFUSION DETECTED", "desc": "LLM prompt adaptation", "detail": "(Reformulation needed)"},
            "confusion_none": {"emoji": "✅", "step": "No Confusion", "desc": "Clear question", "detail": "(Standard prompt)"},
            
            # Semantic Checking
            "semantic_check": {"emoji": "🔗", "step": "Semantic Check", "desc": "Historical comparison", "detail": "(OpenAI similarity>85%)"},
            "semantic_repeat": {"emoji": "🔄", "step": "Similar Question", "desc": "Repetition detected", "detail": "(Different angle proposed)"},
            
            # LLM Processing
            "llm_thinking": {"emoji": "🧠", "step": "LLM Thinking", "desc": "Response generation", "detail": "(OpenAI/Mistral in progress)"},
            "llm_generating": {"emoji": "✍️", "step": "Generating Response", "desc": "Text construction", "detail": "(Tokens generated)"},
            
            # Streaming Phase
            "streaming_llm": {"emoji": "📡", "step": "LLM Streaming", "desc": "Direct transmission", "detail": "(Complete response)"},
            "tts_generating": {"emoji": "🎙️", "step": "Audio Generation", "desc": "Text-to-speech conversion", "detail": "(Edge TTS in progress)"},
            "tts_streaming": {"emoji": "📢", "step": "Audio Streaming", "desc": "Audio playback", "detail": "(Direct chunks)"},
            
            # Completion
            "response_complete": {"emoji": "🎉", "step": "Response Complete", "desc": "Sent successfully", "detail": "(Awaiting feedback)"},
            "feedback_listening": {"emoji": "👂", "step": "Voice Feedback", "desc": "Say YES or REPEAT", "detail": "(2-3 seconds)"},
        }
        
        # ═══════════════════════════════════════════════════════════════════════
        # MAIN STATES
        # ═══════════════════════════════════════════════════════════════════════
        state_map = {
            DialogState.IDLE: {"emoji": "🛑", "name": "Idle", "description": "No active session"},
            DialogState.INDEXING: {"emoji": "📚", "name": "Indexing", "description": "Course ingestion in progress..."},
            DialogState.PRESENTING: {"emoji": "🎓", "name": "Presenting", "description": "AI presenting content"},
            DialogState.LISTENING: {"emoji": "👂", "name": "Listening", "description": "AI listening to your question..."},
            DialogState.PROCESSING: {"emoji": "⚙️", "name": "Processing", "description": "Analysis and processing..."},
            DialogState.RESPONDING: {"emoji": "🗣️", "name": "Responding", "description": "AI generating response..."},
            DialogState.WAITING: {"emoji": "⏳", "name": "Waiting", "description": "Awaiting feedback..."},
            DialogState.CLARIFICATION: {"emoji": "❓", "name": "Clarification", "description": "Clarification needed..."},
        }

        state_info = state_map.get(state, {})
        emoji = state_info.get("emoji", "❓")
        state_name = state_info.get("name", "Unknown")

        msg_lines = [f"{emoji} {state_name}"]

        if state_info.get("description"):
            msg_lines.append(f"   {state_info['description']}")

        if substep and substep in substep_full:
            sub = substep_full[substep]
            msg_lines.append("")
            msg_lines.append(f"{sub['emoji']} {sub['step']}")
            msg_lines.append(f"   → {sub['desc']}")
            if sub.get("detail"):
                msg_lines.append(f"   💭 {sub['detail']}")

        if details and details.get("reason"):
            msg_lines.append(f"   🎯 Reason: {details['reason'].replace('_', ' ').title()}")

        if details:
            detail_items = [
                ("course_title", "📘 Course"),
                ("chapter_title", "📚 Chapter"),
                ("section_title", "🔖 Section"),
                ("slide_title", "🖼️ Slide"),
                ("question_text", "❓ Question"),
                ("transcription", "🎤 STT"),
                ("engine", "🛠️ Engine"),
                ("voice", "🎙️ Voice"),
                ("tts_engine", "🗣️ TTS Engine"),
                ("tts_voice", "🎙️ TTS Voice"),
                ("answer_preview", "💬 Answer"),
            ]
            for key, label in detail_items:
                value = details.get(key)
                if value is None:
                    continue
                value_text = str(value).strip()
                if not value_text:
                    continue
                if len(value_text) > 160:
                    value_text = value_text[:160].rstrip() + "…"
                msg_lines.append(f"   {label}: {value_text}")

        if metrics and len(metrics) > 0 and state == DialogState.RESPONDING:
            msg_lines.append("")
            msg_lines.append("📊 Complete Metrics:")

            if "elapsed" in metrics:
                msg_lines.append(f"   ⏱️  Elapsed: {metrics['elapsed']:.2f}s")
            if "total_time" in metrics:
                msg_lines.append(f"   ⏱️  Total: {metrics['total_time']:.2f}s")

            if "confidence" in metrics:
                conf = metrics["confidence"]
                bar = "▓" * int(conf * 10) + "░" * (10 - int(conf * 10))
                msg_lines.append(f"   🎯 Confidence: {bar} {conf:.0%}")

            if "speech_rate" in metrics:
                msg_lines.append(f"   🎤 Speech Rate: {metrics['speech_rate']:.0f} wpm")
            if "hesitations" in metrics:
                msg_lines.append(f"   💭 Hesitations: {metrics['hesitations']} found")
            if "language" in metrics:
                msg_lines.append(f"   🌍 Language: {metrics['language'].upper()}")

            if "chunks" in metrics:
                msg_lines.append(f"   📚 Documents: {metrics['chunks']} found")
            if "retrieval_time" in metrics:
                msg_lines.append(f"   🔍 Retrieval: {metrics['retrieval_time']:.3f}s")
            if "document_score" in metrics:
                msg_lines.append(f"   🎲 Top Score: {metrics['document_score']:.2f}/1.00")

            if "confusion_confidence" in metrics:
                conf = metrics["confusion_confidence"]
                msg_lines.append(f"   🤔 Confusion Level: {conf:.0%}")

            if "tokens" in metrics:
                msg_lines.append(f"   🔤 Tokens: {metrics['tokens']} generated")
            if "sentences" in metrics:
                msg_lines.append(f"   📝 Sentences: {metrics['sentences']}")
            if "words" in metrics:
                msg_lines.append(f"   📰 Words: {metrics['words']}")
            if "llm_time" in metrics:
                msg_lines.append(f"   🧠 LLM Time: {metrics['llm_time']:.2f}s")

            if "tts_chunks" in metrics:
                msg_lines.append(f"   🎙️  Audio Chunks: {metrics['tts_chunks']}")
            if "audio_duration" in metrics:
                msg_lines.append(f"   🔉 Audio Duration: {metrics['audio_duration']:.1f}s")

            if "progress" in metrics:
                prog = metrics["progress"]
                bar = "▓" * int(prog * 12) + "░" * (12 - int(prog * 12))
                msg_lines.append(f"   {bar} {prog:.0%}")

        display_message = "\n".join(msg_lines)

        try:
            record_trace_event({
                "session_id": session_id,
                "state": state.value,
                "state_name": state_name,
                "substep": substep,
                "display_message": display_message,
                "details": details or {},
                "metrics": metrics or {},
                "emoji": emoji,
                **({"turn_id": turn_id} if turn_id is not None else {}),
            })
        except Exception as trace_exc:
            log.debug(f"[{session_id[:8]}] trace event skipped: {trace_exc}")
        
        return await send({
            "type": "state_change",
            "state": state.value,
            "display_message": display_message,
            "substep": substep,
            "emoji": emoji,
            "state_name": state_name,
            "details": details or {},
            "metrics": metrics or {},
            "substep_full": substep_full,
            "timestamp": time.time(),
            **({"turn_id": turn_id} if turn_id is not None else {}),
        })

    async def cancel_text_question_task() -> None:
        nonlocal text_question_task, active_text_turn_id
        if text_question_task and not text_question_task.done():
            task = text_question_task
            task.cancel()

            def _log_done(done_task: asyncio.Task) -> None:
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    log.debug(f"[{session_id[:8]}] text question task cancel error: {exc}")

            task.add_done_callback(_log_done)
        text_question_task = None
        active_text_turn_id = 0

    async def process_text_question_turn(
        *,
        turn_id: int,
        content: str,
        lang: str,
        subj: str,
        chunks_with_scores: list,
        rag_time: float,
        avg_score: float,
        is_confused: bool,
        confusion_reason: str,
        question_for_llm: str,
        llm_start: float,
        question_ctx: SessionContext | None,
        presentation_cursor: int,
        current_chapter_title: str,
        current_section_title: str,
        current_chapter_idx: int | None,
        section_index_int: int | None,
    ) -> None:
        nonlocal text_question_task

        try:
            if turn_id != active_text_turn_id:
                return

            # âœ… STREAMING LLM WITH REAL-TIME METRICS
            ai_response = ""
            llm_confidence = 0.7
            chunk_count = 0
            tokens_generated = 0

            try:
                async for chunk_text, full_text in rag.generate_final_answer_stream(
                    chunks_with_scores,
                    question=question_for_llm,
                    history=history,
                    language=lang,
                    current_chapter_title=current_chapter_title,
                    current_section_title=current_section_title,
                ):
                    ai_response = full_text
                    chunk_count += 1
                    tokens_generated = len(ai_response.split())
                    elapsed_ms = (time.time() - llm_start) * 1000
                    tokens_per_sec = (tokens_generated / elapsed_ms * 1000) if elapsed_ms > 0 else 0

                    await send_state(
                        DialogState.PROCESSING,
                        "streaming_llm",
                        {"chunk": chunk_count, "text": chunk_text[:80]},
                        {
                            "tokens_generated": tokens_generated,
                            "tokens_per_sec": round(tokens_per_sec, 1),
                            "duration_ms": round(elapsed_ms, 1),
                            "progress_pct": 55 + min(chunk_count * 5, 20),
                        },
                        turn_id=turn_id,
                    )

            except Exception as rag_exc:
                log.warning(
                    f"[{session_id[:8]}] âš ï¸  RAG failed ({type(rag_exc).__name__}): {str(rag_exc)[:100]} â†’ Fallback brain.ask()..."
                )
                try:
                    ai_response, _ = await asyncio.to_thread(
                        brain.ask,
                        question_for_llm,
                        reply_language=lang,
                        session_id=session_id,
                    )
                    ai_response = brain._clean_for_speech(ai_response)
                    llm_confidence = 0.5
                except Exception as fallback_exc:
                    log.error(f"[{session_id[:8]}] âŒ Fallback also failed: {fallback_exc}")
                    ai_response = "Je suis dÃ©solÃ©, j'ai rencontrÃ© une erreur technique. Veuillez rÃ©essayer."
                    llm_confidence = 0.0

            llm_time = time.time() - llm_start

            if turn_id != active_text_turn_id:
                return

            history.append({"role": "user", "content": content})
            history.append({"role": "assistant", "content": ai_response})

            # âœ… UPDATE STATE: TTS Generation
            tts_start = time.time()
            num_chunks = max(1, len(ai_response) // 200)
            await send_state(
                DialogState.PROCESSING,
                "tts_text_chunking",
                {"chunks_total": num_chunks},
                {"progress_pct": 78},
                turn_id=turn_id,
            )

            audio_bytes, tts_time, tts_engine, tts_voice, mime = await voice.generate_audio_async(
                ai_response,
                language_code=lang,
            )

            await send_state(
                DialogState.PROCESSING,
                "tts_generation",
                {"engine": tts_engine, "voice": tts_voice},
                {
                    "audio_bytes": len(audio_bytes) if audio_bytes else 0,
                    "duration_ms": round(tts_time * 1000, 1),
                    "progress_pct": 90,
                },
                turn_id=turn_id,
            )

            if turn_id != active_text_turn_id:
                return

            if question_ctx:
                try:
                    await dialogue.transition(question_ctx.session_id, DialogState.RESPONDING)
                except ValueError:
                    return
            response_metrics = {
                "retrieval_time": round(rag_time / 1000.0, 3),
                "chunks": len(chunks_with_scores),
                "document_score": round(avg_score, 2),
                "llm_time": round(llm_time, 2),
                "tts_time": round(tts_time, 2),
                "total_time": round((rag_time / 1000.0) + llm_time + tts_time, 2),
                "tokens": tokens_generated,
                "words": len(ai_response.split()),
                "sentences": chunk_count,
                "confidence": round(llm_confidence, 2),
                "progress_pct": 95,
            }
            await send_state(
                DialogState.RESPONDING,
                "response_complete",
                {
                    "question_text": content,
                    "answer_preview": ai_response[:160],
                    "subject": subj,
                    "slide_title": current_section_title or current_chapter_title or "",
                    "chapter_title": current_chapter_title or "",
                    "section_title": current_section_title or "",
                    "tts_engine": tts_engine,
                    "tts_voice": tts_voice,
                },
                response_metrics,
                turn_id=turn_id,
            )

            log.info(f"[{session_id[:8]}] ≡ƒôñ Envoi answer_text: {len(ai_response)} chars | subj={subj}")
            await send({
                "type": "answer_text",
                "text": ai_response,
                "subject": subj,
                "rag_chunks": len(chunks_with_scores),
                "turn_id": turn_id,
            })
            log.info(f"[{session_id[:8]}] Γ£à answer_text envoy├⌐")

            if audio_bytes:
                await send({
                    "type": "audio_chunk",
                    "data": base64.b64encode(audio_bytes).decode(),
                    "mime": mime,
                    "final": True,
                    "turn_id": turn_id,
                })

            media_stamp = int(time.time() * 1000)
            transcript_payload = {
                "kind": "text_question",
                "session_id": session_id,
                "turn_id": turn_id,
                "question_text": content,
                "answer_text": ai_response,
                "language": lang,
                "subject": subj,
                "chapter_title": current_chapter_title or "",
                "section_title": current_section_title or "",
                "chapter_index": current_chapter_idx,
                "section_index": section_index_int,
                "char_position": presentation_cursor,
                "audio_answer_path": f"turns/answers/{session_id}/{turn_id}_{media_stamp}.{'mp3' if audio_bytes and 'mpeg' in (mime or '') else 'webm'}" if audio_bytes else "",
            }
            await save_media_json(f"turns/transcripts/{session_id}/{turn_id}_{media_stamp}.json", transcript_payload)
            if audio_bytes:
                answer_audio_object = transcript_payload["audio_answer_path"]
                await save_media_bytes(answer_audio_object, audio_bytes, mime or "audio/mpeg")

            if question_ctx:
                try:
                    await dialogue.transition(question_ctx.session_id, DialogState.LISTENING)
                except ValueError:
                    return
            await send_state(DialogState.LISTENING)

            if turn_id != active_text_turn_id:
                return

            # ΓöÇΓöÇ Analytics & Recherche ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
            try:
                transcript_searcher.index_interaction(
                    session_id=session_id,
                    student_q=content,
                    teacher_a=ai_response,
                    language=lang,
                    course_id="",
                    subject=subj,
                )
                analytics_engine.record_interaction(
                    session_id=session_id,
                    question=content,
                    answer=ai_response,
                    stt_time=0,
                    llm_time=llm_time,
                    tts_time=tts_time,
                    language=lang,
                    subject=subj,
                )
                try:
                    text_profile = await profile_mgr.update_from_interaction(
                        session_id,
                        "qa",
                        topic=(current_section_title or current_chapter_title or subj or ""),
                        confused=is_confused,
                        response_time=rag_time / 1000.0 + llm_time + tts_time,
                        confidence=0.85 if not is_confused else 0.35,
                        reward=1.0 if not is_confused else 0.0,
                        action_taken="reformulate" if is_confused else "answer",
                    )
                    if text_profile:
                        student_profile.update(text_profile.to_dict())

                    await persist_learning_turn(
                        event_type="qa",
                        question_text=content,
                        answer_text=ai_response,
                        language=lang,
                        subject=subj or current_section_title or current_chapter_title or "",
                        course_id_value=course_id or (question_ctx.course_id if question_ctx and question_ctx.course_id else None),
                        confusion_detected=is_confused,
                        confusion_reason=confusion_reason,
                        action_taken="reformulate" if is_confused else "answer",
                        reward=1.0 if not is_confused else 0.0,
                        stt_time=0.0,
                        llm_time=llm_time,
                        tts_time=tts_time,
                        total_time=rag_time / 1000.0 + llm_time + tts_time,
                        profile_snapshot=text_profile.to_dict() if text_profile else {},
                        concept=current_section_title or current_chapter_title or subj or "",
                        chapter_index=current_chapter_idx,
                        section_index=section_index_int,
                        char_position=presentation_cursor,
                        extra_payload={
                            "source": "text",
                            "rag_chunks": len(chunks_with_scores),
                            "confidence": llm_confidence,
                        },
                    )
                except Exception as learning_exc:
                    log.debug(f"[{session_id[:8]}] Text learning log skipped: {learning_exc}")

                record_session_event({
                    "session_id": session_id,
                    "language": lang,
                    "question": content,
                    "stt_text": content,
                    "answer": ai_response,
                    "turn_id": turn_id,
                    "stt_time": 0.0,
                    "llm_time": round(llm_time, 2),
                    "tts_time": round(tts_time, 2),
                    "total_time": round(llm_time + tts_time, 2),
                    "meets_kpi": (llm_time + tts_time) < 5.0,
                    "subject": subj,
                    "confusion": is_confused,
                    "confusion_reason": confusion_reason,
                    "source": "text",
                    "slide_title": current_section_title or current_chapter_title or "",
                    "chapter_title": current_chapter_title or "",
                    "section_title": current_section_title or "",
                    "tts_engine": tts_engine,
                    "tts_voice": tts_voice,
                    "chapter_index": current_chapter_idx,
                    "section_index": section_index_int,
                    "char_position": presentation_cursor,
                })
            except Exception as _ae:
                log.debug("analytics error: %s", _ae)
        finally:
            if asyncio.current_task() is text_question_task:
                text_question_task = None

    async def process_quiz_request(
        *,
        quiz_topic: str,
        lang: str,
        subj: str,
        chunks_with_scores: list,
        question_ctx: SessionContext | None,
        presentation_cursor: int,
        current_chapter_title: str,
        current_section_title: str,
        current_chapter_idx: int | None,
        section_index_int: int | None,
        course_id: str,
        course_title: str,
        course_domain: str,
        slide_path: str,
    ) -> None:
        quiz_topic = (quiz_topic or current_section_title or current_chapter_title or course_title or "Quiz").strip()
        try:
            await cancel_text_question_task()
            await cancel_audio_stream(notify_client=False)
            await cancel_presentation_task(notify_client=False)

            if question_ctx:
                try:
                    await dialogue.transition(question_ctx.session_id, DialogState.PROCESSING)
                except ValueError:
                    pass

            await send_state(
                DialogState.PROCESSING,
                "quiz_preparing",
                {
                    "type": "quiz",
                    "quiz_topic": quiz_topic,
                    "chapter_title": current_chapter_title or "",
                    "section_title": current_section_title or "",
                },
                {
                    "progress_pct": 25,
                    "quiz_topic": quiz_topic,
                },
            )

            quiz_llm_start = time.time()
            quiz_payload, quiz_confidence = await asyncio.to_thread(
                rag.generate_quiz,
                chunks_with_scores,
                question=quiz_topic,
                history=[],
                language=lang,
                student_level=session_level,
                current_chapter_title=current_chapter_title,
                current_section_title=current_section_title,
                question_count=3,
            )

            quiz_llm_time = time.time() - quiz_llm_start

            if not isinstance(quiz_payload, dict):
                quiz_payload = {}

            quiz_payload.setdefault("title", "Quiz rapide")
            quiz_payload.setdefault("topic", quiz_topic)
            quiz_payload.setdefault("difficulty", session_level)
            quiz_payload.setdefault("language", lang)
            quiz_payload.setdefault("chapter_title", current_chapter_title or "")
            quiz_payload.setdefault("section_title", current_section_title or "")
            quiz_payload.setdefault("course_title", course_title or "")
            quiz_payload.setdefault("course_domain", course_domain or "")
            quiz_payload.setdefault("slide_title", current_section_title or current_chapter_title or "")
            quiz_payload.setdefault("slide_path", slide_path or "")

            questions = quiz_payload.get("questions") if isinstance(quiz_payload.get("questions"), list) else []
            quiz_payload["question_count"] = len(questions)
            quiz_payload["confidence"] = round(float(quiz_confidence or 0.0), 3)

            await send({
                "type": "quiz_prompt",
                "question": quiz_payload.get("title") or quiz_payload.get("topic") or quiz_topic,
                "quiz": quiz_payload,
                "chapter_title": current_chapter_title or "",
                "section_title": current_section_title or "",
                "course_id": course_id or "",
                "course_title": course_title or "",
                "course_domain": course_domain or "",
                "language": lang,
                "level": session_level,
                "confidence": quiz_payload["confidence"],
            })

            if question_ctx:
                try:
                    await dialogue.transition(question_ctx.session_id, DialogState.LISTENING)
                except ValueError:
                    return

            await send_state(
                DialogState.LISTENING,
                details={
                    "quiz_topic": quiz_payload.get("topic") or quiz_topic,
                    "quiz_questions": quiz_payload.get("question_count", 0),
                    "chapter_title": current_chapter_title or "",
                    "section_title": current_section_title or "",
                },
            )

            try:
                quiz_profile = await profile_mgr.update_from_interaction(
                    session_id,
                    "quiz",
                    topic=quiz_payload.get("topic") or current_section_title or current_chapter_title or subj or "",
                    confused=False,
                    response_time=quiz_llm_time,
                    confidence=None,
                    reward=0.0,
                    action_taken="quiz",
                )
                if quiz_profile:
                    student_profile.update(quiz_profile.to_dict())

                await persist_learning_turn(
                    event_type="quiz",
                    question_text=quiz_topic,
                    answer_text=f"{quiz_payload.get('title', 'Quiz rapide')} ({quiz_payload.get('question_count', 0)} questions)",
                    language=lang,
                    subject=subj or current_section_title or current_chapter_title or "",
                    course_id_value=course_id or (question_ctx.course_id if question_ctx and question_ctx.course_id else None),
                    confusion_detected=False,
                    action_taken="quiz",
                    reward=0.0,
                    stt_time=0.0,
                    llm_time=quiz_llm_time,
                    tts_time=0.0,
                    total_time=quiz_llm_time,
                    profile_snapshot=quiz_profile.to_dict() if quiz_profile else {},
                    concept=current_section_title or current_chapter_title or subj or "",
                    chapter_index=current_chapter_idx,
                    section_index=section_index_int,
                    char_position=presentation_cursor,
                    extra_payload={
                        "source": "quiz",
                        "quiz": quiz_payload,
                        "quiz_confidence": round(float(quiz_confidence or 0.0), 3),
                    },
                    session_state=DialogState.LISTENING.value,
                )
            except Exception as quiz_log_exc:
                log.debug(f"[{session_id[:8]}] Quiz learning log skipped: {quiz_log_exc}")

            record_session_event({
                "session_id": session_id,
                "language": lang,
                "question": quiz_topic,
                "stt_text": quiz_topic,
                "answer": quiz_payload.get("title", "Quiz rapide"),
                "turn_id": None,
                "stt_time": 0.0,
                "llm_time": round(quiz_llm_time, 2),
                "tts_time": 0.0,
                "total_time": round(quiz_llm_time, 2),
                "meets_kpi": quiz_llm_time < 5.0,
                "subject": subj,
                "confusion": False,
                "confusion_reason": "",
                "source": "quiz",
                "slide_title": current_section_title or current_chapter_title or "",
                "chapter_title": current_chapter_title or "",
                "section_title": current_section_title or "",
                "chapter_index": current_chapter_idx,
                "section_index": section_index_int,
                "char_position": presentation_cursor,
                "quiz_questions": quiz_payload.get("question_count", 0),
            })

            try:
                analytics_engine.record_section(
                    session_id,
                    course_id or "",
                    current_chapter_idx or 0,
                    section_index_int or 0,
                    event_type="quiz",
                    language=lang,
                )
            except Exception as analytics_exc:
                log.debug(f"[{session_id[:8]}] Quiz analytics skipped: {analytics_exc}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"Erreur quiz: {e}")
            await send({"type": "error", "message": f"Erreur quiz: {str(e)}"})

    async def set_listening_state() -> None:
        """
        Transition SÃ‰CURISÃ‰E vers LISTENING avec gestion de la machine d'Ã©tat.
        
        âœ… Si en LISTENING: pas de transition nÃ©cessaire
        âœ… Si en PROCESSING: passer par CLARIFICATION d'abord (transition valide)
        âœ… Si dans autre Ã©tat: transition directe
        """
        nonlocal ctx
        
        if not ctx:
            return
        
        current_state = ctx.state
        
        # âœ… DÃ©jÃ  en LISTENING: rien Ã  faire
        if current_state == DialogState.LISTENING.value:
            return
        
        # âœ… Si en PROCESSING: passer par CLARIFICATION (transition valide: PROCESSING â†’ CLARIFICATION)
        if current_state == DialogState.PROCESSING.value:
            log.info(f"[{session_id[:8]}] ðŸ”„ PROCESSING â†’ CLARIFICATION â†’ LISTENING (transition sÃ©curisÃ©e)")
            await dialogue.transition(ctx.session_id, DialogState.CLARIFICATION)
            await send_state(DialogState.CLARIFICATION)
            await send({"type": "message", "text": "Je n'ai rien entendu. Peux-tu rÃ©pÃ©ter?"})
        
        # âœ… Si en PRESENTING: annuler d'abord la prÃ©sentation
        if current_state == DialogState.PRESENTING.value:
            log.info(f"[{session_id[:8]}] ðŸ›‘ PRESENTING â†’ LISTENING (annulation prÃ©sentation)")
            await cancel_presentation_task(notify_client=False)
        
        # âœ… Maintenant transition sÃ©curisÃ©e vers LISTENING
        ctx = await dialogue.get_session(ctx.session_id) or ctx
        if ctx.state != DialogState.LISTENING.value:
            await dialogue.transition(ctx.session_id, DialogState.LISTENING)
        
        await send_state(DialogState.LISTENING)

    def _safe_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
        if value is None or value == "":
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except Exception:
            return None

    async def persist_learning_turn(
        *,
        event_type: str,
        question_text: str,
        answer_text: str,
        language: str,
        subject: str = "",
        course_id_value: str | uuid.UUID | None = None,
        confusion_detected: bool = False,
        confusion_reason: str = "",
        action_taken: str = "answer",
        reward: float = 0.0,
        stt_time: float = 0.0,
        llm_time: float = 0.0,
        tts_time: float = 0.0,
        total_time: float = 0.0,
        profile_snapshot: dict | None = None,
        concept: str = "",
        chapter_index: int | None = None,
        section_index: int | None = None,
        char_position: int | None = None,
        extra_payload: dict | None = None,
        session_state: str = DialogState.LISTENING.value,
    ) -> None:
        """Persist a turn in PostgreSQL so we can train later from real usage."""
        nonlocal learning_session_db_id

        if learning_session_db_id is None:
            return

        course_uuid = _safe_uuid(course_id_value)
        if course_uuid is None and ctx and ctx.course_id:
            course_uuid = _safe_uuid(ctx.course_id)

        try:
            async with AsyncSessionLocal() as db:
                await log_interaction(
                    db=db,
                    session_id=learning_session_db_id,
                    student_id=session_id,
                    course_id=course_uuid,
                    interaction_type=event_type,
                    question=question_text,
                    answer=answer_text,
                    language=language,
                    stt_time=stt_time,
                    llm_time=llm_time,
                    tts_time=tts_time,
                    total_time=total_time,
                    kpi_ok=1 if total_time <= Config.MAX_RESPONSE_TIME else 0,
                )
                await log_learning_event(
                    db=db,
                    session_id=learning_session_db_id,
                    student_id=session_id,
                    course_id=course_uuid,
                    event_type=event_type,
                    input_text=question_text,
                    output_text=answer_text,
                    concept=concept or subject or None,
                    action_taken=action_taken,
                    confusion_score=1.0 if confusion_detected else 0.0,
                    reward=reward,
                    stt_time=stt_time,
                    llm_time=llm_time,
                    tts_time=tts_time,
                    total_time=total_time,
                    student_state=profile_snapshot or {},
                    event_payload={
                        "subject": subject,
                        "language": language,
                        "confusion_reason": confusion_reason,
                        "chapter_index": chapter_index,
                        "section_index": section_index,
                        "char_position": char_position,
                        **(extra_payload or {}),
                    },
                )
                await update_session_state(
                    db,
                    learning_session_db_id,
                    session_state,
                    chapter_index=chapter_index,
                    section_index=section_index,
                    char_position=char_position,
                )
        except Exception as exc:
            log.debug(f"[{session_id[:8]}] Learning event persistence skipped: {exc}")

    def _format_presentation_point() -> tuple[str, str, int]:
        chapter_no = (ctx.chapter_index + 1) if ctx else 0
        section_no = (ctx.section_index + 1) if ctx else 0

        location_bits: list[str] = []
        if chapter_no:
            location_bits.append(f"chapitre {chapter_no}")
        if section_no:
            location_bits.append(f"section {section_no}")

        location_label = ", ".join(location_bits) if location_bits else "point courant"
        total_chars = len(current_presentation_text or "")
        cursor_label = f"{current_presentation_cursor}/{total_chars}" if total_chars else str(current_presentation_cursor)
        return location_label, cursor_label, total_chars

    async def record_pause_point(reason: str, notice_prefix: str = "â¸ Point d'arrÃªt mÃ©morisÃ©") -> str:
        nonlocal ctx

        if not ctx:
            return ""

        location_label, cursor_label, total_chars = _format_presentation_point()
        slide_id = ":".join(str(part) for part in current_presentation_key) if current_presentation_key else None

        try:
            paused_ctx = await dialogue.pause_session(
                ctx.session_id,
                slide_id=slide_id,
                char_offset=current_presentation_cursor,
                presentation_text=current_presentation_text or None,
                presentation_cursor=current_presentation_cursor,
                presentation_key=slide_id,
                slide_title=current_section_title or current_chapter_title or "",
            )
            if paused_ctx:
                ctx = paused_ctx
        except Exception as pause_exc:
            log.debug(f"[{session_id[:8]}] pause_session skipped: {pause_exc}")

        point_text = f"{notice_prefix} â€” {location_label}, position {cursor_label}. Narration gardÃ©e en cache."
        record_checkpoint_event({
            "session_id": session_id,
            "language": session_lang,
            "subject": (ctx.course_analysis.get("course_domain", "") if ctx and ctx.course_analysis else ""),
            "checkpoint_type": "pause",
            "point_text": point_text,
            "location_label": location_label,
            "cursor_label": cursor_label,
            "slide_id": slide_id,
            "slide_title": current_section_title or current_chapter_title or "",
            "chapter_index": ctx.chapter_index if ctx else None,
            "section_index": ctx.section_index if ctx else None,
            "char_position": current_presentation_cursor,
            "reason": reason,
            "source": "checkpoint",
        })
        await send({"type": "system_notice", "text": point_text})

        try:
            await persist_learning_turn(
                event_type="pause",
                question_text="",
                answer_text="",
                language=session_lang,
                subject=(ctx.course_analysis.get("course_domain", "") if ctx and ctx.course_analysis else ""),
                course_id_value=ctx.course_id if ctx else None,
                confusion_detected=False,
                confusion_reason=reason,
                action_taken="pause",
                reward=0.0,
                stt_time=0.0,
                llm_time=0.0,
                tts_time=0.0,
                total_time=0.0,
                profile_snapshot=student_profile.copy(),
                concept=ctx.last_slide_explained if ctx else "",
                chapter_index=ctx.chapter_index if ctx else None,
                section_index=ctx.section_index if ctx else None,
                char_position=current_presentation_cursor,
                extra_payload={
                    "reason": reason,
                    "point_text": point_text,
                    "slide_id": slide_id,
                    "cursor_label": cursor_label,
                    "total_chars": total_chars,
                },
                session_state=DialogState.WAITING.value,
            )
        except Exception as learning_exc:
            log.debug(f"[{session_id[:8]}] Pause learning log skipped: {learning_exc}")

        return point_text

    async def cancel_next_slide_prefetch() -> None:
        nonlocal next_slide_prefetch_task
        if next_slide_prefetch_task and not next_slide_prefetch_task.done():
            next_slide_prefetch_task.cancel()
            try:
                await next_slide_prefetch_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.debug(f"[{session_id[:8]}] next slide prefetch cancel error: {exc}")
        next_slide_prefetch_task = None

    async def warm_presentation_audio_cache(narration_text: str, language_code: str, rate: str) -> None:
        if not narration_text.strip():
            return

        for sentence, _, _ in split_sentences_with_spans(narration_text):
            if not sentence.strip():
                continue
            try:
                await synthesize_cached_tts(
                    sentence,
                    language_code=language_code,
                    rate=rate,
                    cache_scope="prefetch",
                )
            except Exception as cache_exc:
                log.debug(f"[{session_id[:8]}] Prefetch TTS skipped: {cache_exc}")

    async def prefetch_next_slide(
        current_slide_key: tuple[str, int, int],
        course_id_value: str,
        chapter_index_value: int,
        section_index_value: int,
        language_code: str,
        student_level_value: str,
        course_summary_value: str,
        rate_value: str,
        current_slide_title: str,
    ) -> None:
        if not course_id_value:
            return

        next_candidates = [
            (chapter_index_value, section_index_value + 1),
            (chapter_index_value + 1, 0),
        ]

        next_slide_ctx = None
        next_chapter_index = None
        next_section_index = None

        for candidate_chapter, candidate_section in next_candidates:
            if candidate_chapter < 0 or candidate_section < 0:
                continue
            next_slide_ctx = await load_course_slide_context(
                course_id_value,
                candidate_chapter,
                candidate_section,
            )
            if next_slide_ctx:
                next_chapter_index = candidate_chapter
                next_section_index = candidate_section
                break

        if not next_slide_ctx or next_chapter_index is None or next_section_index is None:
            return

        next_slide_id = f"{course_id_value}:{next_chapter_index}:{next_section_index}"

        if current_presentation_key != current_slide_key:
            return

        cached_snapshot = await dialogue.load_presentation_snapshot(session_id, next_slide_id)
        next_narration_text = (cached_snapshot or {}).get("presentation_text") or ""
        next_cursor = int((cached_snapshot or {}).get("presentation_cursor") or 0)

        if not next_narration_text:
            next_narration_text = await explain_slide_focused(
                slide_content=next_slide_ctx.get("content") or "",
                chapter_idx=next_chapter_index,
                chapter_title=next_slide_ctx.get("chapter_title") or "",
                section_title=next_slide_ctx.get("section_title") or "",
                language=language_code,
                student_level=student_level_value,
                course_summary=course_summary_value,
                is_resume=False,
                session_id=session_id,
            )
            next_narration_text = next_narration_text.strip()
            next_cursor = 0

        if not next_narration_text or current_presentation_key != current_slide_key:
            return

        await dialogue.save_presentation_snapshot(
            session_id,
            next_slide_id,
            next_narration_text,
            presentation_cursor=next_cursor,
            slide_title=next_slide_ctx.get("section_title") or next_slide_ctx.get("chapter_title") or current_slide_title,
        )

        await warm_presentation_audio_cache(next_narration_text, language_code, rate_value)

        log.info(
            f"[{session_id[:8]}] âœ… Next slide prefetched | key={next_slide_id} | chars={len(next_narration_text)}"
        )

    async def schedule_next_slide_prefetch(
        *,
        current_slide_key: tuple[str, int, int],
        course_id_value: str,
        chapter_index_value: int,
        section_index_value: int,
        language_code: str,
        student_level_value: str,
        course_summary_value: str,
        rate_value: str,
        current_slide_title: str,
    ) -> None:
        nonlocal next_slide_prefetch_task

        await cancel_next_slide_prefetch()

        async def runner() -> None:
            nonlocal next_slide_prefetch_task
            try:
                await prefetch_next_slide(
                    current_slide_key=current_slide_key,
                    course_id_value=course_id_value,
                    chapter_index_value=chapter_index_value,
                    section_index_value=section_index_value,
                    language_code=language_code,
                    student_level_value=student_level_value,
                    course_summary_value=course_summary_value,
                    rate_value=rate_value,
                    current_slide_title=current_slide_title,
                )
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.debug(f"[{session_id[:8]}] next slide prefetch failed: {exc}")
            finally:
                if asyncio.current_task() is next_slide_prefetch_task:
                    next_slide_prefetch_task = None

        next_slide_prefetch_task = asyncio.create_task(runner())

    async def synthesize_cached_tts(
        text_to_speak: str,
        *,
        language_code: str,
        rate: str = "+0%",
        cache_scope: str = "presentation",
    ) -> tuple[bytes | None, float, str, str, str | None, bool]:
        """Generate TTS once and reuse cached audio for repeated phrases."""
        if not text_to_speak or not text_to_speak.strip():
            return None, 0.0, "none", "none", None, False

        cache_signatures = []
        try:
            cache_signatures = voice.get_cache_signatures(language_code)
        except Exception:
            cache_signatures = []

        if not cache_signatures:
            request_provider = getattr(voice, "provider", "edge") or "edge"
            request_voice_name = getattr(voice, "voice_name", None) or getattr(voice, "voice_id", "none") or "none"
            cache_signatures = [(request_provider, request_voice_name)]

        cached = None
        for request_provider, request_voice_name in cache_signatures:
            try:
                cached = await dialogue.load_tts_phrase_cache(
                    text_to_speak,
                    language=language_code,
                    rate=rate,
                    provider=request_provider,
                    voice_name=request_voice_name,
                )
            except Exception as cache_exc:
                log.debug(f"[{session_id[:8]}] TTS cache lookup skipped: {cache_exc}")
                cached = None
            if cached and cached.get("audio_bytes"):
                break

        if cached and cached.get("audio_bytes"):
            log.info(
                f"[{session_id[:8]}] â™»ï¸ TTS cache hit | scope={cache_scope} | "
                f"provider={cached.get('provider')} | voice={cached.get('voice_name')}"
            )
            return (
                cached.get("audio_bytes"),
                0.0,
                cached.get("provider") or request_provider,
                cached.get("voice_name") or request_voice_name,
                cached.get("mime"),
                True,
            )

        audio_bytes, duration_s, engine_name, voice_name, mime_type = await voice.generate_audio_async(
            text_to_speak,
            language_code=language_code,
            rate=rate,
        )

        if audio_bytes:
            try:
                cache_targets = list(cache_signatures)
                cache_targets.append((engine_name or cache_signatures[0][0], voice_name or cache_signatures[0][1]))
                seen_targets: set[tuple[str, str]] = set()
                for provider_name, voice_label in cache_targets:
                    target = (provider_name, voice_label)
                    if target in seen_targets:
                        continue
                    seen_targets.add(target)
                    await dialogue.save_tts_phrase_cache(
                        text_to_speak,
                        audio_bytes,
                        language=language_code,
                        rate=rate,
                        provider=provider_name,
                        voice_name=voice_label,
                        mime=mime_type or "audio/mpeg",
                        metadata={
                            "scope": cache_scope,
                            "engine": engine_name,
                            "voice_name": voice_name,
                            "request_signatures": cache_signatures,
                        },
                    )
            except Exception as cache_exc:
                log.debug(f"[{session_id[:8]}] TTS cache save skipped: {cache_exc}")

        return audio_bytes, duration_s, engine_name, voice_name, mime_type, False

    async def _stream_audio(audio_bytes: bytes, mime: str | None, stream_id: int) -> None:
        chunk_size = 4096
        total_len = len(audio_bytes)
        for i in range(0, total_len, chunk_size):
            chunk = audio_bytes[i:i + chunk_size]
            if not await send({
                "type":      "audio_chunk",
                "stream_id": stream_id,
                "data":      base64.b64encode(chunk).decode(),
                "mime":      mime,
                "final":     (i + chunk_size) >= total_len,
            }):
                return
            # Laisse la boucle Ã©vÃ©nementielle respirer entre chunks
            await asyncio.sleep(0)

    async def cancel_audio_stream(notify_client: bool = False, turn_id: int | None = None) -> None:
        nonlocal audio_stream_task
        if audio_stream_task and not audio_stream_task.done():
            audio_stream_task.cancel()
            try:
                await audio_stream_task
            except asyncio.CancelledError:
                pass
        audio_stream_task = None
        if notify_client:
            payload = {"type": "audio_interrupted", "stream_id": current_stream_id}
            if turn_id is not None:
                payload["turn_id"] = turn_id
            await send(payload)

    async def start_audio_stream(
        audio_bytes: bytes | None,
        mime: str | None,
        auto_listening: bool = True,
    ) -> None:
        nonlocal audio_stream_task, current_stream_id
        await cancel_audio_stream(notify_client=False)

        if not audio_bytes:
            if auto_listening:
                await set_listening_state()
            return

        current_stream_id += 1
        stream_id = current_stream_id

        async def runner() -> None:
            nonlocal audio_stream_task
            try:
                await _stream_audio(audio_bytes, mime, stream_id)
                if auto_listening and not websocket_closed:
                    await set_listening_state()
            except asyncio.CancelledError:
                pass
            except Exception as stream_exc:
                log.error(f"[{session_id[:8]}] audio stream error: {stream_exc}")
            finally:
                if asyncio.current_task() is audio_stream_task:
                    audio_stream_task = None

        audio_stream_task = asyncio.create_task(runner())

    def split_sentences_with_spans(text: str) -> list[tuple[str, int, int]]:
        import re

        spans: list[tuple[str, int, int]] = []
        for match in re.finditer(r"[^.!?]+(?:[.!?]+|\Z)", text, flags=re.S):
            raw = match.group()
            sentence = raw.strip()
            if not sentence:
                continue
            left_trim = len(raw) - len(raw.lstrip())
            right_trim = len(raw.rstrip())
            spans.append((sentence, match.start() + left_trim, match.start() + right_trim))

        if not spans and text.strip():
            stripped = text.strip()
            start = text.find(stripped)
            spans.append((stripped, max(0, start), max(0, start) + len(stripped)))

        return spans

    async def cancel_presentation_task(notify_client: bool = False) -> None:
        nonlocal presentation_task
        if presentation_task and not presentation_task.done():
            presentation_task.cancel()
            try:
                await presentation_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.debug(f"[{session_id[:8]}] presentation task cancel error: {exc}")
        presentation_task = None
        if notify_client:
            await send({"type": "audio_interrupted", "stream_id": current_stream_id})

    async def explain_slide_focused(
        slide_content: str,
        chapter_idx: int,
        chapter_title: str,
        section_title: str = "",
        language: str = "fr",
        student_level: str = "lycÃ©e",
        course_summary: str = "",  # âœ… NOUVEAU: contexte du cours entier
        is_resume: bool = False,   # âœ… NOUVEAU: dÃ©tecter pause/reprise
        session_id: str | None = None,  # âœ… For rate limiting
    ) -> str:
        """
        Expliquer un slide de maniÃ¨re PRÃ‰CISE.
        Focus UNIQUEMENT sur la slide actuelle.
        
        Args:
            slide_content: Contenu EXACT de la slide
            chapter_idx: Index du chapitre
            chapter_title: Titre du chapitre
            section_title: Titre de la section
            language: fr/en
            student_level: collÃ¨ge/lycÃ©e/licence/master/doctorat
            course_summary: RÃ©sumÃ© du cours entier (contexte global)
            is_resume: True si pause/reprise (ne pas redÃ©marrer depuis dÃ©but)
        """
        try:
            # âœ… NO RAG! JUSTE la slide actuelle + positionnement
            position_info = f"Chapitre {chapter_idx + 1}: {chapter_title}"
            if section_title:
                position_info += f" â†’ Section: {section_title}"
            
            # âœ… Contexte global du cours (pour cohÃ©rence)
            course_context = course_summary or position_info
            
            # âœ… Adapter le ton selon le niveau
            level_instruction = {
                "collÃ¨ge": "Explique trÃ¨s simplement, avec des exemples concrets et accessibles. Ã‰vite la terminologie complexe.",
                "lycÃ©e": "Sois clair et structurÃ©. Utilise la terminologie exacte mais reste accessible.",
                "licence": "Sois technique et prÃ©cis. Utilise la terminologie universitaire. Cite les concepts clÃ©s.",
                "master": "Utilise un langage technique avancÃ©. Analyse critique. RÃ©fÃ©rences thÃ©oriques attendues.",
                "doctorat": "Analyse approfondie avec terminologie spÃ©cialisÃ©e. Enjeux de recherche. Nuances critiques.",
            }
            level_hint = level_instruction.get(student_level, level_instruction["lycÃ©e"])
            
            # âœ… Prompt ULTRA STRICT anti-hallucination (TRÃˆS IMPORTANT)
            if language == "fr":
                if is_resume:
                    # ðŸ”„ Mode REPRISE : ne pas redÃ©marrer depuis le dÃ©but
                    prompt_mode = """ATTENTION: Cette slide a DÃ‰JÃ€ Ã©tÃ© expliquÃ©e.
NE RECOMMENCE PAS L'EXPLICATION.
Continues oÃ¹ tu t'Ã©tais arrÃªtÃ© ou propose des dÃ©tails supplÃ©mentaires."""
                else:
                    prompt_mode = ""
                
                system_prompt = f"""Tu es Smart Teacher, expert pÃ©dagogue.

**RÃˆGLES ABSOLUES (non-nÃ©gociable)**:

1. âŒ JAMAIS parler de :
   - Chapitres futurs
   - Sujets "qui viennent aprÃ¨s"
   - "nous verrons...", "ensuite...", "dans la suite..."
   - Connaissances hors du cours

2. âœ… SEULEMENT :
   - Contenu de CETTE slide
   - Ce qui est en cours

3. ðŸš« Si tu ne sais pas :
   - NE PAS inventer
   - Dis: "Ce dÃ©tail n'est pas expliquÃ©"

**CONTEXTE COURS**:
{course_context}

**AUDIENCE**: {student_level}

{prompt_mode}

**SLIDE Ã€ EXPLIQUER**:
{slide_content}

Explique Ã§a naturellement. MAX 4 phrases."""

            else:  # English
                if is_resume:
                    prompt_mode = """ATTENTION: This slide was already explained.
DO NOT restart.
Continue from where you stopped or add extra details."""
                else:
                    prompt_mode = ""
                
                system_prompt = f"""You are Smart Teacher, expert educator.

**ABSOLUTE RULES (non-negotiable)**:

1. âŒ NEVER mention:
   - Future chapters
   - Topics "that come next"
   - "we will see...", "later...", "next in the course..."
   - Knowledge outside the course

2. âœ… ONLY:
   - This CURRENT slide content
   - What is being taught right now

3. ðŸš« If you don't know:
   - DO NOT invent
   - Say: "This detail is not explained"

**COURSE CONTEXT**:
{course_context}

**AUDIENCE**: {student_level}

{prompt_mode}

**SLIDE TO EXPLAIN**:
{slide_content}

Explain naturally. MAX 4 sentences."""

            # âœ… LLM call direct (pas de RAG, juste la slide)
            response, duration = await asyncio.to_thread(
                brain.ask,
                question=slide_content[:100],  # Juste premiÃ¨re partie pour rÃ©fÃ©rence
                course_context=slide_content,  # La slide EST le contexte
                reply_language=language,
                chapter_idx=chapter_idx,
                chapter_title=chapter_title,
                section_title=section_title,
                domain=None,
                session_id=session_id,  # âœ… Pass session_id for rate limiting
            )
            
            log.info(f"âœ… LLM focused response ({duration:.1f}s) | {len(response)} chars")
            return response
            
        except Exception as e:
            log.error(f"âŒ Error in explain_slide_focused: {e}")
            return f"Erreur lors de l'explication : {str(e)}"

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")

            # â”€â”€ start_session â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if msg_type == "start_session":
                # âœ… Flexible auth: Only validate if we have a token entry
                # - If session_id in SESSION_TOKENS: Validate token strictly (secure flow)
                # - Otherwise: Auto-approve unconditionally (legacy SDK)
                token = msg.get("token")
                
                if session_id in SESSION_TOKENS:
                    # Secure flow: We generated a token, so it must be provided and match
                    if not token or SESSION_TOKENS.get(session_id) != token:
                        await send({"type": "error", "message": "Authentication failed: invalid or missing token"})
                        await websocket.close(code=1008, reason="Unauthorized")
                        log.warning(f"[{session_id[:8]}] âŒ WebSocket auth failed (invalid token)")
                        return
                    # Token is valid - consume it (one-time use)
                    del SESSION_TOKENS[session_id]
                    log.info(f"[{session_id[:8]}] âœ… WebSocket authenticated (secure token)")
                else:
                    # Legacy flow: No token generated, so ignore any token and auto-approve
                    log.info(f"[{session_id[:8]}] âœ… WebSocket auto-approved (legacy SDK)")
                
                lang  = msg.get("language", "fr")
                level = msg.get("level",    "lycÃ©e")
                ctx   = await dialogue.create_session(
                    session_id=session_id,
                    language=lang,
                    student_level=level,
                    course_id=(msg.get("course_id") or None),
                )
                session_lang  = lang
                session_level = level
                history.clear()
                interrupt_audio = False  # ðŸŸ¢ RÃ©initialiser le flag
                await cancel_text_question_task()
                active_text_turn_id = 0
                text_turn_seq = 0

                try:
                    course_uuid = _safe_uuid(msg.get("course_id") or (ctx.course_id if ctx else None))
                    async with AsyncSessionLocal() as db:
                        learning_session = await create_learning_session(
                            db,
                            student_id=session_id,
                            course_id=course_uuid,
                            language=lang,
                            level=level,
                        )
                        await update_session_state(
                            db,
                            learning_session.id,
                            DialogState.LISTENING.value,
                            chapter_index=0,
                            section_index=0,
                            char_position=0,
                        )
                        await db.commit()
                        learning_session_db_id = learning_session.id
                except Exception as exc:
                    learning_session_db_id = None
                    log.warning(f"[{session_id[:8]}] âš ï¸ Learning session DB init failed: {exc}")

                await send({"type": "session_ready", "session_id": ctx.session_id})
                
                # âœ… NOUVEAU: Transition explicite IDLE â†’ LISTENING
                await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                await send_state(DialogState.LISTENING)
                log.info(f"[{session_id[:8]}] ðŸš€ Session dÃ©marrÃ©e | lang={lang} level={level} state=LISTENING")

            # â”€â”€ audio_chunk â€” accumule les donnÃ©es audio â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            elif msg_type == "audio_chunk":
                raw = msg.get("data", "")
                turn_id = int(msg.get("turn_id") or 0)
                if raw:
                    try:
                        decoded = base64.b64decode(raw)
                        log.info(f"   ðŸ“¦ Audio chunk: base64_len={len(raw)} â†’ {len(decoded)} bytes")
                        # âœ… REFRESH ctx (peut Ãªtre modifiÃ© par run_presentation)
                        if ctx:
                            ctx = await dialogue.get_session(session_id) or ctx
                        
                        if ctx and ctx.state in [DialogState.RESPONDING.value, DialogState.PRESENTING.value]:
                            log.info(f"[{session_id[:8]}] Interruption vocale detectee")
                            interrupt_audio = True
                            
                            # âœ… NOUVEAU: DÃ©terminer si interruption est TRÃˆS PRÃ‰COCE (avant streaming)
                            time_since_presenting = time.time() - presentation_start_time if presentation_start_time > 0 else 999
                            if ctx.state == DialogState.PRESENTING.value and time_since_presenting < 1.0:
                                log.info(f"[{session_id[:8]}] âš¡ TRÃˆS TÃ”T interruption ({time_since_presenting:.2f}s aprÃ¨s PRESENTING) â†’ annuler prÃ©paration")
                            
                            # âœ… CRUCIAL: Sauvegarder le point AVANT d'annuler
                            await record_pause_point("voice_interrupt", notice_prefix="â¸ Point d'arrÃªt mÃ©morisÃ© (voix)")
                            
                            # âœ… Annuler la prÃ©sentation EN COURS pour Ã©viter conflit
                            await cancel_presentation_task(notify_client=True)
                            await cancel_audio_stream(notify_client=True, turn_id=turn_id)
                            await cancel_text_question_task()
                            await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                            await send_state(DialogState.LISTENING, turn_id=turn_id)
                        audio_buffer.append(decoded)
                    except Exception as e:
                        log.error(f"âŒ Failed to decode audio chunk: {e}")

            # â”€â”€ audio_end â€” traite l'audio accumulÃ© â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            elif msg_type == "audio_end":
                interrupt_audio = False
                turn_id = int(msg.get("turn_id") or 0)
                
                # âœ… REFRESH ctx FROM REDIS (peut Ãªtre modifiÃ© par run_presentation en tÃ¢che async)
                if not ctx:
                    ctx = await dialogue.get_session(session_id)
                else:
                    ctx = await dialogue.get_session(session_id) or ctx
                
                # âœ… SÃ‰CURITÃ‰: Ne jamais traiter audio_end sans session active
                if not ctx:
                    await send({"type": "error", "message": "Aucune session active (dÃ©marrez avec start_session)", "turn_id": turn_id})
                    continue
                
                # âœ… SÃ‰CURITÃ‰: Bloquer transition IDLE â†’ PROCESSING (mais LISTENING OK!)
                if ctx.state == DialogState.IDLE.value:
                    log.warning(f"[{session_id[:8]}] âš ï¸ Tentative audio_end en IDLE â†’ ignorÃ© (jamais IDLE â†’ PROCESSING)")
                    await send({"type": "error", "message": "Session en IDLE, dÃ©marrage nÃ©cessaire", "turn_id": turn_id})
                    continue
                
                if not audio_buffer:
                    await send({"type": "error", "message": "Aucun audio reÃ§u", "turn_id": turn_id})
                    continue
                await cancel_audio_stream(notify_client=False)

                # Assembler et convertir l'audio
                full_audio = b"".join(audio_buffer)
                log.info(f"[{session_id[:8]}] ðŸŽ™ï¸ Audio buffer assembled: {len(audio_buffer)} chunks = {len(full_audio)} total bytes")
                audio_buffer.clear()

                media_stamp = int(time.time() * 1000)
                question_audio_object = f"turns/questions/{session_id}/{turn_id}_{media_stamp}.webm"
                await save_media_bytes(question_audio_object, full_audio, "audio/webm")

                try:
                    audio_np = audio_bytes_to_numpy(full_audio)
                except RuntimeError as exc:
                    await send({"type": "error", "message": str(exc), "turn_id": turn_id})
                    continue

                # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                # ðŸŽ¤ SILERO VAD: Filter audio with backend voice detection (PyTorch)
                # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                log.info(f"[{session_id[:8]}] ðŸŽ¤ Silero VAD: Filtering {len(audio_np)} samples...")
                
                # Break audio into CHUNK_SIZE chunks (512 samples @ 16kHz = 32ms)
                chunk_size = Config.CHUNK_SIZE
                vad_confidence_scores = []
                filtered_chunks = []
                
                for i in range(0, len(audio_np), chunk_size):
                    chunk = audio_np[i:i + chunk_size]
                    
                    # Pad chunk if last one is shorter
                    if len(chunk) < chunk_size:
                        chunk = np.pad(chunk, (0, chunk_size - len(chunk)), mode='constant', constant_values=0.0)
                    
                    # Get speech probability (0.0 = silence, 1.0 = definitely speech)
                    prob = audio_input.get_speech_probability(chunk.astype(np.float32))
                    vad_confidence_scores.append(prob)
                    
                    # Keep chunk if confidence > threshold (0.5 = medium confidence)
                    if prob > Config.SPEECH_THRESHOLD:
                        filtered_chunks.append(chunk[:len(audio_np[i:i + chunk_size])])
                
                # Concatenate filtered chunks
                if filtered_chunks:
                    audio_np = np.concatenate(filtered_chunks)
                    avg_confidence = np.mean(vad_confidence_scores)
                    log.info(
                        f"[{session_id[:8]}] âœ… Silero VAD: "
                        f"Kept {len(filtered_chunks)} / {len(vad_confidence_scores)} chunks, "
                        f"avg_confidence={avg_confidence:.2f}, "
                        f"audio_len {len(audio_np)} samples"
                    )
                else:
                    # No speech detected - send a neutral notice
                    log.info(f"[{session_id[:8]}] â„¹ï¸ Silero VAD: No speech detected (all chunks < threshold)")
                    await send({
                        "type": "system_notice",
                        "text": "Aucune voix dÃ©tectÃ©e.",
                        "turn_id": turn_id,
                    })
                    await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                    await send_state(DialogState.LISTENING, turn_id=turn_id)
                    continue

                # Transition â†’ PROCESSING (sÃ©curisÃ©e via state machine)
                await dialogue.transition(ctx.session_id, DialogState.PROCESSING)
                await send_state(DialogState.PROCESSING, turn_id=turn_id)

                # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                # ðŸš€ STREAMING PIPELINE: Real-time LLM â†’ TTS
                # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
                
                current_stream_id += 1
                stream_id = current_stream_id
                turn_id = int(msg.get("turn_id") or 0)
                response_audio_parts: list[bytes] = []
                response_audio_mime = ""
                
                async def on_text_chunk(sentence: str, full_response: str):
                    chunk_text = (full_response or sentence or "").strip()
                    if not chunk_text:
                        return
                    if not await send({
                        "type": "answer_text",
                        "text": chunk_text,
                        "turn_id": turn_id,
                        "partial": True,
                        "final": False,
                    }):
                        return

                async def on_transcription(text: str, lang: str, confidence: float):
                    await send_state(
                        DialogState.PROCESSING,
                        "stt_transcription",
                        {
                            "transcription": text,
                            "language": lang,
                            "confidence": confidence,
                            "slide_title": current_section_title or current_chapter_title or "",
                            "chapter_title": current_chapter_title or "",
                            "section_title": current_section_title or "",
                        },
                        {"progress_pct": 12, "confidence": confidence},
                        turn_id=turn_id,
                    )
                    if not await send({
                        "type": "transcription",
                        "text": text,
                        "lang": lang,
                        "confidence": confidence,
                        "turn_id": turn_id,
                    }):
                        log.warning(f"[{session_id[:8]}] âš ï¸ Transcription non envoyÃ©e")
                
                async def on_state_change(substep: str, details: dict = None):
                    """âœ… NOUVEAU: Callback pour les mises Ã  jour d'Ã©tat de la pipeline"""
                    return await send_state(
                        DialogState.PROCESSING,
                        substep=substep,
                        details=details or {},
                        turn_id=turn_id,
                    )
                
                async def on_audio_chunk(audio_bytes: bytes, mime: str):
                    """Stream each sentence's audio as it's generated"""
                    nonlocal interrupt_audio, response_audio_mime
                    if audio_bytes:
                        response_audio_parts.append(audio_bytes)
                        if mime:
                            response_audio_mime = mime
                        chunk_size = 4096
                        total_len = len(audio_bytes)
                        for i in range(0, total_len, chunk_size):
                            # ðŸš¨ VÃ©rifier le flag d'interruption EN TEMPS RÃ‰EL
                            if interrupt_audio:
                                log.info(f"[{session_id[:8]}] ðŸ›‘ Audio interruption dÃ©tectÃ©e â†’ STOP streaming")
                                return
                            
                            chunk = audio_bytes[i:i + chunk_size]
                            if not await send({
                                "type":      "audio_chunk",
                                "stream_id": stream_id,
                                "turn_id":   turn_id,
                                "data":      base64.b64encode(chunk).decode(),
                                "mime":      mime,
                                "final":     (i + chunk_size) >= total_len,
                            }):
                                return
                            await asyncio.sleep(0)  # yield control
                
                try:
                    # Launch streaming pipeline with course language to force STT detection
                    course_lang = ctx.course_analysis.get("language") if ctx and ctx.course_analysis else None
                    course_id_for_rag = ctx.course_id if ctx else None  # âœ… Pass course_id from session context
                    result = await run_pipeline_streaming(
                        audio_np, session_id, history,
                        on_text_chunk=on_text_chunk,
                        on_transcription=on_transcription,
                        on_audio_chunk=on_audio_chunk,
                        on_state_change=on_state_change,  # âœ… NOUVEAU: State updates
                        force_language=course_lang,
                        course_id=course_id_for_rag,  # âœ… Scoped RAG retrieval
                        ctx=ctx,
                        # âœ… Inject dependencies
                        transcriber=transcriber,
                        rag=rag,
                        voice=voice,
                        brain=brain,
                        dialogue=dialogue,
                        csv_logger=csv_logger,
                        stt_logger=stt_logger,
                    )

                    if result.get("no_speech"):
                        await send({
                            "type": "system_notice",
                            "text": result.get("message", "Aucune voix dÃ©tectÃ©e."),
                            "turn_id": turn_id,
                        })
                        await save_media_json(
                            f"turns/transcripts/{session_id}/{turn_id}_{media_stamp}.json",
                            {
                                "kind": "audio_question",
                                "session_id": session_id,
                                "turn_id": turn_id,
                                "question_audio_path": question_audio_object,
                                "question_text": result.get("transcription", {}).get("text", ""),
                                "answer_text": "",
                                "language": result.get("transcription", {}).get("language", session_lang),
                                "subject": result.get("subject", ""),
                                "audio_answer_path": "",
                                "note": result.get("message", "Aucune voix dÃ©tectÃ©e."),
                            },
                        )
                        await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                        await send_state(DialogState.LISTENING, turn_id=turn_id)
                        continue

                    if "error" in result:
                        # âœ… Quand STT Ã©choue: passer par CLARIFICATION (transition valide depuis PROCESSING)
                        await send({"type": "error", "message": result["error"], "turn_id": turn_id})
                        await save_media_json(
                            f"turns/transcripts/{session_id}/{turn_id}_{media_stamp}.json",
                            {
                                "kind": "audio_question",
                                "session_id": session_id,
                                "turn_id": turn_id,
                                "question_audio_path": question_audio_object,
                                "question_text": result.get("transcription", {}).get("text", ""),
                                "answer_text": "",
                                "language": result.get("transcription", {}).get("language", session_lang),
                                "subject": result.get("subject", ""),
                                "audio_answer_path": "",
                                "error": result["error"],
                            },
                        )
                        try:
                            await persist_learning_turn(
                                event_type="error",
                                question_text=result.get("transcription", {}).get("text", ""),
                                answer_text="",
                                language=result.get("transcription", {}).get("language", session_lang),
                                subject=result.get("subject", ""),
                                course_id_value=course_id_for_rag,
                                confusion_detected=bool(result.get("confusion", {}).get("detected", False)),
                                confusion_reason=result.get("confusion", {}).get("reason", ""),
                                action_taken="error",
                                reward=0.0,
                                stt_time=float(result.get("performance", {}).get("stt_time", 0.0)),
                                llm_time=float(result.get("performance", {}).get("llm_time", 0.0)),
                                tts_time=float(result.get("performance", {}).get("tts_time", 0.0)),
                                total_time=float(result.get("performance", {}).get("total_time", 0.0)),
                                profile_snapshot=student_profile.copy(),
                                concept=ctx.last_slide_explained if ctx else "",
                                chapter_index=ctx.chapter_index if ctx else None,
                                section_index=ctx.section_index if ctx else None,
                                char_position=current_presentation_cursor if ctx else None,
                                extra_payload={
                                    "source": "streaming_error",
                                    "message": result["error"],
                                },
                            )
                        except Exception as learning_exc:
                            log.debug(f"[{session_id[:8]}] Error learning log skipped: {learning_exc}")
                        record_session_event({
                            "session_id": session_id,
                            "language": result.get("transcription", {}).get("language", session_lang),
                            "question": result.get("transcription", {}).get("text", ""),
                            "stt_text": result.get("transcription", {}).get("text", ""),
                            "answer": "",
                            "turn_id": turn_id,
                            "stt_time": float(result.get("performance", {}).get("stt_time", 0.0)),
                            "llm_time": float(result.get("performance", {}).get("llm_time", 0.0)),
                            "tts_time": float(result.get("performance", {}).get("tts_time", 0.0)),
                            "total_time": float(result.get("performance", {}).get("total_time", 0.0)),
                            "meets_kpi": False,
                            "subject": result.get("subject", ""),
                            "confusion": bool(result.get("confusion", {}).get("detected", False)),
                            "confusion_reason": result.get("confusion", {}).get("reason", ""),
                            "source": "streaming_error",
                            "slide_title": current_section_title or current_chapter_title or "",
                            "chapter_title": current_chapter_title or "",
                            "section_title": current_section_title or "",
                            "tts_engine": result.get("tts_engine", ""),
                            "tts_voice": result.get("tts_voice", ""),
                            "chapter_index": ctx.chapter_index if ctx else None,
                            "section_index": ctx.section_index if ctx else None,
                            "char_position": current_presentation_cursor if ctx else None,
                        })
                        if ctx:
                            await dialogue.transition(ctx.session_id, DialogState.CLARIFICATION)
                        await send_state(DialogState.CLARIFICATION, turn_id=turn_id)
                        # Puis revenir Ã  LISTENING via set_listening_state()
                        ctx = await dialogue.get_session(session_id) or ctx  # âœ… Refresh ctx
                        await set_listening_state()
                        continue

                    # Transition â†’ RESPONDING (now streaming)
                    if ctx:
                        await dialogue.transition(ctx.session_id, DialogState.RESPONDING)
                    await send_state(
                        DialogState.RESPONDING,
                        turn_id=turn_id,
                        details={
                            "question_text": result.get("transcription", {}).get("text", ""),
                            "answer_preview": result.get("answer", "")[:160],
                            "subject": result.get("subject", ""),
                            "slide_title": current_section_title or current_chapter_title or "",
                            "chapter_title": current_chapter_title or "",
                            "section_title": current_section_title or "",
                            "tts_engine": result.get("tts_engine", ""),
                            "tts_voice": result.get("tts_voice", ""),
                        },
                    )

                    # Send final full answer text
                    if not await send({"type": "answer_text", "text": result["answer"],
                                "subject": result["subject"], "rag_chunks": result["rag_chunks"], "turn_id": turn_id,
                                "partial": False, "final": True}):
                        continue

                    # Send performance metrics
                    if not await send({"type": "performance", "turn_id": turn_id, **result["performance"]}):
                        continue

                    answer_audio_object = f"turns/answers/{session_id}/{turn_id}_{media_stamp}.{'mp3' if 'mpeg' in (response_audio_mime or '') else 'webm'}"
                    transcript_payload = {
                        "kind": "audio_question",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "question_audio_path": question_audio_object,
                        "question_text": result.get("transcription", {}).get("text", ""),
                        "answer_text": result.get("answer", ""),
                        "language": result.get("transcription", {}).get("language", session_lang),
                        "subject": result.get("subject", ""),
                        "chapter_title": current_chapter_title or "",
                        "section_title": current_section_title or "",
                        "chapter_index": ctx.chapter_index if ctx else None,
                        "section_index": ctx.section_index if ctx else None,
                        "char_position": current_presentation_cursor if ctx else None,
                        "audio_answer_path": answer_audio_object if response_audio_parts else "",
                    }
                    await save_media_json(f"turns/transcripts/{session_id}/{turn_id}_{media_stamp}.json", transcript_payload)
                    if response_audio_parts:
                        await save_media_bytes(answer_audio_object, b"".join(response_audio_parts), response_audio_mime or "audio/mpeg")

                    try:
                        confusion_detected = bool(result.get("confusion", {}).get("detected", False))
                        total_turn_time = float(result["performance"].get("total_time", 0.0))
                        stream_profile = await profile_mgr.update_from_interaction(
                            session_id,
                            "qa",
                            topic=(result.get("subject") or ""),
                            confused=confusion_detected,
                            response_time=total_turn_time,
                            confidence=0.85 if not confusion_detected else 0.35,
                            reward=1.0 if (not confusion_detected and result["performance"].get("kpi_ok", False)) else 0.0,
                            action_taken="reformulate" if confusion_detected else "answer",
                        )
                        if stream_profile:
                            student_profile.update(stream_profile.to_dict())

                        await persist_learning_turn(
                            event_type="qa",
                            question_text=result.get("transcription", {}).get("text", ""),
                            answer_text=result.get("answer", ""),
                            language=result.get("transcription", {}).get("language", session_lang),
                            subject=result.get("subject", ""),
                            course_id_value=course_id_for_rag,
                            confusion_detected=confusion_detected,
                            confusion_reason=result.get("confusion", {}).get("reason", ""),
                            action_taken="reformulate" if confusion_detected else "answer",
                            reward=1.0 if (not confusion_detected and result["performance"].get("kpi_ok", False)) else 0.0,
                            stt_time=float(result["performance"].get("stt_time", 0.0)),
                            llm_time=float(result["performance"].get("llm_time", 0.0)),
                            tts_time=float(result["performance"].get("tts_time", 0.0)),
                            total_time=total_turn_time,
                            profile_snapshot=stream_profile.to_dict() if stream_profile else {},
                            concept=result.get("subject", ""),
                            chapter_index=ctx.chapter_index if ctx else None,
                            section_index=ctx.section_index if ctx else None,
                            char_position=current_presentation_cursor if ctx else None,
                            extra_payload={
                                "source": "streaming",
                                "rag_chunks": result.get("rag_chunks", 0),
                                "confusion_reason": result.get("confusion", {}).get("reason", ""),
                            },
                        )
                    except Exception as learning_exc:
                        log.debug(f"[{session_id[:8]}] Streaming learning log skipped: {learning_exc}")
                    record_session_event({
                        "session_id": session_id,
                        "language": result.get("transcription", {}).get("language", session_lang),
                        "question": result.get("transcription", {}).get("text", ""),
                        "stt_text": result.get("transcription", {}).get("text", ""),
                        "answer": result.get("answer", ""),
                        "turn_id": turn_id,
                        "stt_time": float(result["performance"].get("stt_time", 0.0)),
                        "llm_time": float(result["performance"].get("llm_time", 0.0)),
                        "tts_time": float(result["performance"].get("tts_time", 0.0)),
                        "total_time": float(result["performance"].get("total_time", 0.0)),
                        "meets_kpi": bool(result["performance"].get("kpi_ok", False)),
                        "subject": result.get("subject", ""),
                        "confusion": confusion_detected,
                        "confusion_reason": result.get("confusion", {}).get("reason", ""),
                        "source": "streaming",
                        "slide_title": current_section_title or current_chapter_title or "",
                        "chapter_title": current_chapter_title or "",
                        "section_title": current_section_title or "",
                        "tts_engine": result.get("tts_engine", ""),
                        "tts_voice": result.get("tts_voice", ""),
                        "chapter_index": ctx.chapter_index if ctx else None,
                        "section_index": ctx.section_index if ctx else None,
                        "char_position": current_presentation_cursor if ctx else None,
                    })

                    await send_state(
                        DialogState.RESPONDING,
                        "response_complete",
                        {
                            "question_text": result.get("transcription", {}).get("text", ""),
                            "answer_preview": result.get("answer", "")[:160],
                            "subject": result.get("subject", ""),
                            "slide_title": current_section_title or current_chapter_title or "",
                            "chapter_title": current_chapter_title or "",
                            "section_title": current_section_title or "",
                            "tts_engine": result.get("tts_engine", ""),
                            "tts_voice": result.get("tts_voice", ""),
                        },
                        result.get("performance", {}),
                        turn_id=turn_id,
                    )
                    
                    # Signal stream completion
                    if not await send({"type": "audio_stream_end", "stream_id": stream_id, "turn_id": turn_id}):
                        continue

                    # âœ… CRITICAL: Attendre interruption ou auto-avancer
                    await asyncio.sleep(0.5)  # Petit pause aprÃ¨s TTS
                    
                    user_interrupted = await handle_post_response(timeout_sec=2.5)
                    
                    if user_interrupted:
                        # âœ… Utilisateur a posÃ© une question â†’ Ã©couter
                        log.info(f"ðŸ’¬ [{session_id[:8]}] Student asked a question")
                        # State est dÃ©jÃ  LISTENING (detectable par VAD)
                    else:
                        # âœ… Pas de question â†’ auto-avancer PRÃ‰SENTATION
                        log.info(f"â­ï¸  [{session_id[:8]}] Auto-advancing to next slide")
                        if ctx:
                            await dialogue.transition(ctx.session_id, DialogState.PRESENTING)
                        await send({"type": "next_section", "turn_id": turn_id})
                        # Laisser le client gÃ©rer le chargement du slide suivant

                except Exception as pipeline_exc:
                    log.error(f"[{session_id[:8]}] Pipeline streaming error: {pipeline_exc}", exc_info=True)
                    await send({"type": "error", "message": f"Pipeline error: {str(pipeline_exc)[:100]}", "turn_id": turn_id})
                    await send_state(DialogState.LISTENING, turn_id=turn_id)

            # â”€â”€ interrupt â€” l'Ã©tudiant coupe l'IA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            elif msg_type == "interrupt":
                interrupt_reason = str(msg.get("reason") or "question").strip().lower() or "question"
                turn_id = int(msg.get("turn_id") or 0)
                await record_pause_point(interrupt_reason, notice_prefix="â¸ Point d'arrÃªt mÃ©morisÃ©")
                await cancel_presentation_task(notify_client=True)
                audio_buffer.clear()
                await cancel_audio_stream(notify_client=True, turn_id=turn_id)
                await cancel_text_question_task()
                if ctx and interrupt_reason != "pause":
                    await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                    await send_state(DialogState.LISTENING, turn_id=turn_id)
                elif ctx:
                    await send_state(DialogState.WAITING, turn_id=turn_id)
                else:
                    await set_listening_state()
                log.info(f"[{session_id[:8]}] âš¡ Interruption")

            # â”€â”€ present_section â€” prÃ©senter une section de cours â”€â”€â”€â”€â”€
            elif msg_type == "present_section":
                content_txt = (msg.get("slide_content") or msg.get("content") or "").strip()
                presentation_request_id = str(msg.get("presentation_request_id") or "").strip()
                slide_title = msg.get("slide_title", "")
                slide_content = msg.get("slide_content", "")
                keywords = msg.get("keywords", [])
                chapter = msg.get("chapter", "")
                section_title = msg.get("section_title", "")
                progress_pct = msg.get("progress_pct", 0)
                lang_ps = msg.get("language", session_lang)
                course_id = str(msg.get("course_id") or (ctx.course_id if ctx and ctx.course_id else "") or "").strip()
                course_title = msg.get("course_title", "")
                course_domain = msg.get("course_domain", "general")
                chapter_index_raw = msg.get("chapter_index")
                section_index_raw = msg.get("section_index")
                slide_index_raw = msg.get("slide_index")
                slide_path = str(msg.get("slide_path") or msg.get("image_url") or "").strip()
                slide_type = msg.get("slide_type", "section")
                in_course = True

                try:
                    chapter_index_int = int(chapter_index_raw) if chapter_index_raw is not None else 0
                except (TypeError, ValueError):
                    chapter_index_int = 0
                try:
                    section_index_int = int(section_index_raw) if section_index_raw is not None else 0
                except (TypeError, ValueError):
                    section_index_int = 0
                try:
                    slide_index_int = int(slide_index_raw) if slide_index_raw is not None else 0
                except (TypeError, ValueError):
                    slide_index_int = 0

                slide_ctx = None
                if course_id:
                    slide_ctx = await load_course_slide_context(course_id, chapter_index_int, section_index_int)
                if slide_ctx:
                    content_txt = (slide_ctx.get("content") or content_txt).strip()
                    slide_title = slide_ctx.get("section_title") or slide_title
                    slide_content = slide_ctx.get("content") or slide_content
                    keywords = slide_ctx.get("keywords") or keywords
                    chapter = slide_ctx.get("chapter_title") or chapter
                    section_title = slide_ctx.get("section_title") or section_title
                    course_title = slide_ctx.get("course_title") or course_title
                    course_domain = slide_ctx.get("course_domain") or course_domain
                    slide_path = slide_ctx.get("slide_path") or slide_path
                    slide_type = slide_ctx.get("slide_type") or slide_type
                    slide_index_int = int(slide_ctx.get("slide_index") or slide_index_int)
                    progress_pct = slide_ctx.get("progress_pct") if slide_ctx.get("progress_pct") is not None else progress_pct

                if not content_txt:
                    continue

                await cancel_presentation_task(notify_client=False)
                await cancel_audio_stream(notify_client=False)

                if ctx:
                    # âœ… Stocker le course_summary pour utilisation dans explain_slide_focused
                    if slide_ctx and slide_ctx.get("course_summary"):
                        ctx.course_summary = slide_ctx["course_summary"]
                        ctx.course_analysis = slide_ctx.get("course_analysis", {})
                    
                    await dialogue.save_course_position(
                        ctx.session_id,
                        course_id=course_id or None,
                        chapter_index=chapter_index_int,
                        section_index=section_index_int,
                        char_pos=0,
                    )
                    await dialogue.transition(ctx.session_id, DialogState.PRESENTING)
                presentation_details = {
                    "course_title": course_title or "",
                    "chapter_title": chapter or "",
                    "section_title": section_title or "",
                    "slide_title": section_title or chapter or "",
                    "slide_index": slide_index_int,
                    "progress_pct": progress_pct,
                }
                await send_state(DialogState.PRESENTING, details=presentation_details)

                requested_slide_key = (course_id or "", chapter_index_int, section_index_int)
                requested_slide_id = ":".join(str(part) for part in requested_slide_key)
                cached_snapshot = None
                if ctx:
                    try:
                        cached_snapshot = await dialogue.load_presentation_snapshot(ctx.session_id, requested_slide_id)
                    except Exception as cache_exc:
                        log.debug(f"[{session_id[:8]}] Presentation cache lookup skipped: {cache_exc}")
                cached_pause_state = ctx.paused_state if ctx else {}
                cached_slide_id = str(
                    cached_pause_state.get("presentation_key")
                    or cached_pause_state.get("slide_id")
                    or ""
                )
                cached_presentation_text = (cached_snapshot or {}).get("presentation_text") or cached_pause_state.get("presentation_text") or ""
                cached_presentation_cursor = int(
                    (cached_snapshot or {}).get("presentation_cursor")
                    or cached_pause_state.get("presentation_cursor")
                    or cached_pause_state.get("char_offset")
                    or 0
                )

                reuse_cached_narration = (
                    current_presentation_key == requested_slide_key
                    and bool(current_presentation_text)
                ) or (
                    bool(cached_presentation_text) and cached_slide_id == requested_slide_id
                )

                if reuse_cached_narration:
                    if not current_presentation_text and cached_presentation_text and cached_slide_id == requested_slide_id:
                        current_presentation_text = cached_presentation_text
                        current_presentation_cursor = min(
                            max(0, cached_presentation_cursor),
                            len(current_presentation_text),
                        )
                else:
                    current_presentation_text = ""
                    current_presentation_cursor = 0
                current_presentation_key = requested_slide_key
                resume_offset = current_presentation_cursor if reuse_cached_narration else 0

                # Envoyer la slide immÃ©diatement avec ses mÃ©tadonnÃ©es exactes.
                if not await send({
                    "type": "slide_update",
                    "presentation_request_id": presentation_request_id,
                    "slide_type": slide_type,
                    "slide_index": slide_index_int,
                    "slide_title": slide_title or content_txt[:60],
                    "slide_content": slide_content or content_txt[:200],
                    "content_original": content_txt,
                    "image_url": slide_path,
                    "slide_path": slide_path,
                    "keywords": keywords,
                    "chapter": chapter,
                    "chapter_index": chapter_index_int,
                    "section_index": section_index_int,
                    "section_title": section_title,
                    "course_id": course_id,
                    "course_title": course_title,
                    "course_domain": course_domain,
                    "progress_pct": progress_pct,
                }):
                    continue

                # Profil Ã©tudiant â†’ adapter le dÃ©bit (TODO: implement speech rate customization)
                try:
                    profile = await profile_mgr.get_or_create(session_id, lang_ps, session_level)
                    # âœ… Stocker profil pour timing adaptatif
                    student_profile.update({
                        "confusion_count": profile.confusion_count,
                        "asks_repeat": profile.asks_repeat,
                    })
                    # TODO: Implement speech rate adaptation via TTS engine
                    # For now, using default speech rate
                    rate_override = "+0%"
                except Exception:
                    rate_override = "+0%"

                async def run_presentation(
                    section_text: str,
                    resume_from: int,
                    reuse_cached: bool,
                ) -> None:
                    nonlocal current_stream_id, current_presentation_text, current_presentation_cursor, presentation_task
                    try:
                        narration_text = current_presentation_text if reuse_cached and current_presentation_text else ""
                        if not narration_text:
                            llm_start = time.time()
                            await send_state(
                                DialogState.PRESENTING,
                                "llm_thinking",
                                {"type": "presentation", **presentation_details},
                                {"progress_pct": 20},
                            )
                            try:
                                # âœ… DÃ©terminer si c'est une reprise (pause/resume)
                                is_resuming = resume_offset > 0 and reuse_cached

                                # âœ… RÃ©cupÃ©rer le course_summary depuis le contexte session
                                course_summary = ctx.course_summary if ctx else ""

                                # âœ… NOUVEAU: Utiliser explain_slide_focused (strict + focused + level-adapted)
                                narration_text = await explain_slide_focused(
                                    slide_content=section_text or slide_content or content_txt,
                                    chapter_idx=chapter_index_int,
                                    chapter_title=chapter,
                                    section_title=section_title,
                                    language=lang_ps,
                                    student_level=session_level,
                                    course_summary=course_summary,  # âœ… NOUVEAU
                                    is_resume=is_resuming,  # âœ… NOUVEAU
                                    session_id=session_id,  # âœ… Pass session_id for rate limiting
                                )
                            except Exception:
                                # Fallback: brain.ask
                                narration_text, _ = await asyncio.to_thread(
                                    brain.ask,
                                    section_text or content_txt,
                                    reply_language=lang_ps,
                                    session_id=session_id,
                                )  # âœ… Pass session_id
                                narration_text = brain._clean_for_speech(narration_text)
                            narration_text = narration_text.strip()
                            current_presentation_text = narration_text
                            llm_time = time.time() - llm_start
                            if ctx and requested_slide_id:
                                try:
                                    await dialogue.save_presentation_snapshot(
                                        ctx.session_id,
                                        requested_slide_id,
                                        narration_text,
                                        presentation_cursor=resume_from,
                                        slide_title=section_title or chapter or "",
                                    )
                                except Exception as cache_exc:
                                    log.debug(f"[{session_id[:8]}] Presentation snapshot save skipped: {cache_exc}")

                            await schedule_next_slide_prefetch(
                                current_slide_key=requested_slide_key,
                                course_id_value=course_id or "",
                                chapter_index_value=chapter_index_int,
                                section_index_value=section_index_int,
                                language_code=lang_ps,
                                student_level_value=session_level,
                                course_summary_value=ctx.course_summary if ctx else "",
                                rate_value=rate_override,
                                current_slide_title=section_title or chapter or "",
                            )
                            await send_state(
                                DialogState.PRESENTING,
                                "tts_generating",
                                {"engine": "presentation", **presentation_details},
                                {
                                    "llm_time": round(llm_time, 2),
                                    "tokens": len(narration_text.split()),
                                    "progress_pct": 55,
                                },
                            )
                        else:
                            llm_time = 0.0

                        if not narration_text:
                            if await send({"type": "stream_end", "stream_id": current_stream_id}):
                                await set_listening_state()
                            return

                        effective_resume = resume_from if 0 <= resume_from < len(narration_text) else 0
                        remaining_text = narration_text[effective_resume:]
                        if not remaining_text.strip():
                            current_presentation_cursor = len(narration_text)
                            if ctx:
                                await dialogue.save_position(ctx.session_id, current_presentation_cursor)
                            if not await send({"type": "answer_text", "text": narration_text, "subject": "course", "presentation_request_id": presentation_request_id, "final": True}):
                                return
                            if not await send({"type": "stream_end", "stream_id": current_stream_id}):
                                return
                            await set_listening_state()
                            return

                        current_stream_id += 1
                        stream_id = current_stream_id
                        sentences = split_sentences_with_spans(remaining_text)
                        tts_total_time = 0.0
                        await send_state(
                            DialogState.PRESENTING,
                            "tts_streaming",
                            {"chunks": len(sentences), **presentation_details},
                            {
                                "tts_chunks": len(sentences),
                                "progress_pct": 70,
                            },
                        )
                        for sentence, start, end in sentences:
                            if not sentence.strip():
                                continue

                            if not await send({"type": "answer_text", "text": sentence, "subject": "course", "presentation_request_id": presentation_request_id, "partial": True}):
                                return

                            audio_chunk = None
                            tts_piece_time = 0.0
                            mime = None
                            try:
                                audio_chunk, tts_piece_time, _, _, mime, _cache_hit = await synthesize_cached_tts(
                                    sentence,
                                    language_code=lang_ps,
                                    rate=rate_override,
                                    cache_scope="presentation",
                                )
                            except TypeError:
                                audio_chunk, tts_piece_time, _, _, mime, _cache_hit = await synthesize_cached_tts(
                                    sentence,
                                    language_code=lang_ps,
                                    rate="+0%",
                                    cache_scope="presentation",
                                )

                            tts_total_time += tts_piece_time or 0.0

                            if audio_chunk:
                                await _stream_audio(audio_chunk, mime, stream_id)

                            current_presentation_cursor = min(len(narration_text), effective_resume + end)
                            if ctx:
                                await dialogue.save_position(ctx.session_id, current_presentation_cursor)

                            if ctx and requested_slide_id:
                                try:
                                    await dialogue.save_presentation_snapshot(
                                        ctx.session_id,
                                        requested_slide_id,
                                        narration_text,
                                        presentation_cursor=current_presentation_cursor,
                                        slide_title=section_title or chapter or "",
                                    )
                                except Exception as cache_exc:
                                    log.debug(f"[{session_id[:8]}] Presentation snapshot refresh skipped: {cache_exc}")

                            await asyncio.sleep(0)

                        current_presentation_cursor = len(narration_text)
                        if ctx:
                            await dialogue.save_position(ctx.session_id, current_presentation_cursor)

                        if ctx and requested_slide_id:
                            try:
                                await dialogue.save_presentation_snapshot(
                                    ctx.session_id,
                                    requested_slide_id,
                                    narration_text,
                                    presentation_cursor=current_presentation_cursor,
                                    slide_title=section_title or chapter or "",
                                )
                            except Exception as cache_exc:
                                log.debug(f"[{session_id[:8]}] Presentation snapshot final save skipped: {cache_exc}")

                        await send_state(
                            DialogState.PRESENTING,
                            "response_complete",
                            presentation_details,
                            {
                                "llm_time": round(llm_time, 2),
                                "tts_time": round(tts_total_time, 2),
                                "total_time": round(llm_time + tts_total_time, 2),
                                "tokens": len(narration_text.split()),
                                "words": len(narration_text.split()),
                                "sentences": len(sentences),
                                "progress_pct": 95,
                            },
                        )

                        if not await send({"type": "answer_text", "text": narration_text, "subject": "course", "presentation_request_id": presentation_request_id, "final": True}):
                            return
                        if not await send({"type": "stream_end", "stream_id": stream_id}):
                            return
                        await set_listening_state()
                    except asyncio.CancelledError:
                        if ctx:
                            try:
                                await dialogue.save_position(ctx.session_id, current_presentation_cursor)
                            except Exception:
                                pass
                        raise
                    except Exception as e:
                        log.error(f"Erreur prÃ©sentation streaming: {e}")
                        await send({"type": "error", "message": f"Erreur prÃ©sentation: {str(e)}"})
                    finally:
                        nonlocal_presentation_task = presentation_task
                        if nonlocal_presentation_task is asyncio.current_task():
                            presentation_task = None

                # âœ… NOUVEAU: Enregistrer le moment oÃ¹ la prÃ©sentation COMMENCE
                presentation_start_time = time.time()
                presentation_task = asyncio.create_task(
                    run_presentation(content_txt, resume_offset, reuse_cached_narration)
                )

            # â”€â”€ text â€” question texte (depuis l'input HTML) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            elif msg_type == "text":
                # âœ… REFRESH ctx (peut Ãªtre modifiÃ© par run_presentation)
                if ctx:
                    ctx = await dialogue.get_session(session_id) or ctx
                
                content = msg.get("content", "").strip()
                if not content:
                    continue
                await cancel_audio_stream(notify_client=False)

                content_lower = " ".join(content.lower().split()).strip(" .!?,:;")
                resume_triggers = (
                    "continue",
                    "continuer",
                    "reprendre",
                    "reprends",
                    "reprise",
                    "poursuis",
                    "poursuivre",
                    "go on",
                    "resume",
                    "on continue",
                    "continue le cours",
                    "continuer le cours",
                    "reprendre le cours",
                    "reprends le cours",
                    "on reprend",
                    "reprenons",
                )
                quiz_triggers = (
                    "quiz",
                    "quiz me",
                    "quiz moi",
                    "quiz-moi",
                    "quizz",
                    "test me",
                    "teste-moi",
                    "teste moi",
                    "donne-moi un quiz",
                    "donne moi un quiz",
                    "fais-moi un quiz",
                    "fais moi un quiz",
                    "interroge-moi",
                    "interroge moi",
                )
                quiz_phrase_triggers = (
                    "can do quiz",
                    "do a quiz",
                    "do quiz",
                    "make a quiz",
                    "create a quiz",
                    "generate a quiz",
                    "give me a quiz",
                    "quiz about this course",
                    "quiz on this course",
                    "quiz on the course",
                    "test me on this course",
                    "test me on the course",
                    "can you quiz",
                    "quiz me on",
                    "faire un quiz",
                    "fais un quiz",
                    "donne moi un quiz",
                    "donne-moi un quiz",
                    "cree un quiz",
                    "crÃ©e un quiz",
                    "generer un quiz",
                    "gÃ©nÃ©rer un quiz",
                    "teste moi sur ce cours",
                    "teste-moi sur ce cours",
                    "interroge moi sur ce cours",
                    "interroge-moi sur ce cours",
                )

                def is_quiz_intent(normalized_text: str) -> bool:
                    if normalized_text in quiz_triggers:
                        return True
                    if any(normalized_text.startswith(trigger + " ") for trigger in quiz_triggers):
                        return True
                    return any(phrase in normalized_text for phrase in quiz_phrase_triggers)

                course_id = str(msg.get("course_id") or (ctx.course_id if ctx and ctx.course_id else "") or "").strip()
                chapter_index_raw = msg.get("chapter_index")
                section_index_raw = msg.get("section_index")
                try:
                    chapter_index_int = int(chapter_index_raw) if chapter_index_raw is not None else None
                except (TypeError, ValueError):
                    chapter_index_int = None
                try:
                    section_index_int = int(section_index_raw) if section_index_raw is not None else None
                except (TypeError, ValueError):
                    section_index_int = None

                current_slide_context = None
                if course_id and chapter_index_int is not None and section_index_int is not None:
                    current_slide_context = await load_course_slide_context(
                        course_id,
                        chapter_index_int,
                        section_index_int,
                    )

                current_slide_content = (msg.get("slide_content") or "").strip()
                current_chapter_title = msg.get("chapter", "")
                current_section_title = msg.get("section_title", msg.get("slide_title", ""))
                course_title = msg.get("course_title", "")
                course_domain = msg.get("course_domain", "general")
                current_chapter_idx = chapter_index_int + 1 if chapter_index_int is not None else None

                if current_slide_context:
                    current_slide_content = (current_slide_context.get("content") or current_slide_content).strip()
                    current_chapter_title = current_slide_context.get("chapter_title") or current_chapter_title
                    current_section_title = current_slide_context.get("section_title") or current_section_title
                    course_title = current_slide_context.get("course_title") or course_title
                    course_domain = current_slide_context.get("course_domain") or course_domain
                    current_chapter_idx = current_slide_context.get("chapter_order") or current_chapter_idx

                is_in_course = msg.get("in_course", in_course or bool(course_id))
                if is_in_course and is_quiz_intent(content_lower):
                    await cancel_text_question_task()
                    active_text_turn_id = 0
                    quiz_topic = current_section_title or current_chapter_title or current_slide_content or course_title or "Quiz"
                    quiz_query = current_slide_content or current_section_title or current_chapter_title or course_title or quiz_topic
                    quiz_chunks = rag.retrieve_chunks(
                        quiz_query,
                        k=Config.RAG_NUM_RESULTS,
                        current_chapter_idx=current_chapter_idx,
                        strict_chapter=bool(current_chapter_idx),
                        course_id=course_id if course_id else None,
                    )
                    if current_slide_content:
                        from langchain_core.documents import Document

                        slide_doc = Document(
                            page_content=current_slide_content,
                            metadata={
                                "course_id": course_id,
                                "chapter_idx": current_chapter_idx,
                                "chapter_title": current_chapter_title,
                                "section_title": current_section_title,
                                "slide_idx": current_slide_context.get("slide_index") if current_slide_context else chapter_index_int,
                                "source_file": msg.get("slide_path") or msg.get("image_url") or "",
                            },
                        )
                        quiz_chunks = [(slide_doc, 1.0, f"Current slide: {current_chapter_title} / {current_section_title}")] + quiz_chunks

                    lang = detect_lang_text(content)
                    subj = detect_subject(content)
                    await process_quiz_request(
                        quiz_topic=quiz_topic,
                        lang=lang,
                        subj=subj,
                        chunks_with_scores=quiz_chunks,
                        question_ctx=ctx,
                        presentation_cursor=current_presentation_cursor,
                        current_chapter_title=current_chapter_title,
                        current_section_title=current_section_title,
                        current_chapter_idx=current_chapter_idx,
                        section_index_int=section_index_int,
                        course_id=course_id,
                        course_title=course_title,
                        course_domain=course_domain,
                        slide_path=str(msg.get("slide_path") or msg.get("image_url") or (current_slide_context.get("slide_path") if current_slide_context else "") or ""),
                    )
                    continue
                if is_in_course and content_lower in resume_triggers:
                    await cancel_text_question_task()
                    active_text_turn_id = 0
                    if ctx:
                        # âœ… BUG #4 FIX: Retrieve char_offset from paused_state
                        resumed_ctx = await dialogue.resume_session(ctx.session_id)
                        if resumed_ctx and resumed_ctx.paused_state.get("timestamp") is not None:
                            # Restore cursor position from pause point
                            current_presentation_cursor = resumed_ctx.paused_state.get("presentation_cursor", resumed_ctx.paused_state.get("char_offset", 0))
                            cached_text = resumed_ctx.paused_state.get("presentation_text") or ""
                            cached_key = str(resumed_ctx.paused_state.get("presentation_key") or resumed_ctx.paused_state.get("slide_id") or "")
                            resume_slide_id = ":".join(str(part) for part in (course_id, chapter_index_int, section_index_int))
                            if cached_text and cached_key == resume_slide_id:
                                current_presentation_text = cached_text
                            resume_offset = current_presentation_cursor
                            log.info(f"ðŸ“ [{ctx.session_id[:8]}] Resume TTS from char {current_presentation_cursor}")
                            record_checkpoint_event({
                                "session_id": ctx.session_id,
                                "language": resumed_ctx.language if resumed_ctx else session_lang,
                                "subject": (ctx.course_analysis.get("course_domain", "") if ctx and ctx.course_analysis else ""),
                                "checkpoint_type": "resume",
                                "point_text": (
                                    f"â–¶ Reprise au point mÃ©morisÃ© â€” chapitre {resumed_ctx.chapter_index + 1}, "
                                    f"section {resumed_ctx.section_index + 1}, position {current_presentation_cursor}. "
                                    f"Narration reprise sans nouveau LLM."
                                ),
                                "location_label": f"chapitre {resumed_ctx.chapter_index + 1}, section {resumed_ctx.section_index + 1}",
                                "cursor_label": f"{current_presentation_cursor}/{len(current_presentation_text or '')}",
                                "slide_id": resume_slide_id,
                                "slide_title": current_section_title or current_chapter_title or "",
                                "chapter_index": resumed_ctx.chapter_index,
                                "section_index": resumed_ctx.section_index,
                                "char_position": current_presentation_cursor,
                                "reason": content_lower,
                                "source": "checkpoint",
                            })
                            await send({
                                "type": "system_notice",
                                "text": (
                                    f"â–¶ Reprise au point mÃ©morisÃ© â€” chapitre {resumed_ctx.chapter_index + 1}, "
                                    f"section {resumed_ctx.section_index + 1}, position {current_presentation_cursor}. "
                                    f"Narration reprise sans nouveau LLM."
                                ),
                            })
                        ctx = resumed_ctx or ctx
                    await send_state(
                        DialogState.PRESENTING,
                        details={
                            "course_title": course_title or "",
                            "chapter_title": current_chapter_title or "",
                            "section_title": current_section_title or "",
                            "slide_title": current_section_title or current_chapter_title or "",
                            "char_position": current_presentation_cursor,
                        },
                    )
                    await send({"type": "resume_course"})
                    continue

                # âœ… PrioritÃ© Ã  la question: stopper immÃ©diatement la prÃ©sentation en cours
                # pour Ã©viter que la narration du cours continue pendant la rÃ©ponse.
                turn_id = int(msg.get("turn_id") or 0)
                if turn_id <= 0:
                    text_turn_seq += 1
                    turn_id = text_turn_seq
                active_text_turn_id = turn_id

                if presentation_task and not presentation_task.done():
                    await cancel_presentation_task(notify_client=True)
                await cancel_audio_stream(notify_client=True, turn_id=turn_id)
                await cancel_text_question_task()

                lang   = detect_lang_text(content)
                subj   = detect_subject(content)
                
                # âœ… UPDATE STATE: Language Detection + Prosody (text: estimated)
                await send_state(
                    DialogState.PROCESSING, 
                    "stt_language_detection", 
                    {"language": lang},
                    {"language": lang},
                    turn_id=turn_id
                )
                
                await send_state(
                    DialogState.PROCESSING,
                    "prosody_analysis",
                    {"type": "text_question"},
                    {"speech_rate": len(content.split())},
                    turn_id=turn_id
                )
                
                # âœ… S29-32: DÃ‰TECTION DE CONFUSION AUTOMATIQUE (gÃ©nÃ©ralise audio_pipeline)
                # Inclut: mots-clÃ©s, rÃ©pÃ©tition, patterns d'historique + SEMANTIC (si brain fourni)
                # Pour questions texte, crÃ©er prosody estimÃ© (pas de voix rÃ©elle)
                text_prosody = {
                    "speech_rate": len(content.split()),  # Approximation: un mot = 1 mpm
                    "hesitation_count": 0,  # Pas accessible en texte
                    "markers": [],
                    "confidence": 0.0,  # Pas de signal prosodique en texte
                }
                
                # âœ… Helper function to emit micro-states during confusion detection
                async def emit_confusion_micro_state(state_name: str, metrics: dict):
                    """Wrapper for sending confusion micro-states with proper state"""
                    if metrics and metrics != {}:
                        await send_state(DialogState.PROCESSING, state_name, {}, metrics, turn_id=turn_id)
                
                is_confused, confusion_reason, q_hash, confusion_count = await dialogue.detect_and_track_confusion(
                    session_id=session_id,
                    question_text=content,
                    language=lang,
                    history=history,  # â† Inclure l'historique pour pattern detection
                    brain=brain,      # â† NOUVEAU: Embeddings sÃ©mantiques
                    prosody=text_prosody,  # â† Pour questions texte: dummy/estimÃ©
                    on_state_change=emit_confusion_micro_state,  # âœ… Pass callback for micro-states
                )
                
                # âœ… UPDATE STATE: RAG Search
                rag_start = time.time()
                await send_state(DialogState.PROCESSING, "rag_search", {}, {}, turn_id=turn_id)
                
                chunks_with_scores = rag.retrieve_chunks(
                    content,
                    k=Config.RAG_NUM_RESULTS,
                    current_chapter_idx=current_chapter_idx,
                    strict_chapter=bool(current_chapter_idx),
                    course_id=course_id if course_id else None,  # âœ… Scoped RAG retrieval
                )
                
                rag_time = (time.time() - rag_start) * 1000  # Convert to ms
                avg_score = sum(score for _, score, _ in chunks_with_scores) / len(chunks_with_scores) if chunks_with_scores else 0.0

                if current_slide_content:
                    from langchain_core.documents import Document

                    slide_doc = Document(
                        page_content=current_slide_content,
                        metadata={
                            "course_id": course_id,
                            "chapter_idx": current_chapter_idx,
                            "chapter_title": current_chapter_title,
                            "section_title": current_section_title,
                            "slide_idx": current_slide_context.get("slide_index") if current_slide_context else chapter_index_int,
                            "source_file": msg.get("slide_path") or msg.get("image_url") or "",
                        },
                    )
                    chunks_with_scores = [(slide_doc, 1.0, f"Current slide: {current_chapter_title} / {current_section_title}")] + chunks_with_scores

                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.PROCESSING)
                
                # âœ… UPDATE STATE: RAG Search Complete with Metrics
                await send_state(DialogState.PROCESSING, "rag_search", {}, {
                    "chunks_found": len(chunks_with_scores),
                    "avg_score": round(avg_score, 3),
                    "duration_ms": round(rag_time, 1),
                    "progress_pct": 35
                }, turn_id=turn_id)

                # âœ… UPDATE STATE: Confusion Detection (if any)
                if is_confused:
                    await send_state(DialogState.PROCESSING, "confusion_detected", 
                                   {"reason": confusion_reason}, 
                                   {"confidence": 0.85 if is_confused else 0.1},
                                   turn_id=turn_id)

                llm_start   = time.time()
                
                # âœ… UPDATE STATE: LLM Thinking
                await send_state(DialogState.PROCESSING, "llm_thinking", 
                               {"chunks": len(chunks_with_scores)},
                               {"chunks_processed": len(chunks_with_scores), "progress_pct": 50},
                               turn_id=turn_id)
                
                # âœ… TRY RAG + FALLBACK pour les questions texte (comme le streaming)
                # Construire le prompt : normal ou reformulation si confusion
                last_slide = ctx.last_slide_explained if ctx else ""
                
                if is_confused:
                    # Prompt spÃ©cial reformulation pour questions texte
                    question_for_llm = dialogue.build_confusion_prompt(
                        original_question=content,
                        reason=confusion_reason,
                        language=lang,
                        last_slide_content=last_slide,
                    )
                    log.info(f"[{session_id[:8]}] ðŸ“ Prompt reformulation appliquÃ© au LLM (texte)")
                else:
                    question_for_llm = content
                
                text_question_task = asyncio.create_task(
                    process_text_question_turn(
                        turn_id=turn_id,
                        content=content,
                        lang=lang,
                        subj=subj,
                        chunks_with_scores=chunks_with_scores,
                        rag_time=rag_time,
                        avg_score=avg_score,
                        is_confused=is_confused,
                        confusion_reason=confusion_reason,
                        question_for_llm=question_for_llm,
                        llm_start=llm_start,
                        question_ctx=ctx,
                        presentation_cursor=current_presentation_cursor,
                        current_chapter_title=current_chapter_title,
                        current_section_title=current_section_title,
                        current_chapter_idx=current_chapter_idx,
                        section_index_int=section_index_int,
                    )
                )
                continue

            # â”€â”€ quiz â€” gÃ©nÃ©rer un quiz structurÃ© â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            elif msg_type == "quiz":
                if ctx:
                    ctx = await dialogue.get_session(session_id) or ctx

                course_id = str(msg.get("course_id") or (ctx.course_id if ctx and ctx.course_id else "") or "").strip()
                chapter_index_raw = msg.get("chapter_index")
                section_index_raw = msg.get("section_index")
                try:
                    chapter_index_int = int(chapter_index_raw) if chapter_index_raw is not None else None
                except (TypeError, ValueError):
                    chapter_index_int = None
                try:
                    section_index_int = int(section_index_raw) if section_index_raw is not None else None
                except (TypeError, ValueError):
                    section_index_int = None

                current_slide_context = None
                if course_id and chapter_index_int is not None and section_index_int is not None:
                    current_slide_context = await load_course_slide_context(
                        course_id,
                        chapter_index_int,
                        section_index_int,
                    )

                current_slide_content = (msg.get("slide_content") or msg.get("content") or "").strip()
                current_chapter_title = msg.get("chapter", "")
                current_section_title = msg.get("section_title", msg.get("slide_title", ""))
                course_title = msg.get("course_title", "")
                course_domain = msg.get("course_domain", "general")
                current_chapter_idx = chapter_index_int + 1 if chapter_index_int is not None else None

                if current_slide_context:
                    current_slide_content = (current_slide_context.get("content") or current_slide_content).strip()
                    current_chapter_title = current_slide_context.get("chapter_title") or current_chapter_title
                    current_section_title = current_slide_context.get("section_title") or current_section_title
                    course_title = current_slide_context.get("course_title") or course_title
                    course_domain = current_slide_context.get("course_domain") or course_domain
                    current_chapter_idx = current_slide_context.get("chapter_order") or current_chapter_idx

                if not current_slide_content:
                    current_slide_content = current_section_title or current_chapter_title or course_title or ""

                quiz_topic = current_section_title or current_chapter_title or current_slide_content or course_title or "Quiz"
                quiz_query = current_slide_content or current_section_title or current_chapter_title or course_title or quiz_topic

                quiz_chunks = rag.retrieve_chunks(
                    quiz_query,
                    k=Config.RAG_NUM_RESULTS,
                    current_chapter_idx=current_chapter_idx,
                    strict_chapter=bool(current_chapter_idx),
                    course_id=course_id if course_id else None,
                )

                if current_slide_content:
                    from langchain_core.documents import Document

                    slide_doc = Document(
                        page_content=current_slide_content,
                        metadata={
                            "course_id": course_id,
                            "chapter_idx": current_chapter_idx,
                            "chapter_title": current_chapter_title,
                            "section_title": current_section_title,
                            "slide_idx": current_slide_context.get("slide_index") if current_slide_context else chapter_index_int,
                            "source_file": msg.get("slide_path") or msg.get("image_url") or "",
                        },
                    )
                    quiz_chunks = [(slide_doc, 1.0, f"Current slide: {current_chapter_title} / {current_section_title}")] + quiz_chunks

                lang = detect_lang_text(quiz_query)
                subj = detect_subject(quiz_query)
                await process_quiz_request(
                    quiz_topic=quiz_topic,
                    lang=lang,
                    subj=subj,
                    chunks_with_scores=quiz_chunks,
                    question_ctx=ctx,
                    presentation_cursor=current_presentation_cursor,
                    current_chapter_title=current_chapter_title,
                    current_section_title=current_section_title,
                    current_chapter_idx=current_chapter_idx,
                    section_index_int=section_index_int,
                    course_id=course_id,
                    course_title=course_title,
                    course_domain=course_domain,
                    slide_path=str(msg.get("slide_path") or msg.get("image_url") or (current_slide_context.get("slide_path") if current_slide_context else "") or ""),
                )
                continue

            # â”€â”€ next_section â€” avancer dans le cours â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            elif msg_type == "next_section":
                if ctx:
                    await dialogue.next_section(ctx.session_id)
                await send({"type": "section_changed", "direction": "next"})

            # â”€â”€ record dashboard event â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # (done after each complete interaction)

            # â”€â”€ ping / keepalive â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            elif msg_type == "ping":
                await send({"type": "pong"})

    except WebSocketDisconnect:
        websocket_closed = True
        log.info(f"ðŸ”Œ WebSocket dÃ©connectÃ© : {session_id[:8]}")
    except Exception as exc:
        log.error(f"âŒ WebSocket error [{session_id[:8]}]: {exc}", exc_info=True)
        if not websocket_closed:
            try:
                await send({"type": "error", "message": str(exc)})
            except Exception:
                pass
    finally:
        await cancel_next_slide_prefetch()
        await cancel_presentation_task(notify_client=False)
        await cancel_audio_stream(notify_client=False)
        await cancel_text_question_task()

# @app.post("/session")
async def create_session():
    """Create a new session with authentication token.
    
    Returns:
        {\"session_id\": str, \"token\": str}
    
    The client must use this token in the start_session message:
        {\"type\": \"start_session\", \"token\": \"...\", \"language\": \"fr\"}
    """
    session_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)  # 256-bit secure random token
    SESSION_TOKENS[session_id] = token
    
    log.info(f"âœ… Session created: {session_id[:8]} with auth token")
    return {"session_id": session_id, "token": token}


# @app.get("/search/transcripts")
async def search_transcripts(q: str, language: str = "", course_id: str = "",
                              role: str = "", limit: int = 20):
    """Recherche full-text dans l'historique des transcriptions."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="ParamÃ¨tre 'q' requis")
    results = transcript_searcher.search(q, language=language,
                                        course_id=course_id, role=role, limit=limit)
    return {"query": q, "count": len(results), "results": results}

# @app.get("/search/session/{session_id}")
async def get_session_transcript(session_id: str):
    """Retourne l'historique complet d'une session."""
    history = transcript_searcher.get_session_history(session_id)
    return {"session_id": session_id, "count": len(history), "history": history}

# @app.get("/search/stats")
async def search_stats():
    """Statistiques sur l'index de recherche."""
    return transcript_searcher.get_stats()

# @app.get("/analytics/report")
async def analytics_report():
    """Rapport analytics complet."""
    return analytics_engine.full_report()

# @app.get("/analytics/kpi")
async def analytics_kpi(hours: int = 24):
    """KPIs sur les N derniÃ¨res heures."""
    return analytics_engine.kpi_summary(hours=hours)

# @app.get("/analytics/progression/{course_id}")
async def analytics_progression(course_id: str):
    """Progression des sections pour un cours."""
    return {
        "course_id":   course_id,
        "progression": analytics_engine.progression_by_course(course_id),
    }

# @app.get("/analytics/latency")
async def analytics_latency():
    """Distribution des latences (min/avg/max/p95)."""
    return analytics_engine.latency_distribution()

# @app.get("/media/{path:path}")
async def serve_media(path: str):
    """Sert les fichiers mÃ©dia stockÃ©s localement."""
    from fastapi.responses import FileResponse
    from modules.data.media_storage import LOCAL_MEDIA_DIR
    file_path = LOCAL_MEDIA_DIR / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fichier non trouvÃ©")
    return FileResponse(str(file_path))

# @app.get("/media-list")
async def list_media(prefix: str = ""):
    """Liste les fichiers mÃ©dias disponibles."""
    objects = media_storage.list_objects(prefix)
    return {"count": len(objects), "objects": objects[:100]}


# @app.get("/profile/{student_id}")
async def get_student_profile(student_id: str):
    """Retourne le profil d'un Ã©tudiant."""
    profile = await profile_mgr.get_or_create(student_id)
    from dataclasses import asdict
    return asdict(profile)

# @app.post("/profile/{student_id}/reset")
async def reset_student_profile(student_id: str):
    """Remet Ã  zÃ©ro le profil d'un Ã©tudiant."""
    from modules.pedagogy.student_profile import StudentProfile
    profile = StudentProfile(student_id=student_id)
    await profile_mgr.save(profile)
    return {"status": "reset", "student_id": student_id}

if __name__ == "__main__":
    import uvicorn

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
            probe_socket.bind((Config.SERVER_HOST, Config.SERVER_PORT))
    except OSError as exc:
        log.error(
            "ðŸš« Port %s dÃ©jÃ  utilisÃ© sur %s:%s (%s) â†’ arrÃªtez l'autre instance ou changez SERVER_PORT",
            Config.SERVER_PORT,
            Config.SERVER_HOST,
            Config.SERVER_PORT,
            exc,
        )
        raise SystemExit(1)

    log.info("")
    log.info("Interface UI       : http://localhost:" + str(Config.SERVER_PORT) + "/static/index.html")
    log.info("Swagger Docs       : http://localhost:" + str(Config.SERVER_PORT) + "/docs")
    log.info(" WebSocket tunnels  : ws://localhost:" + str(Config.SERVER_PORT) + "/ws/{session_id}")
    log.info("")
    log.info(" Serveur actif ” Appuyez sur Ctrl+C pour arreter")
    log.info("")
    uvicorn.run(app, host=Config.SERVER_HOST, port=Config.SERVER_PORT, reload=False)
