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
║  Routes REST (compatibilité) :                                       ║
║    POST /process-audio     — pipeline vocal (HTTP)                  ║
║    POST /ask               — texte → réponse                        ║
║    POST /ingest            — indexer des fichiers dans le RAG       ║
║    GET  /rag/stats         — statistiques RAG                       ║
║    GET  /session/{id}      — état de la session                     ║
║    GET  /health            — healthcheck complet                    ║
║                                                                      ║
║  Messages WebSocket (client → serveur) :                            ║
║    {"type": "start_session",  "language": "fr", "level": "lycée"}  ║
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
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, Request, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langdetect import detect

from config import Config
from modules.transcriber    import Transcriber
from modules.llm            import Brain
from modules.tts            import VoiceEngine
from modules.multimodal_rag import MultiModalRAG
from modules.logger         import CsvLogger
from modules.stt_logger     import STTLogger
from modules.dialogue       import DialogueManager, DialogState, SessionContext
from modules.voice_navigator import VoiceNavigator, NavCommand
from modules.student_profile import ProfileManager
from modules.slide_sync      import SlideSynchronizer
from modules.dashboard       import router as dashboard_router, record_session_event
from modules.media_storage   import get_storage
from modules.transcript_search import get_searcher, TranscriptEntry
from modules.analytics       import get_analytics
from modules.jitsi_webrtc    import JitsiRoomManager, WebRTCAudioConfig
from modules.speech_rate     import get_speech_adapter
from database.init_db       import create_tables, get_db
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

Config.validate()

transcriber = Transcriber()
brain       = Brain()
voice       = VoiceEngine()
rag         = MultiModalRAG(db_dir=Config.RAG_DB_DIR)
csv_logger  = CsvLogger()
stt_logger  = STTLogger()
dialogue    = DialogueManager()
voice_nav     = VoiceNavigator()
profile_mgr   = ProfileManager()
slide_sync    = SlideSynchronizer()
media_storage = get_storage()
transcript_searcher = get_searcher()
analytics_engine    = get_analytics()
speech_adapter      = get_speech_adapter()
jitsi_manager       = JitsiRoomManager()

# Sessions HTTP (fallback si Redis indisponible)
HTTP_SESSIONS: dict[str, deque] = {}

log.info("✅ Modules prêts\n")


# ══════════════════════════════════════════════════════════════════════
#  UTILITAIRES COMMUNS
# ══════════════════════════════════════════════════════════════════════

def detect_lang_text(text: str) -> str:
    try:
        code = detect(text)
        if code.startswith("fr"): return "fr"
        if code.startswith("ar"): return "ar"
        if code.startswith("tr"): return "tr"
        return "en"
    except Exception:
        return "en"


def audio_bytes_to_numpy(audio_bytes: bytes) -> np.ndarray:
    try:
        data, sr = sf.read(io.BytesIO(audio_bytes))
        if len(data.shape) > 1:
            data = data.mean(axis=1)
        if sr != Config.SAMPLE_RATE:
            import librosa
            data = librosa.resample(data, orig_sr=sr, target_sr=Config.SAMPLE_RATE)
        return data.astype(np.float32)
    except Exception:
        pass
    try:
        from pydub import AudioSegment
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(audio_bytes)
            path = tmp.name
        try:
            seg = (AudioSegment.from_file(path)
                   .set_frame_rate(Config.SAMPLE_RATE)
                   .set_channels(1).set_sample_width(2))
            samples = np.frombuffer(seg.raw_data, dtype=np.int16)
            return (samples / 32768.0).astype(np.float32)
        finally:
            os.unlink(path)
    except Exception as exc:
        raise RuntimeError(f"Audio conversion failed: {exc}")


_SUBJECT_KW = {
    "math":      ["math","équation","algèbre","calcul","dérivée","intégrale",
                  "géométrie","vecteur","matrice","algebra","equation","حساب","معادلة"],
    "biology":   ["bio","cell","cellule","adn","évolution","photosynthèse","بيولوجيا"],
    "physics":   ["physique","force","énergie","vitesse","mécanique","فيزياء"],
    "chemistry": ["chimie","molécule","atome","réaction","كيمياء"],
    "history":   ["histoire","guerre","révolution","تاريخ"],
    "geography": ["géographie","pays","continent","جغرافيا"],
    "cs":        ["algorithme","code","programmation","python","informatique","برمجة"],
    "economics": ["économie","marché","finance","اقتصاد"],
}

def detect_subject(text: str) -> str | None:
    t = text.lower()
    for subj, kws in _SUBJECT_KW.items():
        if any(k in t for k in kws):
            return subj
    return None


# ══════════════════════════════════════════════════════════════════════
#  PIPELINE VOCAL CENTRAL
# ══════════════════════════════════════════════════════════════════════

async def run_pipeline(
    audio_data: np.ndarray,
    session_id: str,
    history:    list,
) -> dict:
    """
    Pipeline complet : audio numpy → réponse JSON.
    Partagé par WebSocket ET REST /process-audio.
    """
    total_start = time.time()
    utt_id      = str(uuid.uuid4())[:8]

    # ── 1. STT ────────────────────────────────────────────────────────
    text, stt_time, lang, lang_prob, audio_duration = transcriber.transcribe(audio_data)
    if not text or len(text.strip()) <= 2:
        return {"error": "Aucune parole détectée"}

    stt_logger.log(
        session_id=session_id, utt_id=utt_id,
        audio_duration_sec=audio_duration,
        language_detected=lang, language_prob=lang_prob,
        stt_time=stt_time, transcription_text=text,
    )

    # ── 2. RAG ────────────────────────────────────────────────────────
    subject = detect_subject(text)
    chunks  = rag.retrieve_chunks(text, k=Config.RAG_NUM_RESULTS, subject=subject)

    # ── 3. Détection confusion ────────────────────────────────────────
    if dialogue.detect_confusion(text, lang):
        log.info(f"[{session_id[:8]}] 🤔 Confusion détectée — reformulation")

    # ── 4. LLM ────────────────────────────────────────────────────────
    llm_start   = time.time()
    ai_response = rag.generate_final_answer(
        chunks, query=text, history=history, language=lang,
    )
    llm_time = time.time() - llm_start

    # Mise à jour mémoire
    history.append({"role": "user",      "content": text})
    history.append({"role": "assistant", "content": ai_response})
    if len(history) > Config.MAX_HISTORY_TURNS * 2:
        history[:] = history[2:]

    # ── 5. TTS ────────────────────────────────────────────────────────
    audio_bytes, tts_time, tts_engine, tts_voice, mime = \
        await voice.generate_audio_async(ai_response, language_code=lang)

    total_time = time.time() - total_start
    kpi_ok     = total_time <= Config.MAX_RESPONSE_TIME

    # ── 6. Logging ────────────────────────────────────────────────────
    csv_logger.log_turn(
        audio_duration_sec=audio_duration,
        stt_time=stt_time, llm_time=llm_time,
        tts_time=tts_time, total_time=total_time,
        language=lang,
        model_used=Config.WHISPER_MODEL_SIZE,
        tts_engine_used=tts_engine, tts_model_used=tts_voice,
        session_id=session_id, transcription=text,
    )

    log.info(
        f"[{session_id[:8]}] ✅ STT={stt_time:.2f}s LLM={llm_time:.2f}s "
        f"TTS={tts_time:.2f}s TOTAL={total_time:.2f}s {'✅' if kpi_ok else '⚠️'}"
    )

    return {
        "transcription": {"text": text, "language": lang, "confidence": round(lang_prob, 2)},
        "answer":        ai_response,
        "audio_bytes":   audio_bytes,
        "audio_b64":     base64.b64encode(audio_bytes).decode() if audio_bytes else None,
        "mime":          mime,
        "subject":       subject,
        "rag_chunks":    len(chunks),
        "performance": {
            "stt_time":   round(stt_time,   2),
            "llm_time":   round(llm_time,   2),
            "tts_time":   round(tts_time,   2),
            "total_time": round(total_time, 2),
            "kpi_ok":     kpi_ok,
        },
    }


# ══════════════════════════════════════════════════════════════════════
#  APPLICATION FASTAPI
# ══════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Smart Teacher API",
    description="Professeur IA Vocal — WebSocket + REST | STT+RAG+LLM+TTS",
    version="3.0.0",
)

if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(dashboard_router)


@app.on_event("startup")
async def startup():
    """Initialise la base de données au démarrage."""
    try:
        await create_tables()
        log.info("✅ PostgreSQL tables prêtes")
    except Exception as exc:
        log.warning(f"⚠️ PostgreSQL indisponible : {exc} (mode dégradé)")


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

    async def send(data: dict):
        await websocket.send_json(data)

    async def send_state(state: DialogState):
        await send({"type": "state_change", "state": state.value})

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")

            # ── start_session ─────────────────────────────────────────
            if msg_type == "start_session":
                lang  = msg.get("language", "fr")
                level = msg.get("level",    "lycée")
                ctx   = await dialogue.create_session(
                    session_id=session_id,
                    language=lang,
                    student_level=level,
                )
                session_lang  = lang
                session_level = level
                history.clear()

                await send({"type": "session_ready", "session_id": ctx.session_id})
                await send_state(DialogState.LISTENING)
                log.info(f"[{session_id[:8]}] 🚀 Session démarrée | lang={lang} level={level}")

            # ── audio_chunk — accumule les données audio ───────────────
            elif msg_type == "audio_chunk":
                raw = msg.get("data", "")
                if raw:
                    audio_buffer.append(base64.b64decode(raw))

            # ── audio_end — traite l'audio accumulé ───────────────────
            elif msg_type == "audio_end":
                if not audio_buffer:
                    await send({"type": "error", "message": "Aucun audio reçu"})
                    continue

                # Assembler et convertir l'audio
                full_audio = b"".join(audio_buffer)
                audio_buffer.clear()

                try:
                    audio_np = audio_bytes_to_numpy(full_audio)
                except RuntimeError as exc:
                    await send({"type": "error", "message": str(exc)})
                    continue

                # Transition → PROCESSING
                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.PROCESSING)
                await send_state(DialogState.PROCESSING)

                # Lancer le pipeline
                result = await run_pipeline(audio_np, session_id, history)

                if "error" in result:
                    await send({"type": "error", "message": result["error"]})
                    await send_state(DialogState.LISTENING)
                    continue

                # Envoyer la transcription
                t = result["transcription"]
                await send({"type": "transcription", "text": t["text"],
                            "lang": t["language"], "confidence": t["confidence"]})

                # Transition → RESPONDING
                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.RESPONDING)
                await send_state(DialogState.RESPONDING)

                # Envoyer le texte de la réponse
                await send({"type": "answer_text", "text": result["answer"],
                            "subject": result["subject"], "rag_chunks": result["rag_chunks"]})

                # Envoyer l'audio TTS en chunks
                if result["audio_bytes"]:
                    chunk_size = 4096
                    audio_data = result["audio_bytes"]
                    for i in range(0, len(audio_data), chunk_size):
                        chunk = audio_data[i:i + chunk_size]
                        await send({
                            "type":  "audio_chunk",
                            "data":  base64.b64encode(chunk).decode(),
                            "mime":  result["mime"],
                            "final": (i + chunk_size) >= len(audio_data),
                        })

                # Envoyer les métriques
                await send({"type": "performance", **result["performance"]})

                # Retour en LISTENING
                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                await send_state(DialogState.LISTENING)

            # ── interrupt — l'étudiant coupe l'IA ─────────────────────
            elif msg_type == "interrupt":
                if ctx:
                    await dialogue.handle_interruption(ctx.session_id)
                audio_buffer.clear()
                await send_state(DialogState.LISTENING)
                log.info(f"[{session_id[:8]}] ⚡ Interruption")

            # ── present_section — présenter une section de cours ─────
            elif msg_type == "present_section":
                content_txt   = msg.get("content", "").strip()
                slide_title   = msg.get("slide_title",   "")
                slide_content = msg.get("slide_content", "")
                keywords      = msg.get("keywords",      [])
                chapter       = msg.get("chapter",       "")
                progress_pct  = msg.get("progress_pct",  0)
                lang_ps       = msg.get("language", session_lang)
                in_course     = True

                if not content_txt:
                    continue

                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.PRESENTING)
                await send_state(DialogState.PRESENTING)

                # Envoyer la slide IMMÉDIATEMENT (avant l'audio)
                await send({
                    "type":          "slide_update",
                    "slide_title":   slide_title or content_txt[:60],
                    "slide_content": slide_content or content_txt[:200],
                    "keywords":      keywords,
                    "chapter":       chapter,
                    "progress_pct":  progress_pct,
                    "slide_index":   0,
                })

                # Profil étudiant → adapter le débit
                try:
                    profile = await profile_mgr.get_or_create(session_id, lang_ps, session_level)
                    speech_cfg = speech_adapter.get_config(
                        language=lang_ps, level=session_level,
                        confusion_count=profile.confusion_count,
                        asks_repeat=profile.asks_repeat,
                    )
                    rate_override = speech_cfg.rate
                except Exception:
                    rate_override = "+0%"

                # LLM : présentation pédagogique naturelle
                llm_start = time.time()
                try:
                    ai_resp, _ = brain.present(content_txt, language=lang_ps, student_level=session_level)
                except Exception:
                    ai_resp_raw, _ = brain.ask(content_txt, reply_language=lang_ps)
                    ai_resp = brain._clean_for_speech(ai_resp_raw)
                llm_time = time.time() - llm_start

                # TTS avec débit adapté
                try:
                    audio_bytes, tts_time, tts_engine, tts_voice, mime =                         await voice.generate_audio_async(
                            ai_resp, language_code=lang_ps, rate=rate_override
                        )
                except TypeError:
                    # fallback si rate non supporté
                    audio_bytes, tts_time, tts_engine, tts_voice, mime =                         await voice.generate_audio_async(ai_resp, language_code=lang_ps)

                await send({"type": "answer_text", "text": ai_resp, "subject": "course"})

                # Envoyer audio en chunks
                if audio_bytes:
                    chunk_size = 4096
                    for i in range(0, len(audio_bytes), chunk_size):
                        chunk = audio_bytes[i:i + chunk_size]
                        await send({
                            "type":  "audio_chunk",
                            "data":  base64.b64encode(chunk).decode(),
                            "mime":  mime,
                            "final": (i + chunk_size) >= len(audio_bytes),
                        })

                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.LISTENING)
                await send_state(DialogState.LISTENING)

                # Analytics
                try:
                    analytics_engine.record_section(
                        session_id=session_id, course_id="",
                        chapter_idx=0, section_idx=0,
                        event_type="section_start", language=lang_ps,
                    )
                except Exception:
                    pass

            # ── text — question texte (depuis l'input HTML) ────────────
            elif msg_type == "text":
                content = msg.get("content", "").strip()
                if not content:
                    continue

                # Détecter commande vocale de navigation
                nav = voice_nav.detect(content, session_lang)
                if nav.command != NavCommand.NONE:
                    nav_response = voice_nav.get_response(nav.command, session_lang)
                    if nav_response:
                        aud, _, _, _, mime2 = await voice.generate_audio_async(nav_response, language_code=session_lang)
                        await send({"type": "answer_text", "text": nav_response, "subject": "navigation"})
                        if aud:
                            await send({"type": "audio_chunk",
                                        "data": base64.b64encode(aud).decode(),
                                        "mime": mime2, "final": True})
                    await send({"type": "nav_command", "command": nav.command.value,
                                "topic": nav.topic})
                    continue

                lang   = detect_lang_text(content)
                subj   = detect_subject(content)
                chunks = rag.retrieve_chunks(content, k=Config.RAG_NUM_RESULTS, subject=subj)

                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.PROCESSING)
                await send_state(DialogState.PROCESSING)

                llm_start   = time.time()
                ai_response = rag.generate_final_answer(
                    chunks, query=content, history=history, language=lang,
                )
                llm_time = time.time() - llm_start

                history.append({"role": "user",      "content": content})
                history.append({"role": "assistant",  "content": ai_response})

                audio_bytes, tts_time, tts_engine, tts_voice, mime = \
                    await voice.generate_audio_async(ai_response, language_code=lang)

                if ctx:
                    await dialogue.transition(ctx.session_id, DialogState.RESPONDING)
                await send_state(DialogState.RESPONDING)

                await send({"type": "answer_text", "text": ai_response,
                            "subject": subj, "rag_chunks": len(chunks)})

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

                # ── Si en cours : envoyer signal de reprise ───────────────
                is_in_course = msg.get("in_course", in_course)
                if is_in_course:
                    # Vérification de compréhension avant de reprendre
                    check_phrases = {
                        "fr": "C'est clair pour toi ? On peut continuer ?",
                        "ar": "هل الأمر واضح؟ هل نكمل؟",
                        "en": "Is that clear? Shall we continue?",
                        "tr": "Anlaşıldı mı? Devam edelim mi?",
                    }
                    check_q = check_phrases.get(session_lang, check_phrases["fr"])
                    check_audio, _, _, _, check_mime =                         await voice.generate_audio_async(check_q, language_code=session_lang)
                    await send({"type": "answer_text", "text": check_q, "subject": "comprehension"})
                    if check_audio:
                        await send({
                            "type": "audio_chunk",
                            "data": base64.b64encode(check_audio).decode(),
                            "mime": check_mime, "final": True,
                        })
                    await send({"type": "waiting_comprehension"})

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
        log.info(f"🔌 WebSocket déconnecté : {session_id[:8]}")
    except Exception as exc:
        log.error(f"❌ WebSocket error [{session_id[:8]}]: {exc}", exc_info=True)
        try:
            await send({"type": "error", "message": str(exc)})
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
#  ROUTES REST (compatibilité + ingestion)
# ══════════════════════════════════════════════════════════════════════

def get_http_session(request: Request) -> tuple[str, list]:
    sid = request.headers.get("X-Session-ID") or str(uuid.uuid4())
    if sid not in HTTP_SESSIONS:
        HTTP_SESSIONS[sid] = deque(maxlen=Config.MAX_HISTORY_TURNS * 2)
    return sid, list(HTTP_SESSIONS[sid])


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


@app.post("/process-audio")
async def process_audio(request: Request, audio: UploadFile = File(...)):
    session_id, history = get_http_session(request)
    audio_bytes = await audio.read()
    try:
        audio_np = audio_bytes_to_numpy(audio_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = await run_pipeline(audio_np, session_id, history)

    if "error" in result:
        return JSONResponse(status_code=400, content=result)

    # Mettre à jour la session HTTP
    HTTP_SESSIONS[session_id] = deque(history, maxlen=Config.MAX_HISTORY_TURNS * 2)

    return {
        "session_id":    session_id,
        "transcription": result["transcription"],
        "answer":        result["answer"],
        "audio":         result["audio_b64"],
        "subject":       result["subject"],
        "rag_chunks":    result["rag_chunks"],
        "performance":   result["performance"],
    }


@app.post("/ask")
async def ask_question(request: Request, question: str = Form(...)):
    session_id, history = get_http_session(request)
    lang   = detect_lang_text(question)
    subj   = detect_subject(question)
    chunks = rag.retrieve_chunks(question, k=Config.RAG_NUM_RESULTS, subject=subj)

    llm_start   = time.time()
    ai_response = rag.generate_final_answer(
        chunks, query=question, history=history, language=lang,
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
    incremental: bool             = Form(False),
):
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    upload_dir = Path("courses")
    upload_dir.mkdir(exist_ok=True)
    saved_paths = []

    for f in files:
        dest = upload_dir / f.filename
        dest.write_bytes(await f.read())
        saved_paths.append(str(dest))

    ok = rag.run_ingestion_pipeline_for_files(saved_paths, incremental=incremental)
    if not ok:
        raise HTTPException(status_code=500, detail="Ingestion échouée")

    return {"status": "ok", "files": [f.filename for f in files],
            "rag_stats": rag.get_stats()}


@app.get("/rag/stats")
async def rag_stats():
    return rag.get_stats()


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
#  ROUTES JITSI / WEBRTC
# ══════════════════════════════════════════════════════════════════════

@app.get("/jitsi/room/{session_id}")
async def get_jitsi_room(session_id: str):
    """Crée/récupère la salle Jitsi pour une session."""
    room_info   = jitsi_manager.create_room(session_id)
    jitsi_cfg   = WebRTCAudioConfig.get_jitsi_config(
        room_info["room_name"], room_info["domain"], room_info.get("jwt_token")
    )
    audio_constr = WebRTCAudioConfig.get_constraints()
    return {
        **room_info,
        "jitsi_config":    jitsi_cfg,
        "audio_constraints": audio_constr,
    }

@app.get("/jitsi/config")
async def jitsi_config():
    """Retourne la config Jitsi globale (domaine, options)."""
    from modules.jitsi_webrtc import JITSI_DOMAIN
    return {
        "domain":       JITSI_DOMAIN,
        "self_hosted":  os.getenv("JITSI_SELF_HOSTED", "false"),
        "has_jwt":      bool(os.getenv("JITSI_APP_ID")),
        "sdk_url":      f"https://{JITSI_DOMAIN}/external_api.js",
        "audio_constraints": WebRTCAudioConfig.get_constraints(),
    }


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
):
    """
    Upload un PDF/DOCX → GPT le structure en cours présentable.
    Sauvegarde dans PostgreSQL et RAG.
    """
    from modules.course_builder import CourseBuilder
    from database.init_db import AsyncSessionLocal

    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    upload_dir = Path("courses")
    upload_dir.mkdir(exist_ok=True)

    results = []
    builder = CourseBuilder()

    for f in files:
        dest = upload_dir / f.filename
        dest.write_bytes(await f.read())

        try:
            # 1. Construire le cours structuré avec GPT
            course_data = await builder.build_from_file(
                str(dest), language=language, level=level
            )

            # 2. Sauvegarder dans PostgreSQL
            async with AsyncSessionLocal() as db:
                course_id = await builder.save_to_database(course_data, db)

            # 3. Indexer dans Qdrant (RAG)
            rag.run_ingestion_pipeline_for_files([str(dest)], incremental=True)

            chapters  = len(course_data.get("chapters", []))
            sections  = sum(len(ch.get("sections", [])) for ch in course_data.get("chapters", []))

            results.append({
                "file":      f.filename,
                "course_id": course_id,
                "title":     course_data.get("title"),
                "chapters":  chapters,
                "sections":  sections,
                "status":    "ok",
            })

        except Exception as exc:
            log.error(f"❌ Build course failed for {f.filename}: {exc}")
            results.append({"file": f.filename, "status": "error", "error": str(exc)})

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
    """Retourne la structure complète d'un cours (chapitres + sections)."""
    try:
        from database.init_db import AsyncSessionLocal
        from database.crud import get_course_with_structure
        import uuid
        async with AsyncSessionLocal() as db:
            course = await get_course_with_structure(db, uuid.UUID(course_id))
            if not course:
                raise HTTPException(status_code=404, detail="Cours introuvable")
            return {
                "id":       str(course.id),
                "title":    course.title,
                "subject":  course.subject,
                "language": course.language,
                "level":    course.level,
                "chapters": [
                    {
                        "title": ch.title,
                        "order": ch.order,
                        "sections": [
                            {
                                "title":      sec.title,
                                "order":      sec.order,
                                "duration_s": sec.duration_s,
                                "concepts":   [
                                    {"term": c.term, "definition": c.definition}
                                    for c in sec.concepts
                                ],
                            }
                            for sec in ch.sections
                        ],
                    }
                    for ch in course.chapters
                ],
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

if __name__ == "__main__":
    import uvicorn
    log.info(f"🌐 http://localhost:{Config.SERVER_PORT}/static/index.html")
    log.info(f"📚 Docs : http://localhost:{Config.SERVER_PORT}/docs")
    log.info(f"🔌 WS   : ws://localhost:{Config.SERVER_PORT}/ws/{{session_id}}")
    uvicorn.run(app, host=Config.SERVER_HOST, port=Config.SERVER_PORT, reload=False)


# ══════════════════════════════════════════════════════════════════════
#  ROUTES COURS — Construction + Présentation
# ══════════════════════════════════════════════════════════════════════
