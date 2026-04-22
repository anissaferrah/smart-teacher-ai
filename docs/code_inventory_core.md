# Smart Teacher - Inventaire Code (Core)

Généré automatiquement le 2026-04-22 10:51:13

| Dossier | Fichier | Fonctions / Classes détectées | Rôle dans le code |
|---|---|---|---|
| . | analyze_metrics.py | def analyze_global(csv_path: str) -> Optional[pd.DataFrame]:; def create_dashboard(df: pd.DataFrame) -> None:; def analyze_stt(csv_path: str) -> Optional[pd.DataFrame]:; def main() -> int:; def analyze_stt(csv_path: str) -> None:; def main(): | Analyse offline des métriques CSV et dashboard local. |
| . | config.py | class Config: | Configuration simple historique. |
| . | domains_config.py | def get_domains() -> list[str]:; def get_courses(domain: str) -> list[str]:; def get_courses_list(domain: str) -> list[str]:; def get_course_metadata(domain: str, course: str) -> dict:; def get_course_title(domain: str, course: str) -> str:; def discover_chapters(domain: str, course: str) -> Dict[int, str]:; def get_chapters(domain: str, course: str) -> Dict[int, str]:; def get_chapter_title(domain: str, course: str, chapter_idx: int) -> str:; def auto_detect_course(file_path: str) -> tuple[str, str]: | Catalogues domaines/cours/chapitres et auto-détection. |
| . | main.py | async def lifespan(app: FastAPI):; async def disable_html_cache(request: Request, call_next):; async def dashboard_services_alias():; async def root():; async def get_app_version(): | Entrée FastAPI, middlewares et routes racine. |
| api | __init__.py | (aucune fonction/classe top-level) | Endpoints HTTP/WebSocket (contrats API). |
| api | analytics.py | async def get_analytics_report() -> dict:; async def get_kpi_summary(hours: int = 24) -> dict:; async def get_course_progression(course_id: str) -> dict:; async def get_latency_distribution() -> dict: | Endpoints HTTP/WebSocket (contrats API). |
| api | cache.py | async def get_embedding_cache_statistics() -> dict: | Endpoints HTTP/WebSocket (contrats API). |
| api | course.py | def _media_upload_object_name(domain: str, course: str, chapter: str, filename: str) -> str:; async def ingest_course_files(files: list[UploadFile] = File(...), incremental: bool = Form(True), course_id: str \| None = Form(None)):; async def _run_course_ingestion_background(file_paths: list[str], incremental: bool = False, domain: str = "general", course: str = "uploaded", course_id: str \| None = None) -> None:; async def get_ingestion_status() -> dict:; async def build_course_from_upload(files: list[UploadFile] = File(...), language: str = Form("fr"), level: str = Form("lycée"), domain: str = Form("general")):; async def list_courses() -> dict:; async def get_course_structure(course_id: str) -> dict: | Endpoints HTTP/WebSocket (contrats API). |
| api | health.py | async def get_site_favicon() -> Response:; async def get_service_root_status() -> dict:; async def get_service_health() -> dict:; async def get_dashboard_service_overview() -> dict: | Endpoints HTTP/WebSocket (contrats API). |
| api | media.py | async def serve_media_file(path: str):; async def list_media_objects(prefix: str = "") -> dict: | Endpoints HTTP/WebSocket (contrats API). |
| api | profile.py | async def get_student_learning_profile(student_id: str) -> dict:; async def reset_student_learning_profile(student_id: str) -> dict: | Endpoints HTTP/WebSocket (contrats API). |
| api | search.py | async def answer_text_question(request: Request, question: str = Form(...), course_id: str \| None = Form(None)) -> dict:; async def get_rag_statistics() -> dict:; async def debug_rag_retrieval(q: str = "explain this topic", k: int = 5) -> dict:; async def search_transcript_history(q: str, language: str = "", course_id: str = "", role: str = "", limit: int = 20) -> dict:; async def get_session_transcript_history(session_id: str) -> dict:; async def get_search_statistics() -> dict: | Endpoints HTTP/WebSocket (contrats API). |
| api | sessions.py | async def create_session_token() -> dict:; async def get_session_overview(session_id: str) -> dict:; async def clear_http_session(request: Request) -> dict: | Endpoints HTTP/WebSocket (contrats API). |
| api | ws_router.py | def set_session_service(service: RealtimeSessionService) -> None:; async def websocket_endpoint(websocket: WebSocket, session_id: str):; async def create_session(): | Endpoints HTTP/WebSocket (contrats API). |
| database | __init__.py | (aucune fonction/classe top-level) | Scripts utilitaires base de données. |
| database | reset_db_fresh.py | async def reset_database(): | Scripts utilitaires base de données. |
| database\core | __init__.py | (aucune fonction/classe top-level) | Initialisation et connexion base de données. |
| database\core | init_db.py | async def create_tables():; async def get_db():; async def check_db_connection() -> bool: | Initialisation et connexion base de données. |
| database\models | __init__.py | class Student(Base):; class Course(Base):; class Chapter(Base):; class Section(Base):; class Concept(Base):; class LearningSession(Base):; class Interaction(Base):; class LearningEvent(Base):; class StudentProfile(Base):; class StudentMistake(Base):; class RAGChunk(Base):; class SystemLog(Base):; class PerformanceMetric(Base):; class LLMCache(Base): | Modèles ORM et schéma relationnel. |
| database\repositories | __init__.py | (aucune fonction/classe top-level) | CRUD et accès persistance. |
| database\repositories | crud.py | async def create_student(; async def create_course(; async def create_course_with_structure(; async def get_course(; async def get_course_with_structure(; async def get_all_courses(; async def delete_course(; async def create_learning_session(; async def get_session(; async def update_session_state(; async def end_session(; async def log_interaction(; async def get_session_stats(; async def log_learning_event(; async def log_interaction(; async def get_session_stats(db: AsyncSession, session_id: uuid.UUID) -> dict: | CRUD et accès persistance. |
| domain | __init__.py | (aucune fonction/classe top-level) | Entités métier et états de session. |
| domain | session_state.py | class DialogState(str, Enum):; def can_transition(from_state: DialogState, to_state: DialogState) -> bool:; class CourseSlide:; class StudentProfile:; class SessionContext: | Entités métier et états de session. |
| handlers | __init__.py | (aucune fonction/classe top-level) | Adaptateurs d'entrée/sortie et routes legacy. |
| handlers | audio_pipeline.py | async def run_pipeline_streaming(; async def run_pipeline( | Adaptateurs d'entrée/sortie et routes legacy. |
| handlers | rest_routes.py | async def handle_session_creation():; async def handle_ask(; async def handle_ingest(; async def handle_health_check():; async def handle_rag_stats(course_id: Optional[str] = None):; async def handle_session_get(session_id: str):; async def handle_search_transcripts( | Adaptateurs d'entrée/sortie et routes legacy. |
| handlers | session_manager.py | def detect_lang_text(text: str) -> str:; def audio_bytes_to_numpy(audio_bytes: bytes) -> np.ndarray:; def detect_subject(text: str) -> str \| None:; def get_http_session(request) -> tuple[str, list]:; async def get_redis() -> aioredis.Redis: | Adaptateurs d'entrée/sortie et routes legacy. |
| infrastructure | __init__.py | (aucune fonction/classe top-level) | Infrastructure transverse. |
| infrastructure | config.py | class AudioConfig(BaseModel):; class STTConfig(BaseModel):; class LLMConfig(BaseModel):; class RAGConfig(BaseModel):; class ConfusionDetectionConfig(BaseModel):; class TTSConfig(BaseModel):; class RealtimeSessionConfig(BaseModel):; class AnalyticsConfig(BaseModel):; class DatabaseConfig(BaseModel):; class RedisConfig(BaseModel):; class AppSettings(BaseModel):; def load_settings() -> AppSettings: | Configuration applicative (Pydantic Settings). |
| infrastructure | logging.py | def setup_logging(; def get_logger(name: str) -> logging.Logger: | Configuration logs et fabrique logger. |
| modules | __init__.py | (aucune fonction/classe top-level) | Modules métier transverses. |
| modules\ai | __init__.py | (aucune fonction/classe top-level) | LLM, RAG, STT/TTS et détection confusion. |
| modules\ai | confusion_detector.py | class ConfusionPrediction:; class ConfusionModel(nn.Module):; def _resolve_bundle_path(raw_path: str \| Path) -> Path:; class SIGHTConfusionDetector:; def get_confusion_detector(model_path: Optional[str] = None) -> Optional[SIGHTConfusionDetector]:; def predict_confusion(text: str, model_path: Optional[str] = None) -> Optional[ConfusionPrediction]: | LLM, RAG, STT/TTS et détection confusion. |
| modules\ai | llm.py | def _resolve_domain_prompt_parts(domain: str \| None) -> tuple[str, str]:; def detect_confusion(; def get_clarification_prompt(language: str = "fr", domain: str = None) -> str:; def get_system_prompt(domain: str = None, language: str = "en") -> str:; def get_presentation_prompt(domain: str = None, language: str = "en", chapter_title: str = "") -> str:; def _extract_json_payload(raw_text: str) -> dict[str, object] \| None:; class Brain: | LLM, RAG, STT/TTS et détection confusion. |
| modules\ai | local_llm.py | class LocalLLMFallback: | LLM, RAG, STT/TTS et détection confusion. |
| modules\ai | multimodal_rag.py | def _normalize_text_for_diversity(text: str) -> str:; def _is_openai_embedding_model(model_name: str) -> bool:; def _embedding_dim_for_model(model_name: str) -> int:; class MultiModalRAG: | LLM, RAG, STT/TTS et détection confusion. |
| modules\ai | transcriber.py | class Transcriber: | LLM, RAG, STT/TTS et détection confusion. |
| modules\ai | tts.py | class VoiceEngine: | LLM, RAG, STT/TTS et détection confusion. |
| modules\ai\confusion | __init__.py | (aucune fonction/classe top-level) | Détection de confusion unifiée. |
| modules\ai\confusion | unified_detector.py | class UnifiedConfusionDetector:; async def get_unified_confusion_detector( | Détection de confusion unifiée. |
| modules\data | __init__.py | (aucune fonction/classe top-level) | Stockage média, cache embeddings, recherche transcript. |
| modules\data | embedding_cache.py | class EmbeddingCache: | Stockage média, cache embeddings, recherche transcript. |
| modules\data | media_storage.py | class MediaStorage:; def get_storage() -> MediaStorage: | Stockage média, cache embeddings, recherche transcript. |
| modules\data | transcript_search.py | class TranscriptEntry:; class TranscriptSearcher:; def get_searcher() -> TranscriptSearcher: | Stockage média, cache embeddings, recherche transcript. |
| modules\input | __init__.py | (aucune fonction/classe top-level) | Capture/prétraitement audio entrant. |
| modules\input | audio_input.py | class AudioInput: | Capture/prétraitement audio entrant. |
| modules\monitoring | __init__.py | (aucune fonction/classe top-level) | Analytics, dashboard et logs monitoring. |
| modules\monitoring | analytics.py | class LearningEvent:; class AnalyticsEngine:; def get_analytics() -> AnalyticsEngine: | Analytics, dashboard et logs monitoring. |
| modules\monitoring | dashboard.py | def record_session_event(event: dict):; def record_checkpoint_event(event: dict):; def record_trace_event(event: dict):; def _safe_int(value):; def _format_pointer_short(event: dict) -> str:; def _format_pointer_detail(event: dict) -> str:; async def get_stats():; async def get_active_sessions():; async def get_analytics():; async def get_recent_checkpoints():; async def get_recent_trace():; async def get_recent_questions():; async def dashboard_page(): | Analytics, dashboard et logs monitoring. |
| modules\monitoring | logger.py | class CsvLogger: | Analytics, dashboard et logs monitoring. |
| modules\monitoring | stt_logger.py | class STTLogger: | Analytics, dashboard et logs monitoring. |
| modules\pedagogy | __init__.py | (aucune fonction/classe top-level) | Structuration cours, dialogue, profil étudiant. |
| modules\pedagogy | course_analyzer.py | class CourseAnalyzer:; def get_analyzer() -> CourseAnalyzer: | Structuration cours, dialogue, profil étudiant. |
| modules\pedagogy | course_builder.py | class TextExtractor:; class LocalStructurer:; class CourseBuilder: | Structuration cours, dialogue, profil étudiant. |
| modules\pedagogy | dialogue.py | def _is_openai_embedding_model(model_name: str) -> bool:; def _get_semantic_embedder():; def _get_sight_confusion_predictor():; async def get_redis() -> aioredis.Redis:; class DialogState(str, Enum):; class SessionContext:; class DialogueManager: | Structuration cours, dialogue, profil étudiant. |
| modules\pedagogy | ingestion_manager.py | class IngestionState(str, Enum):; class IngestionStatus:; class IngestionManager: | Structuration cours, dialogue, profil étudiant. |
| modules\pedagogy | slide_sync.py | class Slide:; class SlideSynchronizer: | Structuration cours, dialogue, profil étudiant. |
| modules\pedagogy | student_profile.py | async def get_redis() -> aioredis.Redis:; class StudentProfile:; class ProfileManager: | Structuration cours, dialogue, profil étudiant. |
| services | __init__.py | (aucune fonction/classe top-level) | Services applicatifs. |
| services | app_state.py | (aucune fonction/classe top-level) | État global applicatif partagé. |
| services | bootstrap.py | async def log_backend_diagnostics() -> None:; async def store_media_bytes(object_name: str, data: bytes, content_type: str) -> None:; async def store_media_json(object_name: str, payload: dict) -> None:; async def create_application_lifespan(app: FastAPI): | Bootstrap application et diagnostics démarrage. |
| services | media_service.py | async def store_media_bytes(object_name: str, data: bytes, content_type: str) -> None:; async def store_media_json(object_name: str, payload: dict) -> None:; async def read_local_media_file(path: str) -> Path: | Services de stockage média. |
| services | presentation.py | def _build_course_analysis(course) -> dict:; async def load_course_slide_context(course_id: str, chapter_index: int, section_index: int) -> dict \| None:; async def load_current_slide_context(course_id: str, chapter_index: int, section_index: int) -> dict \| None: | Chargement contexte slide et analyse cours. |
| services | quiz.py | def is_quiz_request(normalized_text: str) -> bool: | Détection intention quiz. |
| services\agentic_rag | __init__.py | (aucune fonction/classe top-level) | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | advanced_prompts.py | def build_reasoning_prompt(; def build_aggregation_prompt(; def get_fallback_prompt(kind: str, language: str = "fr") -> str: | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | document_chunker.py | class Chunk:; class HierarchicalDocumentChunker: | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | document_manager.py | class DocumentManager: | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | orchestrator.py | class AgenticRAGState:; class AgenticRAGOrchestrator: | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | parent_store_manager.py | class ParentStoreManager: | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | prompts.py | (aucune fonction/classe top-level) | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | reasoner_agent.py | class ReasonerAgent: | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | schemas.py | class ChunkResult(BaseModel):; class ReasoningTrace(BaseModel):; class QueryAnalysis(BaseModel):; class SubQuery(BaseModel):; class AnswerValidation(BaseModel):; class ConversationExchange(BaseModel):; class StudentProfile(BaseModel):; class AgenticRAGInput(BaseModel):; class AgenticRAGOutput(BaseModel):; class PipelineMetrics(BaseModel): | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | tools.py | class SearchKnowledgeBaseTool(BaseModel):; class GetConfusionPatternsTool(BaseModel):; class GetPrerequisitesTool(BaseModel):; class GetTopicDifficultyTool(BaseModel):; class ValidateAnswerComplenessTool(BaseModel):; class EducationTools: | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag | vector_db_manager.py | class VectorRecord:; class VectorDBManager: | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag\agents | __init__.py | (aucune fonction/classe top-level) | Agents spécialisés du pipeline Agentic RAG. |
| services\agentic_rag\agents | query_clarifier.py | class QueryClarifier: | Agents spécialisés du pipeline Agentic RAG. |
| services\agentic_rag\agents | query_rewriter.py | class QueryRewriter: | Agents spécialisés du pipeline Agentic RAG. |
| services\agentic_rag\agents | reasoning_agent.py | async def reasoning_agent_node( | Agents spécialisés du pipeline Agentic RAG. |
| services\agentic_rag\agents | reflection_agent.py | class ReflectionAgent: | Agents spécialisés du pipeline Agentic RAG. |
| services\agentic_rag\agents | retriever_agent.py | class RetrieverAgent: | Agents spécialisés du pipeline Agentic RAG. |
| services\agentic_rag\graph | __init__.py | (aucune fonction/classe top-level) | Workflow graphe Agentic RAG. |
| services\agentic_rag\graph | state.py | class AgenticRAGState: | Workflow graphe Agentic RAG. |
| services\agentic_rag\graph | workflow.py | class AgenticRAGWorkflow: | Workflow graphe Agentic RAG. |
| services\agentic_rag\memory | __init__.py | (aucune fonction/classe top-level) | Mémoire court/long terme et compression contexte. |
| services\agentic_rag\memory | compressor.py | class ContextCompressor: | Mémoire court/long terme et compression contexte. |
| services\agentic_rag\memory | long_term.py | class LongTermMemory: | Mémoire court/long terme et compression contexte. |
| services\agentic_rag\memory | short_term.py | class ShortTermMemory: | Mémoire court/long terme et compression contexte. |
| services\agentic_rag\retrieval | __init__.py | (aucune fonction/classe top-level) | Composants de retrieval hybride. |
| services\agentic_rag\retrieval | hybrid_retriever.py | class HybridRetriever: | Composants de retrieval hybride. |
| services\agentic_rag\retrievers | __init__.py | (aucune fonction/classe top-level) | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\agentic_rag\utils | __init__.py | (aucune fonction/classe top-level) | Pipeline Agentic RAG (orchestration, schémas, outils, vecteurs). |
| services\analytics | __init__.py | (aucune fonction/classe top-level) | Sink analytics (ClickHouse) et agrégation événements. |
| services\analytics | clickhouse_events.py | class AnalyticsSink:; def get_analytics_sink() -> AnalyticsSink: | Sink analytics (ClickHouse) et agrégation événements. |
| services\orchestrators | __init__.py | (aucune fonction/classe top-level) | Orchestration temps réel présentation/Q&A/session. |
| services\orchestrators | presentation_service.py | class PresentationService: | Orchestration temps réel présentation/Q&A/session. |
| services\orchestrators | qa_service.py | class QAService: | Orchestration temps réel présentation/Q&A/session. |
| services\orchestrators | realtime_session_service.py | class RealtimeSessionService:; def create_session_service( | Orchestration temps réel présentation/Q&A/session. |
| tests | test_agentic_rag_integration.py | class MockLLM:; class MockRAG:; async def test_orchestrator_initialization():; async def test_pipeline_execution(): | Tests d'intégration et mocks. |
