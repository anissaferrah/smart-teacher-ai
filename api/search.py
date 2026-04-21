from __future__ import annotations

from collections import deque

from fastapi import APIRouter, Form, HTTPException, Request

from config import Config
from handlers.session_manager import HTTP_SESSIONS, detect_lang_text, detect_subject, get_http_session
from services.app_state import (
    analytics_service,
    language_brain,
    knowledge_retrieval_engine,
    speech_synthesizer,
    transcript_search_service,
)

router = APIRouter(tags=["search"])


@router.post("/ask")
async def answer_text_question(request: Request, question: str = Form(...), course_id: str | None = Form(None)) -> dict:
    session_id, history = get_http_session(request)
    if not course_id:
        course_id = request.headers.get("X-Course-ID")

    language = detect_lang_text(question)
    subject = detect_subject(question)
    chunks_with_scores = knowledge_retrieval_engine.retrieve_chunks(question, k=Config.RAG_NUM_RESULTS, course_id=course_id)

    llm_start = __import__("time").time()
    ai_response, _ = knowledge_retrieval_engine.generate_final_answer(
        chunks_with_scores,
        question=question,
        history=history,
        language=language,
    )
    llm_time = __import__("time").time() - llm_start

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": ai_response})
    HTTP_SESSIONS[session_id] = deque(history, maxlen=Config.MAX_HISTORY_TURNS * 2)

    audio_bytes, tts_time, tts_engine, tts_voice, mime = await speech_synthesizer.generate_audio_async(ai_response, language_code=language)
    total_time = llm_time + tts_time

    return {
        "session_id": session_id,
        "question": question,
        "answer": ai_response,
        "audio": __import__("base64").b64encode(audio_bytes).decode() if audio_bytes else None,
        "subject": subject,
        "performance": {
            "llm_time": round(llm_time, 2),
            "tts_time": round(tts_time, 2),
            "total_time": round(total_time, 2),
        },
    }


@router.get("/rag/stats")
async def get_rag_statistics() -> dict:
    return knowledge_retrieval_engine.get_stats()


@router.get("/debug/rag_test")
async def debug_rag_retrieval(q: str = "explain this topic", k: int = 5) -> dict:
    if not knowledge_retrieval_engine.is_ready:
        return {"error": "RAG not ready", "status": knowledge_retrieval_engine.get_status()}

    try:
        result = knowledge_retrieval_engine.debug_retrieve(q, k=k)
        return {"status": "ok", "debug_data": result, "rag_status": knowledge_retrieval_engine.get_status()}
    except Exception as exc:
        return {"error": str(exc), "status": knowledge_retrieval_engine.get_status()}


@router.get("/search/transcripts")
async def search_transcript_history(q: str, language: str = "", course_id: str = "", role: str = "", limit: int = 20) -> dict:
    if not q.strip():
        raise HTTPException(status_code=400, detail="Paramètre 'q' requis")
    results = transcript_search_service.search(q, language=language, course_id=course_id, role=role, limit=limit)
    return {"query": q, "count": len(results), "results": results}


@router.get("/search/session/{session_id}")
async def get_session_transcript_history(session_id: str) -> dict:
    history = transcript_search_service.get_session_history(session_id)
    return {"session_id": session_id, "count": len(history), "history": history}


@router.get("/search/stats")
async def get_search_statistics() -> dict:
    return transcript_search_service.get_stats()
