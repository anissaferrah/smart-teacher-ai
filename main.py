"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — WebSocket Server (Streaming Audio)          ║
║                                                                      ║
║  Ce fichier est le point d'entrée PRINCIPAL du projet.              ║
║  Il remplace server.py pour la production.                          ║
║                                                                      ║
║  Routes WebSocket :                                                  ║
║    WS  /ws/{session_id}    — pipeline vocal temps réel              ║
║                                                                      ║
║  Routes REST :                                                        ║
║    POST /session            — créer une session avec token auth     ║
║    POST /ask                — texte → réponse                       ║
║    POST /ingest             — indexer des fichiers dans le RAG      ║
║    GET  /rag/stats          — statistiques RAG                      ║
║    GET  /session/{id}       — état de la session                    ║
║    GET  /health             — healthcheck complet                   ║
║                                                                      ║
║  Messages WebSocket (client → serveur) :                            ║
║    {"type": "start_session",  "token": "...", "language": "fr"}   ║
║    {"type": "audio_chunk",    "data": "<base64>"}                   ║
║    {"type": "audio_end"}                                            ║
║    {"type": "interrupt"}                                            ║
║    {"type": "next_section"}                                         ║
║    {"type": "text",           "content": "..."}                     ║
║                                                                      ║
║  Messages WebSocket (serveur → client) :                            ║
║    {"type": "session_ready",  "session_id": "..."}                  ║
║    {"type": "transcription",  "text": "...", "lang": "fr"}          ║
║    {"type": "answer_text",    "text": "..."}                        ║
║    {"type": "audio_chunk",    "data": "<base64>", "mime": "..."}    ║
║    {"type": "state_change",   "state": "PROCESSING"}                ║
║    {"type": "error",          "message": "..."}                     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import base64
import io
import logging
import os
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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langdetect import detect

from config import Config
from handlers.session_manager import HTTP_SESSIONS, SESSION_TOKENS, detect_lang_text, audio_bytes_to_numpy, detect_subject, get_http_session
from handlers.audio_pipeline import run_pipeline_streaming, run_pipeline
from modules.transcriber    import Transcriber
from modules.llm            import Brain
from modules.tts            import VoiceEngine
from modules.multimodal_rag import MultiModalRAG
from modules.logger         import CsvLogger
from modules.stt_logger     import STTLogger
from modules.dialogue       import DialogueManager, DialogState, SessionContext
from modules.student_profile import ProfileManager
from modules.slide_sync      import SlideSynchronizer
from modules.dashboard       import router as dashboard_router, record_session_event
from modules.media_storage   import get_storage
from modules.transcript_search import get_searcher, TranscriptEntry
from modules.analytics       import get_analytics
from modules.course_analyzer import get_analyzer
from modules.ingestion_manager import IngestionManager
from database.init_db       import check_db_connection, create_tables
from database.crud          import (
    create_learning_session, log_interaction,
    update_session_state, get_session_stats,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SmartTeacher.Main")


# ══════════════════════════════════════════════════════════════════════
#  INITIALISATION DES MODULES
# ══════════════════════════════════════════════════════════════════════

log.info("=" * 70)
log.info("🤖 SMART TEACHER — DÉMARRAGE (WebSocket + REST)")
log.info("=" * 70)
log.info("")
log.info("📦 Services Docker requis:")
log.info("   • PostgreSQL (5432) — Base de données")
log.info("   • Redis (6379) — Cache et sessions")
log.info("   • Qdrant (6333) — RAG vectoriel")
log.info("   • Ollama (11434) — LLM local (fallback)")
log.info("")
log.info("💡 Lancez-les: docker-compose up -d")
log.info("")

Config.validate()

transcriber = Transcriber()
brain       = Brain()
voice       = VoiceEngine()
rag         = MultiModalRAG(db_dir=Config.RAG_DB_DIR)
csv_logger  = CsvLogger()
stt_logger  = STTLogger()
dialogue    = DialogueManager()
profile_mgr   = ProfileManager()
slide_sync    = SlideSynchronizer()
media_storage = get_storage()
transcript_searcher = get_searcher()
analytics_engine    = get_analytics()
ingestion_manager   = IngestionManager()

# Note: HTTP_SESSIONS and SESSION_TOKENS are imported from handlers.session_manager
# They are shared module-level dicts initialized once

log.info("✅ Modules prêts")


# ══════════════════════════════════════════════════════════════════════
#  PIPELINE VOCAL CENTRAL
# ══════════════════════════════════════════════════════════════════════
# Note: run_pipeline_streaming() and run_pipeline() are imported from
# handlers.audio_pipeline. These functions implement:
#   - run_pipeline_streaming(audio, session_id, history, ...) → Streaming LLM+TTS
#   - run_pipeline(audio, session_id, history, ...) → Full audio pipeline
#
# Usage in websocket_endpoint:
#   result = await run_pipeline_streaming(
#       audio_data, session_id, history,
#       on_text_chunk=..., on_audio_chunk=..., course_id=...
#   )


# ══════════════════════════════════════════════════════════════════════
#  APPLICATION FASTAPI
# ══════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialisation légère au démarrage, avec dégradation si PostgreSQL est indisponible."""
    try:
        if await check_db_connection():
            await create_tables()
            log.info("✅ PostgreSQL tables créées/validées")
        else:
            log.info("ℹ️ PostgreSQL indisponible au démarrage — mode dégradé activé")
    except Exception as exc:
        log.info(f"ℹ️ PostgreSQL non disponible au démarrage ({exc}) — mode dégradé activé")

    yield


app = FastAPI(
    title="Smart Teacher API",
    description="Professeur IA Vocal — WebSocket + REST | STT+RAG+LLM+TTS",
    version="3.0.0",
    lifespan=lifespan,
)

if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# 📸 Routes pour les PNG slides (images visuelles du cours)
if Path("media").exists():
    app.mount("/media", StaticFiles(directory="media"), name="media")

app.include_router(dashboard_router)


async def load_course_slide_context(
    course_id: str,
    chapter_index: int,
    section_index: int,
) -> dict | None:
    """Charge la slide courante d'un cours depuis PostgreSQL."""
    if not course_id:
        return None

    try:
        from database.init_db import AsyncSessionLocal
        from database.crud import get_course_with_structure
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
            
            # ✅ NOUVEAU: Analyser le cours pour le contexte LLM (une fois par cours)
            if chapter_index == 0:  # Première fois = analyser le cours entier
                try:
                    analyzer = get_analyzer()
                    course_data = {
                        "title": course.title,
                        "domain": course.domain or "general",
                        "chapters": [
                            {
                                "title": ch.title,
                                "sections": [
                                    {"title": sec.title, "content": sec.content or ""}
                                    for sec in sorted(ch.sections, key=lambda s: s.order or 0)
                                ],
                            }
                            for ch in chapters
                        ],
                    }
                    analysis = analyzer.analyze(course_data)
                    # 📝 Stocker pour utiliser plus tard
                except Exception as e:
                    log.debug(f"Course analysis error: {e}")
                    analysis = None
            
            slide_path = section.image_url or (
                section.image_urls[0]
                if getattr(section, "image_urls", None)
                else ""
            )

            total_sections = sum(
                len(sorted(ch.sections, key=lambda sec: sec.order or 0))
                for ch in chapters
            )
            global_slide_index = sum(
                len(sorted(ch.sections, key=lambda sec: sec.order or 0))
                for ch in chapters[:chapter_index]
            ) + section_index
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
                # ✅ NOUVEAU: Ajouter analysis du cours
                "course_summary": analysis.get("summary", "") if analysis else "",
                "course_analysis": analysis or {},
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


# ══════════════════════════════════════════════════════════════════════
#  WEBSOCKET — Pipeline Vocal Temps Réel
# ══════════════════════════════════════════════════════════════════════

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
    current_presentation_key: tuple[str, int, int] | None = None
    current_presentation_text: str = ""
    current_presentation_cursor: int = 0
    websocket_closed = False
    student_profile: dict = {}  # ✅ Profil de l'étudiant pour timing adaptatif
    interrupt_audio: bool = False  # 🚨 Flag pour interrompre le TTS en temps réel
    presentation_start_time: float = 0.0  # ✅ NOUVEAU: Timestamp quand présentation commence

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
                log.info(f"[{session_id[:8]}] WebSocket fermé pendant send: {exc}")
                return False

    async def handle_post_response(timeout_sec: float = 2.5) -> bool:
        """
        Après que le LLM a répondu.
        Attire interruption utilisateur (VAD).
        Timeout adaptatif selon le profil étudiant (niveau + performance).
        
        Returns: True si utilisateur a interrompu, False si timeout
        """
        if not ctx:
            return False
        
        try:
            # ✅ Calculer timeout ADAPTATIF selon profil
            BASE_TIMING = {
                "collège": 5.0,
                "lycée": 4.0,
                "licence": 3.5,
                "master": 2.5,
                "doctorat": 2.0,
            }
            
            # Récupérer le timing de base selon le niveau
            base_timeout = BASE_TIMING.get(session_level, 3.0)
            
            # ✅ Ajuster selon la confusion de l'étudiant
            if student_profile:
                confusion_count = student_profile.get("confusion_count", 0)
                asks_repeat = student_profile.get("asks_repeat", 0)
                
                # Plus confusion → plus de temps (ajouter 0.5s par confusion)
                confusion_factor = 1.0 + (confusion_count * 0.5)
                
                # Plus demande de répétitions → plus de temps
                repeat_factor = 1.0 + (asks_repeat * 0.3)
                
                # Appliquer les facteurs
                timeout_sec = base_timeout * confusion_factor * repeat_factor
                
                log.info(
                    f"⏱️  Timing adaptatif | level={session_level} base={base_timeout:.1f}s "
                    f"confusion_factor={confusion_factor:.2f} repeat_factor={repeat_factor:.2f} "
                    f"→ final={timeout_sec:.2f}s"
                )
            else:
                timeout_sec = base_timeout
            
            # ⏸️  Transition vers WAITING (court repos)
            await dialogue.transition(ctx.session_id, DialogState.WAITING)
            await send_state(DialogState.WAITING)
            log.info(f"⏸️  [{session_id[:8]}] Waiting for interruption ({timeout_sec:.1f}s)...")
            
            # ⏱️  Attendre interruption utilisateur (durée timeout)
            start_wait = time.time()
            while time.time() - start_wait < timeout_sec:
                # Vérifier si VAD a détecté la parole
                session = await dialogue.get_session(ctx.session_id)
                if session and session.state == DialogState.LISTENING.value:
                    # ✅ Utilisateur a interrompu!
                    log.info(f"🎤 [{session_id[:8]}] User interrupt detected → LISTENING")
                    return True
                
                await asyncio.sleep(0.05)  # Vérifier tous les 50ms
            
            # ⏭️  Timeout écoulé = pas d'interruption → continuer auto
            log.info(f"▶️  [{session_id[:8]}] No interrupt → auto-advancing")
            return False
            
        except Exception as e:
            log.error(f"❌ Error in handle_post_response: {e}")
            return False

    async def send_state(state: DialogState, substep: str = "", details: dict = None, metrics: dict = None):
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
            "stt_language_detection": {"emoji": "🌍", "step": "Language Detection", "desc": "Language identification", "detail": "(EN/FR/AR auto-detect)"},
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
        
        # ═══════════════════════════════════════════════════════════════════════
        # BUILDING ENRICHED MESSAGE
        # ═══════════════════════════════════════════════════════════════════════
        msg_lines = [f"{emoji} {state_name}"]
        
        # Line 2: State description
        if state_info.get("description"):
            msg_lines.append(f"   {state_info['description']}")
        
        # Line 3-5: Detailed substep
        # ✅ SHOW SUBSTEPS FOR STREAMING REASONING DISPLAY
        if substep and substep in substep_full:
            sub = substep_full[substep]
            msg_lines.append("")  # Empty line
            msg_lines.append(f"{sub['emoji']} {sub['step']}")
            msg_lines.append(f"   → {sub['desc']}")
            if sub.get('detail'):
                msg_lines.append(f"   💭 {sub['detail']}")
        
        # Additional details
        if details and details.get("reason"):
            msg_lines.append(f"   🎯 Reason: {details['reason'].replace('_', ' ').title()}")
        
        # ═══════════════════════════════════════════════════════════════════════
        # REAL-TIME METRICS SECTION 📊
        # ✅ ONLY SHOW METRICS FOR RESPONDING STATE (end of processing)
        # ═══════════════════════════════════════════════════════════════════════
        if metrics and len(metrics) > 0 and state == DialogState.RESPONDING:
            msg_lines.append("")  # Empty line
            msg_lines.append("📊 Complete Metrics:")
            
            # Duration metrics
            if "elapsed" in metrics:
                msg_lines.append(f"   ⏱️  Elapsed: {metrics['elapsed']:.2f}s")
            if "total_time" in metrics:
                msg_lines.append(f"   ⏱️  Total: {metrics['total_time']:.2f}s")
            
            # Quality metrics
            if "confidence" in metrics:
                conf = metrics["confidence"]
                bar = "▓" * int(conf * 10) + "░" * (10 - int(conf * 10))
                msg_lines.append(f"   🎯 Confidence: {bar} {conf:.0%}")
            
            # STT metrics
            if "speech_rate" in metrics:
                msg_lines.append(f"   🎤 Speech Rate: {metrics['speech_rate']:.0f} wpm")
            if "hesitations" in metrics:
                msg_lines.append(f"   💭 Hesitations: {metrics['hesitations']} found")
            if "language" in metrics:
                msg_lines.append(f"   🌍 Language: {metrics['language'].upper()}")
            
            # RAG metrics
            if "chunks" in metrics:
                msg_lines.append(f"   📚 Documents: {metrics['chunks']} found")
            if "retrieval_time" in metrics:
                msg_lines.append(f"   🔍 Retrieval: {metrics['retrieval_time']:.3f}s")
            if "document_score" in metrics:
                msg_lines.append(f"   🎲 Top Score: {metrics['document_score']:.2f}/1.00")
            
            # Confusion metrics
            if "confusion_confidence" in metrics:
                conf = metrics["confusion_confidence"]
                msg_lines.append(f"   🤔 Confusion Level: {conf:.0%}")
            
            # LLM metrics
            if "tokens" in metrics:
                msg_lines.append(f"   🔤 Tokens: {metrics['tokens']} generated")
            if "sentences" in metrics:
                msg_lines.append(f"   📝 Sentences: {metrics['sentences']}")
            if "words" in metrics:
                msg_lines.append(f"   📰 Words: {metrics['words']}")
            if "llm_time" in metrics:
                msg_lines.append(f"   🧠 LLM Time: {metrics['llm_time']:.2f}s")
            
            # TTS metrics
            if "tts_chunks" in metrics:
                msg_lines.append(f"   🎙️  Audio Chunks: {metrics['tts_chunks']}")
            if "audio_duration" in metrics:
                msg_lines.append(f"   🔉 Audio Duration: {metrics['audio_duration']:.1f}s")
            
            # Progress bar
            if "progress" in metrics:
                prog = metrics["progress"]
                bar = "▓" * int(prog * 12) + "░" * (12 - int(prog * 12))
                msg_lines.append(f"   {bar} {prog:.0%}")
        
        display_message = "\n".join(msg_lines)
        
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
        })

    async def set_listening_state() -> None:
        """
        Transition SÉCURISÉE vers LISTENING avec gestion de la machine d'état.
        
        ✅ Si en LISTENING: pas de transition nécessaire
        ✅ Si en PROCESSING: passer par CLARIFICATION d'abord (transition valide)
        ✅ Si dans autre état: transition directe
        """
        nonlocal ctx
        
        if not ctx:
            return
        
        current_state = ctx.state
        
        # ✅ Déjà en LISTENING: rien à faire
        if current_state == DialogState.LISTENING.value:
            return
        
        # ✅ Si en PROCESSING: passer par CLARIFICATION (transition valide: PROCESSING → CLARIFICATION)
        if current_state == DialogState.PROCESSING.value:
            log.info(f"[{session_id[:8]}] 🔄 PROCESSING → CLARIFICATION → LISTENING (transition sécurisée)")
            await dialogue.transition(ctx.session_id, DialogState.CLARIFICATION)
            await send_state(DialogState.CLARIFICATION)
            await send({"type": "message", "text": "Je n'ai rien entendu. Peux-tu répéter?"})
        
        # ✅ Si en PRESENTING: annuler d'abord la présentation
        if current_state == DialogState.PRESENTING.value:
            log.info(f"[{session_id[:8]}] 🛑 PRESENTING → LISTENING (annulation présentation)")
            await cancel_presentation_task(notify_client=False)
        
        # ✅ Maintenant transition sécurisée vers LISTENING
        ctx = await dialogue.get_session(ctx.session_id) or ctx
        if ctx.state != DialogState.LISTENING.value:
            await dialogue.transition(ctx.session_id, DialogState.LISTENING)
        
        await send_state(DialogState.LISTENING)

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
            # Laisse la boucle événementielle respirer entre chunks
            await asyncio.sleep(0)

    async def cancel_audio_stream(notify_client: bool = False) -> None:
        nonlocal audio_stream_task
        if audio_stream_task and not audio_stream_task.done():
            audio_stream_task.cancel()
            try:
                await audio_stream_task
            except asyncio.CancelledError:
                pass
        audio_stream_task = None
        if notify_client:
            await send({"type": "audio_interrupted", "stream_id": current_stream_id})

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
        student_level: str = "lycée",
        course_summary: str = "",  # ✅ NOUVEAU: contexte du cours entier
        is_resume: bool = False,   # ✅ NOUVEAU: détecter pause/reprise
        session_id: str | None = None,  # ✅ For rate limiting
    ) -> str:
        """
        Expliquer un slide de manière PRÉCISE.
        Focus UNIQUEMENT sur la slide actuelle.
        
        Args:
            slide_content: Contenu EXACT de la slide
            chapter_idx: Index du chapitre
            chapter_title: Titre du chapitre
            section_title: Titre de la section
            language: fr/en/ar
            student_level: collège/lycée/licence/master/doctorat
            course_summary: Résumé du cours entier (contexte global)
            is_resume: True si pause/reprise (ne pas redémarrer depuis début)
        """
        try:
            # ✅ NO RAG! JUSTE la slide actuelle + positionnement
            position_info = f"Chapitre {chapter_idx + 1}: {chapter_title}"
            if section_title:
                position_info += f" → Section: {section_title}"
            
            # ✅ Contexte global du cours (pour cohérence)
            course_context = course_summary or position_info
            
            # ✅ Adapter le ton selon le niveau
            level_instruction = {
                "collège": "Explique très simplement, avec des exemples concrets et accessibles. Évite la terminologie complexe.",
                "lycée": "Sois clair et structuré. Utilise la terminologie exacte mais reste accessible.",
                "licence": "Sois technique et précis. Utilise la terminologie universitaire. Cite les concepts clés.",
                "master": "Utilise un langage technique avancé. Analyse critique. Références théoriques attendues.",
                "doctorat": "Analyse approfondie avec terminologie spécialisée. Enjeux de recherche. Nuances critiques.",
            }
            level_hint = level_instruction.get(student_level, level_instruction["lycée"])
            
            # ✅ Prompt ULTRA STRICT anti-hallucination (TRÈS IMPORTANT)
            if language == "fr":
                if is_resume:
                    # 🔄 Mode REPRISE : ne pas redémarrer depuis le début
                    prompt_mode = """ATTENTION: Cette slide a DÉJÀ été expliquée.
NE RECOMMENCE PAS L'EXPLICATION.
Continues où tu t'étais arrêté ou propose des détails supplémentaires."""
                else:
                    prompt_mode = ""
                
                system_prompt = f"""Tu es Smart Teacher, expert pédagogue.

**RÈGLES ABSOLUES (non-négociable)**:

1. ❌ JAMAIS parler de :
   - Chapitres futurs
   - Sujets "qui viennent après"
   - "nous verrons...", "ensuite...", "dans la suite..."
   - Connaissances hors du cours

2. ✅ SEULEMENT :
   - Contenu de CETTE slide
   - Ce qui est en cours

3. 🚫 Si tu ne sais pas :
   - NE PAS inventer
   - Dis: "Ce détail n'est pas expliqué"

**CONTEXTE COURS**:
{course_context}

**AUDIENCE**: {student_level}

{prompt_mode}

**SLIDE À EXPLIQUER**:
{slide_content}

Explique ça naturellement. MAX 4 phrases."""

            else:  # English
                if is_resume:
                    prompt_mode = """ATTENTION: This slide was already explained.
DO NOT restart.
Continue from where you stopped or add extra details."""
                else:
                    prompt_mode = ""
                
                system_prompt = f"""You are Smart Teacher, expert educator.

**ABSOLUTE RULES (non-negotiable)**:

1. ❌ NEVER mention:
   - Future chapters
   - Topics "that come next"
   - "we will see...", "later...", "next in the course..."
   - Knowledge outside the course

2. ✅ ONLY:
   - This CURRENT slide content
   - What is being taught right now

3. 🚫 If you don't know:
   - DO NOT invent
   - Say: "This detail is not explained"

**COURSE CONTEXT**:
{course_context}

**AUDIENCE**: {student_level}

{prompt_mode}

**SLIDE TO EXPLAIN**:
{slide_content}

Explain naturally. MAX 4 sentences."""

            # ✅ LLM call direct (pas de RAG, juste la slide)
            response, duration = brain.ask(
                question=slide_content[:100],  # Juste première partie pour référence
                course_context=slide_content,  # La slide EST le contexte
                reply_language=language,
                chapter_idx=chapter_idx,
                chapter_title=chapter_title,
                section_title=section_title,
                domain=None,
                session_id=session_id,  # ✅ Pass session_id for rate limiting
            )
            
            log.info(f"✅ LLM focused response ({duration:.1f}s) | {len(response)} chars")
            return response
            
        except Exception as e:
            log.error(f"❌ Error in explain_slide_focused: {e}")
            return f"Erreur lors de l'explication : {str(e)}"

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")

            # ── start_session ─────────────────────────────────────────
            if msg_type == "start_session":
                # ✅ Flexible auth: Only validate if we have a token entry
                # - If session_id in SESSION_TOKENS: Validate token strictly (secure flow)
                # - Otherwise: Auto-approve unconditionally (legacy SDK)
                token = msg.get("token")
                
                if session_id in SESSION_TOKENS:
                    # Secure flow: We generated a token, so it must be provided and match
                    if not token or SESSION_TOKENS.get(session_id) != token:
                        await send({"type": "error", "message": "Authentication failed: invalid or missing token"})
                        await websocket.close(code=1008, reason="Unauthorized")
                        log.warning(f"[{session_id[:8]}] ❌ WebSocket auth failed (invalid token)")
                        return
                    # Token is valid - consume it (one-time use)
                    del SESSION_TOKENS[session_id]
                    log.info(f"[{session_id[:8]}] ✅ WebSocket authenticated (secure token)")
                else:
                    # Legacy flow: No token generated, so ignore any token and auto-approve
                    log.info(f"[{session_id[:8]}] ✅ WebSocket auto-approved (legacy SDK)")
                
                lang  = msg.get("language", "fr")
                level = msg.get("level",    "lycée")
                ctx   = await dialogue.create_session(
                    session_id=session_id,
                    language=lang,
                    student_level=level,
                    course_id=(msg.get("course_id") or None),
                )
                session_lang  = lang
                session_level = level
                history.clear()
                interrupt_audio = False  # 🟢 Réinitialiser le flag

                await send({"type": "session_ready", "session_id": ctx.session_id})
                
                # ✅ NOUVEAU: Transition explicite IDLE → LISTENING
                await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                await send_state(DialogState.LISTENING)
                log.info(f"[{session_id[:8]}] 🚀 Session démarrée | lang={lang} level={level} state=LISTENING")

            # ── audio_chunk — accumule les données audio ───────────────
            elif msg_type == "audio_chunk":
                raw = msg.get("data", "")
                if raw:
                    try:
                        decoded = base64.b64decode(raw)
                        log.info(f"   📦 Audio chunk: base64_len={len(raw)} → {len(decoded)} bytes")
                        # ✅ REFRESH ctx (peut être modifié par run_presentation)
                        if ctx:
                            ctx = await dialogue.get_session(session_id) or ctx
                        
                        if ctx and ctx.state in [DialogState.RESPONDING.value, DialogState.PRESENTING.value]:
                            log.info(f"[{session_id[:8]}] Interruption vocale detectee")
                            interrupt_audio = True
                            
                            # ✅ NOUVEAU: Déterminer si interruption est TRÈS PRÉCOCE (avant streaming)
                            time_since_presenting = time.time() - presentation_start_time if presentation_start_time > 0 else 999
                            if ctx.state == DialogState.PRESENTING.value and time_since_presenting < 1.0:
                                log.info(f"[{session_id[:8]}] ⚡ TRÈS TÔT interruption ({time_since_presenting:.2f}s après PRESENTING) → annuler préparation")
                            
                            # ✅ CRUCIAL: Sauvegarder la position AVANT d'annuler
                            if ctx and current_presentation_cursor > 0:
                                await dialogue.save_position(ctx.session_id, current_presentation_cursor)
                                log.info(f"[{session_id[:8]}] 💾 Position saved: cursor={current_presentation_cursor}")
                            
                            # ✅ Annuler la présentation EN COURS pour éviter conflit
                            await cancel_presentation_task(notify_client=True)
                            await cancel_audio_stream(notify_client=True)
                            await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                            await send_state(DialogState.LISTENING)
                        audio_buffer.append(decoded)
                    except Exception as e:
                        log.error(f"❌ Failed to decode audio chunk: {e}")

            # ── audio_end — traite l'audio accumulé ───────────────────
            elif msg_type == "audio_end":
                interrupt_audio = False
                
                # ✅ REFRESH ctx FROM REDIS (peut être modifié par run_presentation en tâche async)
                if not ctx:
                    ctx = await dialogue.get_session(session_id)
                else:
                    ctx = await dialogue.get_session(session_id) or ctx
                
                # ✅ SÉCURITÉ: Ne jamais traiter audio_end sans session active
                if not ctx:
                    await send({"type": "error", "message": "Aucune session active (démarrez avec start_session)"})
                    continue
                
                # ✅ SÉCURITÉ: Bloquer transition IDLE → PROCESSING (mais LISTENING OK!)
                if ctx.state == DialogState.IDLE.value:
                    log.warning(f"[{session_id[:8]}] ⚠️ Tentative audio_end en IDLE → ignoré (jamais IDLE → PROCESSING)")
                    await send({"type": "error", "message": "Session en IDLE, démarrage nécessaire"})
                    continue
                
                if not audio_buffer:
                    await send({"type": "error", "message": "Aucun audio reçu"})
                    continue
                await cancel_audio_stream(notify_client=False)

                # Assembler et convertir l'audio
                full_audio = b"".join(audio_buffer)
                log.info(f"[{session_id[:8]}] 🎙️ Audio buffer assembled: {len(audio_buffer)} chunks = {len(full_audio)} total bytes")
                audio_buffer.clear()

                try:
                    audio_np = audio_bytes_to_numpy(full_audio)
                except RuntimeError as exc:
                    await send({"type": "error", "message": str(exc)})
                    continue

                # Transition → PROCESSING (sécurisée via state machine)
                await dialogue.transition(ctx.session_id, DialogState.PROCESSING)
                await send_state(DialogState.PROCESSING)

                # ══════════════════════════════════════════════════════════════
                # 🚀 STREAMING PIPELINE: Real-time LLM → TTS
                # ══════════════════════════════════════════════════════════════
                
                current_stream_id += 1
                stream_id = current_stream_id
                full_answer = ""
                transcription_sent = False
                
                async def on_text_chunk(sentence: str, full_response: str):
                    nonlocal full_answer, transcription_sent
                    full_answer = full_response
                    
                    # Send transcription only once
                    if not transcription_sent:
                        # Note: transcription extracted from STT in run_pipeline_streaming
                        transcription_sent = True
                
                async def on_state_change(substep: str, details: dict = None):
                    """✅ NOUVEAU: Callback pour les mises à jour d'état de la pipeline"""
                    return await send_state(
                        DialogState.PROCESSING,
                        substep=substep,
                        details=details or {}
                    )
                
                async def on_audio_chunk(audio_bytes: bytes, mime: str):
                    """Stream each sentence's audio as it's generated"""
                    nonlocal interrupt_audio
                    if audio_bytes:
                        chunk_size = 4096
                        total_len = len(audio_bytes)
                        for i in range(0, total_len, chunk_size):
                            # 🚨 Vérifier le flag d'interruption EN TEMPS RÉEL
                            if interrupt_audio:
                                log.info(f"[{session_id[:8]}] 🛑 Audio interruption détectée → STOP streaming")
                                return
                            
                            chunk = audio_bytes[i:i + chunk_size]
                            if not await send({
                                "type":      "audio_chunk",
                                "stream_id": stream_id,
                                "data":      base64.b64encode(chunk).decode(),
                                "mime":      mime,
                                "final":     (i + chunk_size) >= total_len,
                            }):
                                return
                            await asyncio.sleep(0)  # yield control
                
                try:
                    # Launch streaming pipeline with course language to force STT detection
                    course_lang = ctx.course_analysis.get("language") if ctx and ctx.course_analysis else None
                    course_id_for_rag = ctx.course_id if ctx else None  # ✅ Pass course_id from session context
                    result = await run_pipeline_streaming(
                        audio_np, session_id, history,
                        on_text_chunk=on_text_chunk,
                        on_audio_chunk=on_audio_chunk,
                        on_state_change=on_state_change,  # ✅ NOUVEAU: State updates
                        force_language=course_lang,
                        course_id=course_id_for_rag,  # ✅ Scoped RAG retrieval
                        # ✅ Inject dependencies
                        transcriber=transcriber,
                        rag=rag,
                        voice=voice,
                        brain=brain,
                        dialogue=dialogue,
                        csv_logger=csv_logger,
                        stt_logger=stt_logger,
                    )

                    if "error" in result:
                        # ✅ Quand STT échoue: passer par CLARIFICATION (transition valide depuis PROCESSING)
                        await send({"type": "error", "message": result["error"]})
                        if ctx:
                            await dialogue.transition(ctx.session_id, DialogState.CLARIFICATION)
                        await send_state(DialogState.CLARIFICATION)
                        # Puis revenir à LISTENING via set_listening_state()
                        ctx = await dialogue.get_session(session_id) or ctx  # ✅ Refresh ctx
                        await set_listening_state()
                        continue

                    # Send transcription (extracted from STT)
                    t = result["transcription"]
                    if not await send({"type": "transcription", "text": t["text"],
                                "lang": t["language"], "confidence": t["confidence"]}):
                        continue

                    # Transition → RESPONDING (now streaming)
                    if ctx:
                        await dialogue.transition(ctx.session_id, DialogState.RESPONDING)
                    await send_state(DialogState.RESPONDING)

                    # Send final full answer text
                    if not await send({"type": "answer_text", "text": result["answer"],
                                "subject": result["subject"], "rag_chunks": result["rag_chunks"]}):
                        continue

                    # Send performance metrics
                    if not await send({"type": "performance", **result["performance"]}):
                        continue
                    
                    # Signal stream completion
                    if not await send({"type": "audio_stream_end", "stream_id": stream_id}):
                        continue

                    # ✅ CRITICAL: Attendre interruption ou auto-avancer
                    await asyncio.sleep(0.5)  # Petit pause après TTS
                    
                    user_interrupted = await handle_post_response(timeout_sec=2.5)
                    
                    if user_interrupted:
                        # ✅ Utilisateur a posé une question → écouter
                        log.info(f"💬 [{session_id[:8]}] Student asked a question")
                        # State est déjà LISTENING (detectable par VAD)
                    else:
                        # ✅ Pas de question → auto-avancer PRÉSENTATION
                        log.info(f"⏭️  [{session_id[:8]}] Auto-advancing to next slide")
                        if ctx:
                            await dialogue.transition(ctx.session_id, DialogState.PRESENTING)
                        await send({"type": "next_section"})
                        # Laisser le client gérer le chargement du slide suivant

                except Exception as pipeline_exc:
                    log.error(f"[{session_id[:8]}] Pipeline streaming error: {pipeline_exc}", exc_info=True)
                    await send({"type": "error", "message": f"Pipeline error: {str(pipeline_exc)[:100]}"})
                    await send_state(DialogState.LISTENING)

            # ── interrupt — l'étudiant coupe l'IA ─────────────────────
            elif msg_type == "interrupt":
                await cancel_presentation_task(notify_client=True)
                if ctx:
                    await dialogue.handle_interruption(ctx.session_id)
                    await dialogue.save_position(ctx.session_id, current_presentation_cursor)
                audio_buffer.clear()
                await cancel_audio_stream(notify_client=True)
                await set_listening_state()
                log.info(f"[{session_id[:8]}] ⚡ Interruption")

            # ── present_section — présenter une section de cours ─────
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
                    # ✅ Stocker le course_summary pour utilisation dans explain_slide_focused
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
                await send_state(DialogState.PRESENTING)

                requested_slide_key = (course_id or "", chapter_index_int, section_index_int)
                reuse_cached_narration = (
                    current_presentation_key == requested_slide_key
                    and 0 < current_presentation_cursor < len(current_presentation_text)
                )
                if not reuse_cached_narration:
                    current_presentation_text = ""
                    current_presentation_cursor = 0
                current_presentation_key = requested_slide_key
                resume_offset = current_presentation_cursor if reuse_cached_narration else 0

                # Envoyer la slide immédiatement avec ses métadonnées exactes.
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

                # Profil étudiant → adapter le débit (TODO: implement speech rate customization)
                try:
                    profile = await profile_mgr.get_or_create(session_id, lang_ps, session_level)
                    # ✅ Stocker profil pour timing adaptatif
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
                            try:
                                # ✅ Déterminer si c'est une reprise (pause/resume)
                                is_resuming = resume_offset > 0 and reuse_cached
                                
                                # ✅ Récupérer le course_summary depuis le contexte session
                                course_summary = ctx.course_summary if ctx else ""
                                
                                # ✅ NOUVEAU: Utiliser explain_slide_focused (strict + focused + level-adapted)
                                narration_text = await explain_slide_focused(
                                    slide_content=section_text or slide_content or content_txt,
                                    chapter_idx=chapter_index_int,
                                    chapter_title=chapter,
                                    section_title=section_title,
                                    language=lang_ps,
                                    student_level=session_level,
                                    course_summary=course_summary,  # ✅ NOUVEAU
                                    is_resume=is_resuming,  # ✅ NOUVEAU
                                    session_id=session_id,  # ✅ Pass session_id for rate limiting
                                )
                            except Exception:
                                # Fallback: brain.ask
                                narration_text, _ = brain.ask(section_text or content_txt, reply_language=lang_ps, session_id=session_id)  # ✅ Pass session_id
                                narration_text = brain._clean_for_speech(narration_text)
                            narration_text = narration_text.strip()
                            current_presentation_text = narration_text
                            llm_time = time.time() - llm_start
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
                            if not await send({"type": "answer_text", "text": narration_text, "subject": "course", "final": True}):
                                return
                            if not await send({"type": "stream_end", "stream_id": current_stream_id}):
                                return
                            await set_listening_state()
                            return

                        current_stream_id += 1
                        stream_id = current_stream_id
                        sentences = split_sentences_with_spans(remaining_text)
                        for sentence, start, end in sentences:
                            if not sentence.strip():
                                continue

                            if not await send({"type": "answer_text", "text": sentence, "partial": True}):
                                return

                            try:
                                audio_chunk, _, _, _, mime = await voice.generate_audio_async(
                                    sentence,
                                    language_code=lang_ps,
                                    rate=rate_override,
                                )
                            except TypeError:
                                audio_chunk, _, _, _, mime = await voice.generate_audio_async(
                                    sentence,
                                    language_code=lang_ps,
                                )

                            if audio_chunk:
                                await _stream_audio(audio_chunk, mime, stream_id)

                            current_presentation_cursor = min(len(narration_text), effective_resume + end)
                            if ctx:
                                await dialogue.save_position(ctx.session_id, current_presentation_cursor)

                            await asyncio.sleep(0)

                        current_presentation_cursor = len(narration_text)
                        if ctx:
                            await dialogue.save_position(ctx.session_id, current_presentation_cursor)

                        if not await send({"type": "answer_text", "text": narration_text, "subject": "course", "final": True}):
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
                        log.error(f"Erreur présentation streaming: {e}")
                        await send({"type": "error", "message": f"Erreur présentation: {str(e)}"})
                    finally:
                        nonlocal_presentation_task = presentation_task
                        if nonlocal_presentation_task is asyncio.current_task():
                            presentation_task = None

                # ✅ NOUVEAU: Enregistrer le moment où la présentation COMMENCE
                presentation_start_time = time.time()
                presentation_task = asyncio.create_task(
                    run_presentation(content_txt, resume_offset, reuse_cached_narration)
                )

            # ── text — question texte (depuis l'input HTML) ────────────
            elif msg_type == "text":
                # ✅ REFRESH ctx (peut être modifié par run_presentation)
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
                current_chapter_idx = chapter_index_int + 1 if chapter_index_int is not None else None

                if current_slide_context:
                    current_slide_content = (current_slide_context.get("content") or current_slide_content).strip()
                    current_chapter_title = current_slide_context.get("chapter_title") or current_chapter_title
                    current_section_title = current_slide_context.get("section_title") or current_section_title
                    current_chapter_idx = current_slide_context.get("chapter_order") or current_chapter_idx

                is_in_course = msg.get("in_course", in_course or bool(course_id))
                if is_in_course and content_lower in resume_triggers:
                    if ctx:
                        # ✅ BUG #4 FIX: Retrieve char_offset from paused_state
                        resumed_ctx = await dialogue.resume_session(ctx.session_id)
                        if resumed_ctx and resumed_ctx.paused_state.get("char_offset", 0) > 0:
                            # Restore cursor position from pause point
                            current_presentation_cursor = resumed_ctx.paused_state.get("char_offset", 0)
                            resume_offset = current_presentation_cursor
                            log.info(f"📍 [{ctx.session_id[:8]}] Resume TTS from char {current_presentation_cursor}")
                        await dialogue.transition(ctx.session_id, DialogState.PRESENTING)
                    await send_state(DialogState.PRESENTING)
                    await send({"type": "resume_course"})
                    continue

                lang   = detect_lang_text(content)
                subj   = detect_subject(content)
                
                # ✅ UPDATE STATE: Language Detection + Prosody (text: estimated)
                await send_state(
                    DialogState.PROCESSING, 
                    "stt_language_detection", 
                    {"language": lang},
                    {"language": lang}
                )
                
                await send_state(
                    DialogState.PROCESSING,
                    "prosody_analysis",
                    {"type": "text_question"},
                    {"speech_rate": len(content.split())}
                )
                
                # ✅ S29-32: DÉTECTION DE CONFUSION AUTOMATIQUE (généralise audio_pipeline)
                # Inclut: mots-clés, répétition, patterns d'historique + SEMANTIC (si brain fourni)
                # Pour questions texte, créer prosody estimé (pas de voix réelle)
                text_prosody = {
                    "speech_rate": len(content.split()),  # Approximation: un mot = 1 mpm
                    "hesitation_count": 0,  # Pas accessible en texte
                    "markers": [],
                    "confidence": 0.0,  # Pas de signal prosodique en texte
                }
                
                # ✅ Helper function to emit micro-states during confusion detection
                async def emit_confusion_micro_state(state_name: str, metrics: dict):
                    """Wrapper for sending confusion micro-states with proper state"""
                    if metrics and metrics != {}:
                        await send_state(DialogState.PROCESSING, state_name, {}, metrics)
                
                is_confused, confusion_reason, q_hash, confusion_count = await dialogue.detect_and_track_confusion(
                    session_id=session_id,
                    question_text=content,
                    language=lang,
                    history=history,  # ← Inclure l'historique pour pattern detection
                    brain=brain,      # ← NOUVEAU: Embeddings sémantiques
                    prosody=text_prosody,  # ← Pour questions texte: dummy/estimé
                    on_state_change=emit_confusion_micro_state,  # ✅ Pass callback for micro-states
                )
                
                # ✅ UPDATE STATE: RAG Search
                rag_start = time.time()
                await send_state(DialogState.PROCESSING, "rag_search", {}, {})
                
                chunks_with_scores = rag.retrieve_chunks(
                    content,
                    k=Config.RAG_NUM_RESULTS,
                    current_chapter_idx=current_chapter_idx,
                    strict_chapter=bool(current_chapter_idx),
                    course_id=course_id if course_id else None,  # ✅ Scoped RAG retrieval
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
                
                # ✅ UPDATE STATE: RAG Search Complete with Metrics
                await send_state(DialogState.PROCESSING, "rag_search", {}, {
                    "chunks_found": len(chunks_with_scores),
                    "avg_score": round(avg_score, 3),
                    "duration_ms": round(rag_time, 1),
                    "progress_pct": 35
                })

                # ✅ UPDATE STATE: Confusion Detection (if any)
                if is_confused:
                    await send_state(DialogState.PROCESSING, "confusion_detected", 
                                   {"reason": confusion_reason}, 
                                   {"confidence": 0.85 if is_confused else 0.1})

                llm_start   = time.time()
                
                # ✅ UPDATE STATE: LLM Thinking
                await send_state(DialogState.PROCESSING, "llm_thinking", 
                               {"chunks": len(chunks_with_scores)},
                               {"chunks_processed": len(chunks_with_scores), "progress_pct": 50})
                
                # ✅ TRY RAG + FALLBACK pour les questions texte (comme le streaming)
                # Construire le prompt : normal ou reformulation si confusion
                last_slide = ctx.last_slide_explained if ctx else ""
                
                if is_confused:
                    # Prompt spécial reformulation pour questions texte
                    question_for_llm = dialogue.build_confusion_prompt(
                        original_question=content,
                        reason=confusion_reason,
                        language=lang,
                        last_slide_content=last_slide,
                    )
                    log.info(f"[{session_id[:8]}] 📝 Prompt reformulation appliqué au LLM (texte)")
                else:
                    question_for_llm = content
                
                # ✅ STREAMING LLM WITH REAL-TIME METRICS
                ai_response = ""
                llm_confidence = 0.7
                chunk_count = 0
                tokens_generated = 0
                
                try:
                    # Use streaming version for real-time token metrics
                    async for chunk_text, full_text in rag.generate_final_answer_stream(
                        chunks_with_scores, question=question_for_llm, history=history, language=lang,
                        current_chapter_title=current_chapter_title,
                        current_section_title=current_section_title,
                    ):
                        ai_response = full_text
                        chunk_count += 1
                        tokens_generated = len(ai_response.split())  # Approximate token count
                        elapsed_ms = (time.time() - llm_start) * 1000
                        tokens_per_sec = (tokens_generated / elapsed_ms * 1000) if elapsed_ms > 0 else 0
                        
                        # ✅ UPDATE STATE: LLM Streaming with Real-Time Metrics
                        await send_state(DialogState.PROCESSING, "streaming_llm", 
                                       {"chunk": chunk_count, "text": chunk_text[:80]},
                                       {
                                           "tokens_generated": tokens_generated,
                                           "tokens_per_sec": round(tokens_per_sec, 1),
                                           "duration_ms": round(elapsed_ms, 1),
                                           "progress_pct": 55 + min(chunk_count * 5, 20)  # 55-75%
                                       })
                        
                except Exception as rag_exc:
                    # ✅ FALLBACK: Si OpenAI échoue (429, quota, etc), utiliser brain.ask() avec Ollama
                    log.warning(f"[{session_id[:8]}] ⚠️  RAG failed ({type(rag_exc).__name__}): {str(rag_exc)[:100]} → Fallback brain.ask()...")
                    try:
                        ai_response, _ = brain.ask(question_for_llm, reply_language=lang, session_id=session_id)
                        ai_response = brain._clean_for_speech(ai_response)
                        llm_confidence = 0.5  # Fallback confidence
                    except Exception as fallback_exc:
                        log.error(f"[{session_id[:8]}] ❌ Fallback also failed: {fallback_exc}")
                        ai_response = f"Je suis désolé, j'ai rencontré une erreur technique. Veuillez réessayer."
                        llm_confidence = 0.0
                
                llm_time = time.time() - llm_start

                history.append({"role": "user",      "content": content})
                history.append({"role": "assistant",  "content": ai_response})

                # ✅ UPDATE STATE: TTS Generation
                tts_start = time.time()
                num_chunks = max(1, len(ai_response) // 200)  # Estimate chunks
                await send_state(DialogState.PROCESSING, "tts_text_chunking", 
                               {"chunks_total": num_chunks},
                               {"progress_pct": 78})
                
                audio_bytes, tts_time, tts_engine, tts_voice, mime = \
                    await voice.generate_audio_async(ai_response, language_code=lang)
                
                # ✅ UPDATE STATE: TTS Generation Complete
                await send_state(DialogState.PROCESSING, "tts_generation", 
                               {"engine": tts_engine, "voice": tts_voice},
                               {
                                   "audio_bytes": len(audio_bytes) if audio_bytes else 0,
                                   "duration_ms": round(tts_time * 1000, 1),
                                   "progress_pct": 90
                               })

                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.RESPONDING)
                await send_state(DialogState.RESPONDING, "", {}, {"progress_pct": 95})

                await send({"type": "answer_text", "text": ai_response,
                            "subject": subj, "rag_chunks": len(chunks_with_scores)})

                if audio_bytes:
                    await send({
                        "type":  "audio_chunk",
                        "data":  base64.b64encode(audio_bytes).decode(),
                        "mime":  mime,
                        "final": True,
                    })

                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                await send_state(DialogState.LISTENING)

                if is_in_course:
                    await send({"type": "resume_course"})

                # ── Analytics & Recherche ─────────────────────────────────
                try:
                    transcript_searcher.index_interaction(
                        session_id=session_id, student_q=content,
                        teacher_a=ai_response, language=lang,
                        course_id="", subject=subj,
                    )
                    analytics_engine.record_interaction(
                        session_id=session_id, question=content,
                        answer=ai_response, stt_time=0,
                        llm_time=llm_time, tts_time=tts_time,
                        language=lang, subject=subj,
                    )
                    await profile_mgr.update_from_session(session_id, "qa")
                    record_session_event({
                        "session_id": session_id, "language": lang,
                        "llm_time":   round(llm_time, 2),
                        "tts_time":   round(tts_time, 2),
                        "total_time": round(llm_time + tts_time, 2),
                        "meets_kpi":  (llm_time + tts_time) < 5.0,
                        "subject":    subj,
                    })
                except Exception as _ae:
                    log.debug("analytics error: %s", _ae)

            # ── next_section — avancer dans le cours ──────────────────
            elif msg_type == "next_section":
                if ctx:
                    await dialogue.next_section(ctx.session_id)
                await send({"type": "section_changed", "direction": "next"})

            # ── record dashboard event ───────────────────────────────
            # (done after each complete interaction)

            # ── ping / keepalive ───────────────────────────────────────
            elif msg_type == "ping":
                await send({"type": "pong"})

    except WebSocketDisconnect:
        websocket_closed = True
        log.info(f"🔌 WebSocket déconnecté : {session_id[:8]}")
    except Exception as exc:
        log.error(f"❌ WebSocket error [{session_id[:8]}]: {exc}", exc_info=True)
        if not websocket_closed:
            try:
                await send({"type": "error", "message": str(exc)})
            except Exception:
                pass
    finally:
        await cancel_presentation_task(notify_client=False)
        await cancel_audio_stream(notify_client=False)


# ══════════════════════════════════════════════════════════════════════
#  ROUTES REST (compatibilité + ingestion)
# ══════════════════════════════════════════════════════════════════════

def get_http_session(request: Request) -> tuple[str, list]:
    sid = request.headers.get("X-Session-ID") or str(uuid.uuid4())
    if sid not in HTTP_SESSIONS:
        HTTP_SESSIONS[sid] = deque(maxlen=Config.MAX_HISTORY_TURNS * 2)
    return sid, list(HTTP_SESSIONS[sid])


@app.post("/session")
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
    
    log.info(f"✅ Session created: {session_id[:8]} with auth token")
    return {"session_id": session_id, "token": token}


@app.get("/")
async def root():
    return {"status": "running", "rag_ready": rag.is_ready,
            "tts": Config.TTS_PROVIDER, "model": Config.GPT_MODEL,
            "websocket": "ws://<host>:8000/ws/{session_id}"}


@app.get("/health")
async def health():
    return {
        "server":   "ok",
        "rag":      {"ready": rag.is_ready, **rag.get_stats()},
        "whisper":  Config.WHISPER_MODEL_SIZE,
        "llm":      Config.GPT_MODEL,
        "tts":      Config.TTS_PROVIDER,
        "sessions": len(HTTP_SESSIONS),
    }


@app.post("/ask")
async def ask_question(request: Request, question: str = Form(...), course_id: str | None = Form(None)):
    session_id, history = get_http_session(request)
    # ✅ course_id can be passed via form or headers
    if not course_id:
        course_id = request.headers.get("X-Course-ID")
    
    lang   = detect_lang_text(question)
    subj   = detect_subject(question)
    chunks_with_scores = rag.retrieve_chunks(question, k=Config.RAG_NUM_RESULTS, course_id=course_id)  # ✅ Pass course_id

    llm_start   = time.time()
    ai_response, llm_confidence = rag.generate_final_answer(
                    chunks_with_scores, question=question, history=history, language=lang,
    )
    llm_time    = time.time() - llm_start

    history.append({"role": "user",      "content": question})
    history.append({"role": "assistant", "content": ai_response})
    HTTP_SESSIONS[session_id] = deque(history, maxlen=Config.MAX_HISTORY_TURNS * 2)

    audio_bytes, tts_time, tts_engine, tts_voice, mime = \
        await voice.generate_audio_async(ai_response, language_code=lang)
    total_time = llm_time + tts_time

    return {
        "session_id": session_id,
        "question":   question,
        "answer":     ai_response,
        "audio":      base64.b64encode(audio_bytes).decode() if audio_bytes else None,
        "subject":    subj,
        "performance": {
            "llm_time":   round(llm_time,   2),
            "tts_time":   round(tts_time,   2),
            "total_time": round(total_time, 2),
        },
    }


@app.post("/ingest")
async def ingest_files(
    files:       list[UploadFile] = File(...),
    incremental: bool             = Form(True),
    course_id:   str | None       = Form(None),  # ✅ Allow specifying course_id for strict filtering
):
    """
    Upload et indexe des fichiers de cours dans la base vectorielle.
    
    - Utilise OpenAI embeddings (meilleure qualité)
    - Fallback HuggingFace si OpenAI indisponible
    - Ingestion asynchrone trackée par IngestionManager
    - course_id: UUID du cours (optionnel, pour filtrage strict par course)
    - Retour immédiat avec status
    """
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    upload_dir = Path("courses")
    upload_dir.mkdir(exist_ok=True)
    saved_paths = []

    for f in files:
        dest = upload_dir / f.filename
        dest.write_bytes(await f.read())
        saved_paths.append(str(dest))

    log.info(f"📤 Ingestion lancée ({len(saved_paths)} fichier(s)) — OpenAI embeddings avec fallback HuggingFace")
    if course_id:
        log.info(f"   📚 course_id={course_id}")

    # ✨ Lance l'ingestion en async et retour immédiat
    asyncio.create_task(
        _run_ingestion_background(
            saved_paths,
            incremental=incremental,
            domain="general",
            course="uploaded",
            course_id=course_id,
        )
    )

    return {
        "status": "ingestion_started",
        "files": [f.filename for f in files],
        "message": "Ingestion lancée en arrière-plan. Consultez /ingestion/status pour suivre la progression."
    }


async def _run_ingestion_background(
    file_paths: list[str],
    incremental: bool = False,
    domain: str = "general",
    course: str = "uploaded",
    course_id: str | None = None,  # ✅ Add course_id parameter
) -> None:
    """
    Fonction interne : ingestion asynchrone avec IngestionManager.
    Lance l'ingestion en arrière-plan et track la progression.
    """
    try:
        await ingestion_manager.start_ingestion(len(file_paths))
        
        # ✨ Utilise la RAG principale (OpenAI + fallback HuggingFace)
        # run_ingestion_pipeline_for_files n'est pas async, donc run en executor
        loop = asyncio.get_event_loop()
        
        ok = await loop.run_in_executor(
            None,
            lambda: rag.run_ingestion_pipeline_for_files(
                file_paths,
                domain=domain,
                course=course,
                course_id=course_id,  # ✅ Pass course_id to ingestion
                incremental=incremental,
            )
        )

        if ok:
            stats = rag.get_stats()
            total_chunks = stats.get("total_docs", 0)
            await ingestion_manager.complete_ingestion(total_chunks)
            log.info(f"✅ Ingestion complétée : {total_chunks} chunks indexés")
        else:
            await ingestion_manager.fail_ingestion("run_ingestion_pipeline_for_files returned False")
            log.error("❌ Ingestion échouée")

    except Exception as exc:
        await ingestion_manager.fail_ingestion(str(exc))
        log.error(f"❌ Erreur ingestion : {exc}")


@app.get("/rag/stats")
async def rag_stats():
    return rag.get_stats()


@app.get("/ingestion/status")
async def get_ingestion_status():
    """Endpoint pour tracker l'état d'ingestion en cours"""
    return await ingestion_manager.get_status()


@app.get("/debug/rag_test")
async def debug_rag_test(q: str = "explain this topic", k: int = 5):
    """
    DEBUG endpoint: Teste le RAG et affiche ce qu'il retriève.
    
    Returns:
        - Chunks avec confiances
        - Sources (pages, chapitres)
        - Status RAG
    
    Usage: GET /debug/rag_test?q=what%20is%20clustering&k=5
    """
    if not rag.is_ready:
        return {
            "error": "RAG not ready",
            "status": rag.get_status()
        }
    
    try:
        result = rag.debug_retrieve(q, k=k)
        return {
            "status": "ok",
            "debug_data": result,
            "rag_status": rag.get_status()
        }
    except Exception as exc:
        log.error(f"Debug RAG error: {exc}")
        return {"error": str(exc), "status": rag.get_status()}


@app.get("/cache/stats")
async def cache_stats():
    """
    Endpoint pour voir les stats du cache d'embeddings.
    
    Returns:
        - cache_hits: Nombre de fois où le cache a retourn un embedding
        - cache_misses: Nombre de fois où il fallait calculer l'embedding
        - hit_rate_percent: Pourcentage de cache hits (objectif: > 60%)
        - redis_available: Si Redis est dispo pour le cache chaud
    
    Usage: GET /cache/stats
    """
    from modules.embedding_cache import embedding_cache
    
    stats = embedding_cache.stats()
    rag_stats = rag.get_stats()
    
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
            "redis_tip": "Assurez-vous que Redis est running: `redis-cli ping`"
        }
    }


@app.get("/session/{session_id}")
async def get_session_info(session_id: str):
    ctx = await dialogue.get_session(session_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Session introuvable")
    return await dialogue.get_stats(session_id)


@app.post("/session/clear")
async def clear_session(request: Request):
    sid = request.headers.get("X-Session-ID", "")
    if sid and sid in HTTP_SESSIONS:
        HTTP_SESSIONS[sid].clear()
    if sid:
        await dialogue.end_session(sid)
    return {"status": "cleared", "session_id": sid}


# ══════════════════════════════════════════════════════════════════════
#  ROUTES RECHERCHE HISTORIQUE
# ══════════════════════════════════════════════════════════════════════

@app.get("/search/transcripts")
async def search_transcripts(q: str, language: str = "", course_id: str = "",
                              role: str = "", limit: int = 20):
    """Recherche full-text dans l'historique des transcriptions."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Paramètre 'q' requis")
    results = transcript_searcher.search(q, language=language,
                                        course_id=course_id, role=role, limit=limit)
    return {"query": q, "count": len(results), "results": results}

@app.get("/search/session/{session_id}")
async def get_session_transcript(session_id: str):
    """Retourne l'historique complet d'une session."""
    history = transcript_searcher.get_session_history(session_id)
    return {"session_id": session_id, "count": len(history), "history": history}

@app.get("/search/stats")
async def search_stats():
    """Statistiques sur l'index de recherche."""
    return transcript_searcher.get_stats()


# ══════════════════════════════════════════════════════════════════════
#  ROUTES ANALYTICS (ClickHouse)
# ══════════════════════════════════════════════════════════════════════

@app.get("/analytics/report")
async def analytics_report():
    """Rapport analytics complet."""
    return analytics_engine.full_report()

@app.get("/analytics/kpi")
async def analytics_kpi(hours: int = 24):
    """KPIs sur les N dernières heures."""
    return analytics_engine.kpi_summary(hours=hours)

@app.get("/analytics/progression/{course_id}")
async def analytics_progression(course_id: str):
    """Progression des sections pour un cours."""
    return {
        "course_id":   course_id,
        "progression": analytics_engine.progression_by_course(course_id),
    }

@app.get("/analytics/latency")
async def analytics_latency():
    """Distribution des latences (min/avg/max/p95)."""
    return analytics_engine.latency_distribution()


# ══════════════════════════════════════════════════════════════════════
#  ROUTES MEDIA STORAGE (MinIO / local)
# ══════════════════════════════════════════════════════════════════════

@app.get("/media/{path:path}")
async def serve_media(path: str):
    """Sert les fichiers média stockés localement."""
    from fastapi.responses import FileResponse
    from modules.media_storage import LOCAL_MEDIA_DIR
    file_path = LOCAL_MEDIA_DIR / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    return FileResponse(str(file_path))

@app.get("/media-list")
async def list_media(prefix: str = ""):
    """Liste les fichiers médias disponibles."""
    objects = media_storage.list_objects(prefix)
    return {"count": len(objects), "objects": objects[:100]}


# ══════════════════════════════════════════════════════════════════════
#  ROUTES PROFIL ÉTUDIANT
# ══════════════════════════════════════════════════════════════════════

@app.get("/profile/{student_id}")
async def get_student_profile(student_id: str):
    """Retourne le profil d'un étudiant."""
    profile = await profile_mgr.get_or_create(student_id)
    from dataclasses import asdict
    return asdict(profile)

@app.post("/profile/{student_id}/reset")
async def reset_student_profile(student_id: str):
    """Remet à zéro le profil d'un étudiant."""
    from modules.student_profile import StudentProfile
    profile = StudentProfile(student_id=student_id)
    await profile_mgr.save(profile)
    return {"status": "reset", "student_id": student_id}


# ══════════════════════════════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════════════════════════════


@app.post("/course/build")
async def build_course(
    files:    list[UploadFile] = File(...),
    language: str              = Form("fr"),
    level:    str              = Form("lycée"),
    domain:   str              = Form("general"),  # 🎯 Domaine (general, informatique, etc.)
):
    """
    Upload un PDF/DOCX → le structure en cours présentable.
    Sauvegarde dans PostgreSQL et RAG. Génère les PNG slides.
    """
    from modules.course_builder import CourseBuilder
    from database.init_db import AsyncSessionLocal

    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    upload_dir = Path("courses")
    upload_dir.mkdir(exist_ok=True)

    results = []
    files_to_index: list[tuple[str, str | None]] = []  # ✅ Store (file_path, course_id) tuples
    builder = CourseBuilder()

    for f in files:
        dest = upload_dir / f.filename
        dest.write_bytes(await f.read())

        try:
            # 1. Construire le cours de façon directe, page par page
            course_data = await builder.build_from_file_direct(
                str(dest), language=language, level=level, domain=domain
            )

            course_id = None
            db_error = None
            try:
                # 2. Sauvegarder dans PostgreSQL si disponible
                async with AsyncSessionLocal() as db:
                    course_id = await builder.save_to_database(course_data, db, domain=domain)
            except Exception as exc:
                db_error = str(exc)
                log.info(f"ℹ️ PostgreSQL indisponible pour {f.filename}: {exc}")

            # ✅ Store (file_path, course_id) for indexing
            files_to_index.append((str(dest), course_id))

            chapters  = len(course_data.get("chapters", []))
            sections  = sum(len(ch.get("sections", [])) for ch in course_data.get("chapters", []))

            results.append({
                "file":      f.filename,
                "course_id": course_id,
                "title":     course_data.get("title"),
                "chapters":  chapters,
                "sections":  sections,
                "domain":    domain,
                "status":    "ok" if db_error is None else "partial",
                "db_error":  db_error,
            })

        except Exception as exc:
            log.error(f"❌ Build course failed for {f.filename}: {exc}")
            results.append({"file": f.filename, "status": "error", "error": str(exc)})

    if files_to_index:
        log.info(f"📤 Ingestion RAG batch lancée pour {len(files_to_index)} fichier(s)")
        # ✅ Ingest each file with its corresponding course_id
        for file_path, course_id in files_to_index:
            log.info(f"   📚 Indexing {Path(file_path).name} with course_id={course_id}")
            rag_ok = rag.run_ingestion_pipeline_for_files(
                [file_path],
                domain=domain,
                course="uploaded_course",
                course_id=course_id,
                incremental=True,
            )
            if not rag_ok:
                log.info(f"ℹ️ Ingestion RAG terminée sans indexation vectorielle pour {file_path}")

    return {"results": results, "rag_stats": rag.get_stats()}


@app.get("/course/list")
async def list_courses():
    """Liste tous les cours disponibles dans PostgreSQL."""
    try:
        from database.init_db import AsyncSessionLocal
        from database.crud import get_all_courses
        async with AsyncSessionLocal() as db:
            courses = await get_all_courses(db)
            return {
                "courses": [
                    {
                        "id":       str(c.id),
                        "title":    c.title,
                        "subject":  c.subject,
                        "language": c.language,
                        "level":    c.level,
                    }
                    for c in courses
                ]
            }
    except Exception as exc:
        return {"courses": [], "error": str(exc)}


@app.get("/course/{course_id}/structure")
async def get_course_structure(course_id: str):
    """Retourne la structure complète d'un cours (chapitres + sections + PNG slides)."""
    try:
        from database.init_db import AsyncSessionLocal
        from database.crud import get_course_with_structure
        import uuid
        
        async with AsyncSessionLocal() as db:
            course = await get_course_with_structure(db, uuid.UUID(course_id))
            if not course:
                raise HTTPException(status_code=404, detail="Cours introuvable")
            
            # 🎨 Récupérer les slides depuis les sections (image_url)
            slides = []
            chapters_data = []
            
            for ch in course.chapters:
                sections_data = []
                for sec in ch.sections:
                    # Chaque section a son PNG path dans image_url
                    slide_path = sec.image_url or (sec.image_urls[0] if getattr(sec, "image_urls", None) else "")
                    if slide_path:
                        slides.append(slide_path)
                    
                    sections_data.append({
                        "title":      sec.title,
                        "order":      sec.order,
                        "duration_s": sec.duration_s,
                        "image_url":  slide_path,  # 🎨 PNG de cette slide
                        "content":    sec.content or "",    # Texte OCR pour LLM
                        "concepts":   [
                            {"term": c.term, "definition": c.definition}
                            for c in sec.concepts
                        ],
                    })
                
                chapters_data.append({
                    "title": ch.title,
                    "order": ch.order,
                    "sections": sections_data,
                })
            
            return {
                "id":       str(course.id),
                "title":    course.title,
                "subject":  course.subject,
                "domain":   course.domain or "general",  # 🎯 Domaine du cours
                "language": course.language,
                "level":    course.level,
                "file_path": course.file_path or "",
                "slides":   slides,  # 🎨 Liste des PNG pour l'affichage
                "chapters": chapters_data,
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

if __name__ == "__main__":
    import uvicorn
    log.info("")
    log.info("🌐 Interface UI       : http://localhost:" + str(Config.SERVER_PORT) + "/static/index.html")
    log.info("📚 Swagger Docs       : http://localhost:" + str(Config.SERVER_PORT) + "/docs")
    log.info("🔌 WebSocket tunnels  : ws://localhost:" + str(Config.SERVER_PORT) + "/ws/{session_id}")
    log.info("")
    log.info("✅ Serveur actif — Appuyez sur Ctrl+C pour arrêter")
    log.info("")
    uvicorn.run(app, host=Config.SERVER_HOST, port=Config.SERVER_PORT, reload=False)


# ══════════════════════════════════════════════════════════════════════
#  ROUTES COURS — Construction + Présentation
# ══════════════════════════════════════════════════════════════════════
