"""Shared runtime services for Smart Teacher.

This module centralizes the long-lived service singletons so route modules can
import clear names instead of rebuilding state in `main.py`.
"""

from __future__ import annotations

from config import Config
from modules.input.audio_input import AudioInput
from modules.ai.llm import Brain
from modules.ai.multimodal_rag import MultiModalRAG
from modules.ai.transcriber import Transcriber
from modules.ai.tts import VoiceEngine
from modules.data.media_storage import get_storage
from modules.data.transcript_search import get_searcher
from modules.monitoring.analytics import get_analytics
from modules.monitoring.dashboard import record_checkpoint_event, record_session_event, record_trace_event
from modules.monitoring.logger import CsvLogger
from modules.monitoring.stt_logger import STTLogger
from modules.ai.confusion.unified_detector import UnifiedConfusionDetector
from modules.pedagogy.course_analyzer import get_analyzer
from modules.pedagogy.dialogue import DialogueManager
from modules.pedagogy.ingestion_manager import IngestionManager
from modules.pedagogy.slide_sync import SlideSynchronizer
from modules.pedagogy.student_profile import ProfileManager
from services.agentic_rag.document_manager import DocumentManager
from services.agentic_rag.vector_db_manager import VectorDBManager

Config.validate()

transcription_service = Transcriber()
language_brain = Brain()
speech_synthesizer = VoiceEngine()
knowledge_retrieval_engine = MultiModalRAG(
    db_dir=Config.RAG_DB_DIR,
    force_local_embeddings=not Config.RAG_ENABLED,
)
confusion_detector = UnifiedConfusionDetector(sight_model_path=Config.CONFUSION_MODEL_PATH)
agentic_vector_db_manager = VectorDBManager(knowledge_retrieval_engine)
agentic_document_manager = DocumentManager(
    knowledge_retrieval_engine,
    vector_db_manager=agentic_vector_db_manager,
)
turn_logger = CsvLogger()
stt_event_logger = STTLogger()
dialogue_manager = DialogueManager()
student_profile_manager = ProfileManager()
slide_synchronizer = SlideSynchronizer()
microphone_input = AudioInput()
media_service = get_storage()
transcript_search_service = get_searcher()
analytics_service = get_analytics()
course_analyzer_service = get_analyzer()
ingestion_service = IngestionManager()
# ✅ Initialize Agentic RAG Orchestrator if mode is configured
if Config.RAG_MODE == "agentic":
    try:
        from services.agentic_rag.orchestrator import AgenticRAGOrchestrator
        from services.agentic_rag.memory.short_term import ShortTermMemory
        from services.agentic_rag.memory.long_term import LongTermMemory
        _stm = ShortTermMemory()
        _ltm = LongTermMemory()
        agentic_rag_orchestrator = AgenticRAGOrchestrator(
            llm=language_brain,
            rag=knowledge_retrieval_engine,
            short_term_memory=_stm,
            long_term_memory=_ltm,
        )
        import logging as _log
        _log.getLogger("SmartTeacher").info("✅ AgenticRAGOrchestrator initialized")
    except Exception as _exc:
        import logging as _log
        _log.getLogger("SmartTeacher").warning(f"⚠️ AgenticRAGOrchestrator failed: {_exc}")
        agentic_rag_orchestrator = None
else:
    agentic_rag_orchestrator = None