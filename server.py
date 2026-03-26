"""
╔══════════════════════════════════════════════════════════════════════╗
║           SMART TEACHER — Serveur FastAPI                          ║
║                                                                      ║
║  Routes :                                                            ║
║    GET  /                        — état du serveur                  ║
║    POST /process-audio           — audio → STT → RAG → LLM → TTS   ║
║    POST /ask                     — texte → RAG → LLM → TTS          ║
║    POST /ingest                  — ingère des fichiers dans le RAG  ║
║    GET  /rag/stats               — statistiques RAG                 ║
║    POST /session/clear           — efface la mémoire d'une session  ║
║    GET  /health                  — healthcheck complet              ║
║                                                                      ║
║  AMÉLIORATIONS vs version initiale :                                 ║
║    ✅ detect_question_subject enrichi (12 matières)                  ║
║    ✅ logger.log_turn avec session_id et transcription               ║
║    ✅ Route /ingest pour uploader des fichiers PDF/DOCX              ║
║    ✅ Route /health avec état de chaque module                       ║
║    ✅ Route /session/clear pour reset mémoire                        ║
║    ✅ Gestion d'erreurs robuste avec codes HTTP appropriés           ║
║    ✅ Logs structurés                                                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

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
from fastapi import FastAPI, File, Form, Request, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langdetect import detect

from config import Config
from modules.transcriber   import Transcriber
from modules.llm           import Brain
from modules.tts           import VoiceEngine
from modules.multimodal_rag import MultiModalRAG
from modules.logger        import CsvLogger
from modules.stt_logger    import STTLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SmartTeacher.Server")

# ══════════════════════════════════════════════════════════════════════
#  SESSIONS (mémoire en RAM — pour production: Redis)
# ══════════════════════════════════════════════════════════════════════

SESSIONS: dict[str, deque] = {}
MAX_HISTORY = Config.MAX_HISTORY_TURNS * 2   # paires user+assistant


def get_session(request: Request) -> tuple[str, deque]:
    """Retourne (session_id, history_deque) — crée la session si absente."""
    sid = request.headers.get("X-Session-ID") or str(uuid.uuid4())
    if sid not in SESSIONS:
        SESSIONS[sid] = deque(maxlen=MAX_HISTORY)
    return sid, SESSIONS[sid]


# ══════════════════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════════════════

def detect_lang_text(text: str) -> str:
    """Détecte la langue d'un texte ('fr', 'ar', 'en', 'tr')."""
    try:
        code = detect(text)
        if code.startswith("fr"): return "fr"
        if code.startswith("ar"): return "ar"
        if code.startswith("tr"): return "tr"
        return "en"
    except Exception:
        return "en"


def audio_bytes_to_numpy(audio_bytes: bytes) -> np.ndarray:
    """Convertit des bytes audio (WebM/WAV/MP3…) en np.float32 à 16 kHz mono."""
    # Tentative soundfile
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

    # Fallback pydub
    try:
        from pydub import AudioSegment
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            seg = (AudioSegment.from_file(tmp_path)
                   .set_frame_rate(Config.SAMPLE_RATE)
                   .set_channels(1)
                   .set_sample_width(2))
            samples = np.frombuffer(seg.raw_data, dtype=np.int16)
            return (samples / 32768.0).astype(np.float32)
        finally:
            os.unlink(tmp_path)
    except Exception as exc:
        raise RuntimeError(f"Audio conversion failed: {exc}")


# Mots-clés de détection de matière enrichis
_SUBJECT_KW: dict[str, list[str]] = {
    "math":             ["math", "équation", "algèbre", "calcul", "dérivée",
                         "intégrale", "géométrie", "vecteur", "matrice",
                         "algebra", "equation", "derivative", "حساب", "معادلة"],
    "biology":          ["bio", "cell", "cellule", "adn", "gène", "évolution",
                         "darwin", "photosynthèse", "biology", "بيولوجيا"],
    "physics":          ["physique", "force", "énergie", "vitesse", "mécanique",
                         "physics", "thermodynamique", "فيزياء"],
    "chemistry":        ["chimie", "molécule", "atome", "réaction", "chemistry",
                         "oxydation", "كيمياء"],
    "history":          ["histoire", "guerre", "révolution", "history",
                         "civilization", "empire", "تاريخ"],
    "geography":        ["géographie", "pays", "continent", "climat",
                         "geography", "جغرافيا"],
    "computer_science": ["algorithme", "code", "programmation", "python",
                         "informatique", "algorithm", "database", "برمجة"],
    "economics":        ["économie", "marché", "finance", "trade", "اقتصاد"],
}


def detect_question_subject(text: str) -> str | None:
    """Détecte la matière d'une question. Retourne None si non identifiée."""
    text_lower = text.lower()
    for subject, keywords in _SUBJECT_KW.items():
        if any(kw in text_lower for kw in keywords):
            return subject
    return None


# ══════════════════════════════════════════════════════════════════════
#  INITIALISATION DES MODULES
# ══════════════════════════════════════════════════════════════════════

log.info("=" * 70)
log.info("🤖 SMART TEACHER — DÉMARRAGE")
log.info("=" * 70)

Config.validate()
Config.print_info()

log.info("📦 Chargement des modules…")

transcriber = Transcriber()
brain       = Brain()
voice       = VoiceEngine()
rag         = MultiModalRAG(db_dir=Config.RAG_DB_DIR)
csv_logger  = CsvLogger()
stt_logger  = STTLogger()

log.info("✅ Tous les modules prêts.\n")


# ══════════════════════════════════════════════════════════════════════
#  APPLICATION FASTAPI
# ══════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Smart Teacher API",
    description="Professeur IA Vocal — STT + RAG Multimodal + LLM + TTS",
    version="2.0.0",
)

# Servir le frontend
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")


# ══════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "status":   "running",
        "rag_ready": rag.is_ready,
        "tts":      Config.TTS_PROVIDER,
        "model":    Config.GPT_MODEL,
    }


@app.get("/health")
async def health():
    """Healthcheck complet — état de chaque module."""
    return {
        "server":       "ok",
        "rag":          {"ready": rag.is_ready, **rag.get_stats()},
        "whisper":      Config.WHISPER_MODEL_SIZE,
        "llm":          Config.GPT_MODEL,
        "tts":          Config.TTS_PROVIDER,
        "sessions":     len(SESSIONS),
    }


@app.post("/process-audio")
async def process_audio(request: Request, audio: UploadFile = File(...)):
    """
    Pipeline complet :  Audio → STT → RAG → LLM → TTS → JSON

    En-tête optionnel : X-Session-ID (pour la mémoire de session)
    """
    total_start = time.time()
    session_id, history = get_session(request)
    utt_id = str(uuid.uuid4())[:8]

    # ── 1. Lire et convertir l'audio ──────────────────────────────────
    audio_bytes = await audio.read()
    try:
        audio_data = audio_bytes_to_numpy(audio_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── 2. STT ────────────────────────────────────────────────────────
    text, stt_time, lang, lang_prob, audio_duration = transcriber.transcribe(audio_data)

    if not text or len(text.strip()) <= 2:
        return JSONResponse(status_code=400, content={"error": "Aucune parole détectée"})

    log.info(f"[{session_id[:8]}] 🗣️  {lang}: {text}")

    # Logger STT
    stt_logger.log(
        session_id=session_id, utt_id=utt_id,
        audio_duration_sec=audio_duration,
        language_detected=lang, language_prob=lang_prob,
        stt_time=stt_time, transcription_text=text,
    )

    # ── 3. RAG ────────────────────────────────────────────────────────
    subject = detect_question_subject(text)
    chunks  = rag.retrieve_chunks(text, k=Config.RAG_NUM_RESULTS, subject=subject)

    # ── 4. LLM ────────────────────────────────────────────────────────
    llm_start = time.time()
    ai_response = rag.generate_final_answer(
        chunks,
        query=text,
        history=list(history),
        language=lang,
    )
    llm_time = time.time() - llm_start

    # Mise à jour mémoire session
    history.append({"role": "user",      "content": text})
    history.append({"role": "assistant", "content": ai_response})

    # ── 5. TTS ────────────────────────────────────────────────────────
    audio_resp, tts_time, tts_engine, tts_voice, mime = \
        await voice.generate_audio_async(ai_response, language_code=lang)

    audio_b64   = base64.b64encode(audio_resp).decode() if audio_resp else None
    total_time  = time.time() - total_start

    # ── 6. Log métriques globales ─────────────────────────────────────
    csv_logger.log_turn(
        audio_duration_sec=audio_duration,
        stt_time=stt_time, llm_time=llm_time,
        tts_time=tts_time, total_time=total_time,
        language=lang,
        model_used=Config.WHISPER_MODEL_SIZE,
        tts_engine_used=tts_engine,
        tts_model_used=tts_voice,
        session_id=session_id,
        transcription=text,
    )

    kpi_ok = total_time <= Config.MAX_RESPONSE_TIME
    log.info(
        f"[{session_id[:8]}] ✅ STT={stt_time:.2f}s LLM={llm_time:.2f}s "
        f"TTS={tts_time:.2f}s TOTAL={total_time:.2f}s {'✅KPI' if kpi_ok else '⚠️KPI'}"
    )

    return {
        "session_id":    session_id,
        "transcription": {"text": text, "language": lang, "confidence": round(lang_prob, 2)},
        "answer":        ai_response,
        "audio":         audio_b64,
        "subject":       subject,
        "rag_chunks":    len(chunks),
        "performance": {
            "stt_time":   round(stt_time,  2),
            "llm_time":   round(llm_time,  2),
            "tts_time":   round(tts_time,  2),
            "total_time": round(total_time,2),
            "kpi_ok":     kpi_ok,
        },
    }


@app.post("/ask")
async def ask_question(request: Request, question: str = Form(...)):
    """
    Pipeline texte (sans STT) : Texte → RAG → LLM → TTS → JSON.
    Utile pour les tests depuis l'interface web ou l'API.
    """
    total_start = time.time()
    session_id, history = get_session(request)

    lang    = detect_lang_text(question)
    subject = detect_question_subject(question)
    chunks  = rag.retrieve_chunks(question, k=Config.RAG_NUM_RESULTS, subject=subject)

    llm_start   = time.time()
    ai_response = rag.generate_final_answer(
        chunks, query=question,
        history=list(history),
        language=lang,
    )
    llm_time = time.time() - llm_start

    history.append({"role": "user",      "content": question})
    history.append({"role": "assistant", "content": ai_response})

    audio_resp, tts_time, tts_engine, tts_voice, mime = \
        await voice.generate_audio_async(ai_response, language_code=lang)
    audio_b64  = base64.b64encode(audio_resp).decode() if audio_resp else None
    total_time = time.time() - total_start

    csv_logger.log_turn(
        audio_duration_sec=0.0,
        stt_time=0.0, llm_time=llm_time,
        tts_time=tts_time, total_time=total_time,
        language=lang,
        model_used=Config.GPT_MODEL,
        tts_engine_used=tts_engine,
        tts_model_used=tts_voice,
        session_id=session_id,
        transcription=question,
    )

    return {
        "session_id": session_id,
        "question":   question,
        "answer":     ai_response,
        "audio":      audio_b64,
        "subject":    subject,
        "performance": {
            "llm_time":   round(llm_time,  2),
            "tts_time":   round(tts_time,  2),
            "total_time": round(total_time,2),
        },
    }


@app.post("/ingest")
async def ingest_files(
    files:       list[UploadFile] = File(...),
    incremental: bool             = Form(False),
):
    """
    Ingère des fichiers (PDF, DOCX, PPTX…) dans le RAG Qdrant.

    Paramètres :
        files:       Un ou plusieurs fichiers à indexer
        incremental: Si True, ajoute sans effacer la collection existante
    """
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    saved_paths = []
    upload_dir  = Path("courses")
    upload_dir.mkdir(exist_ok=True)

    for f in files:
        dest = upload_dir / f.filename
        dest.write_bytes(await f.read())
        saved_paths.append(str(dest))
        log.info(f"📥 Fichier reçu : {dest}")

    ok = rag.run_ingestion_pipeline_for_files(saved_paths, incremental=incremental)
    if not ok:
        raise HTTPException(status_code=500, detail="Ingestion échouée — voir les logs serveur")

    return {
        "status":    "ok",
        "files":     [f.filename for f in files],
        "rag_stats": rag.get_stats(),
    }


@app.get("/rag/stats")
async def rag_stats():
    """Retourne les statistiques de la base RAG."""
    return rag.get_stats()


@app.post("/session/clear")
async def clear_session(request: Request):
    """Efface la mémoire de la session courante."""
    session_id, history = get_session(request)
    history.clear()
    brain.clear_memory()
    return {"status": "cleared", "session_id": session_id}


# ══════════════════════════════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    log.info("🌐 Démarrage du serveur…")
    log.info(f"   🔗 App  : http://localhost:{Config.SERVER_PORT}/static/index.html")
    log.info(f"   📚 Docs : http://localhost:{Config.SERVER_PORT}/docs")

    uvicorn.run(
        app,
        host=Config.SERVER_HOST,
        port=Config.SERVER_PORT,
        reload=False,
    )

# ══════════════════════════════════════════════════════════════════════
#  ROUTES COURS — Construction + Présentation
# ══════════════════════════════════════════════════════════════════════

_COURSES_DB: dict = {}  # Stockage mémoire fallback


@app.post("/course/build")
async def build_course(
    files:    list[UploadFile] = File(...),
    language: str              = Form("fr"),
    level:    str              = Form("lycée"),
):
    """Upload PDF → GPT structure → cours présentable."""
    from modules.course_builder import CourseBuilder
    import uuid as _uuid

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
            course_data = await builder.build_from_file(str(dest), language=language, level=level)
            course_id   = str(_uuid.uuid4())
            course_data["id"] = course_id
            _COURSES_DB[course_id] = course_data

            # Essayer PostgreSQL
            try:
                from database.init_db import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    db_id = await builder.save_to_database(course_data, db)
                    course_data["id"] = db_id
                    _COURSES_DB[db_id] = course_data
                    del _COURSES_DB[course_id]
                    course_id = db_id
            except Exception as db_err:
                log.warning(f"PostgreSQL indisponible, cours en mémoire : {db_err}")

            rag.run_ingestion_pipeline_for_files([str(dest)], incremental=True)
            chapters = len(course_data.get("chapters", []))
            sections = sum(len(ch.get("sections", [])) for ch in course_data.get("chapters", []))
            results.append({"file": f.filename, "course_id": course_id,
                            "title": course_data.get("title"), "chapters": chapters,
                            "sections": sections, "status": "ok"})
        except Exception as exc:
            log.error(f"Build failed {f.filename}: {exc}", exc_info=True)
            results.append({"file": f.filename, "status": "error", "error": str(exc)})

    return {"results": results, "rag_stats": rag.get_stats()}


@app.get("/course/list")
async def list_courses():
    """Liste tous les cours disponibles."""
    try:
        from database.init_db import AsyncSessionLocal
        from database.crud import get_all_courses
        async with AsyncSessionLocal() as db:
            courses = await get_all_courses(db)
            if courses:
                return {"courses": [{"id": str(c.id), "title": c.title,
                                     "subject": c.subject, "language": c.language,
                                     "level": c.level} for c in courses]}
    except Exception:
        pass
    return {"courses": [{"id": v["id"], "title": v.get("title", "Sans titre"),
                         "subject": v.get("subject", "general"),
                         "language": v.get("language", "fr"),
                         "level": v.get("level", "lycée")} for v in _COURSES_DB.values()]}


@app.get("/course/{course_id}/structure")
async def get_course_structure(course_id: str):
    """Structure complète d'un cours (chapitres + sections + concepts)."""
    try:
        from database.init_db import AsyncSessionLocal
        from database.crud import get_course_with_structure
        import uuid as _uuid
        async with AsyncSessionLocal() as db:
            c = await get_course_with_structure(db, _uuid.UUID(course_id))
            if c:
                return {"id": str(c.id), "title": c.title, "subject": c.subject,
                        "language": c.language, "level": c.level,
                        "chapters": [{"title": ch.title, "order": ch.order,
                            "sections": [{"title": s.title, "order": s.order,
                                "content": s.content, "duration_s": s.duration_s,
                                "concepts": [{"term": co.term, "definition": co.definition,
                                              "example": co.example or ""}
                                             for co in s.concepts]}
                                        for s in ch.sections]}
                                    for ch in c.chapters]}
    except Exception:
        pass
    course = _COURSES_DB.get(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    return course