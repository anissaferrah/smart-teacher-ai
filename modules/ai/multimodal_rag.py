"""Smart Teacher — Multi-Modal RAG with Qdrant"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from unstructured.partition.auto import partition
from unstructured.chunking.title import chunk_by_title
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_community.retrievers import BM25Retriever
try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:
    from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, Filter, FieldCondition, MatchValue
from config import Config
from modules.data.embedding_cache import embedding_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SmartTeacher.RAG")


def _normalize_text_for_diversity(text: str) -> str:
    text = re.sub(r"[^\w\sÀ-ÿ]+", " ", text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_openai_embedding_model(model_name: str) -> bool:
    return model_name.strip().lower().startswith("text-embedding-")


def _embedding_dim_for_model(model_name: str) -> int:
    normalized = model_name.strip().lower()
    if normalized.startswith("text-embedding-3-large"):
        return 3072
    if normalized.startswith("text-embedding-3-small"):
        return 1536
    if "bge-m3" in normalized:
        return 1024
    if "all-minilm-l6-v2" in normalized:
        return 384
    return 1536 if _is_openai_embedding_model(normalized) else 1024


COLLECTION_NAME  = "smart_teacher_multimodal"
EMBEDDING_DIM_OPENAI     = 1536      # OpenAI text-embedding-3-small
EMBEDDING_DIM_LOCAL      = 1024      # BAAI/bge-m3
EMBEDDING_DIM_LEGACY     = 384       # sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_MODEL_OPENAI   = "text-embedding-3-small"
EMBEDDING_MODEL_LOCAL    = "BAAI/bge-m3"  # Modèle local par défaut
EMBEDDING_MODEL_LEGACY   = "sentence-transformers/all-MiniLM-L6-v2"  # Fallback léger
EMBEDDING_MODEL  = Config.RAG_EMBEDDING_MODEL or EMBEDDING_MODEL_LOCAL
EMBEDDING_DIM    = _embedding_dim_for_model(EMBEDDING_MODEL)
LLM_SUMMARY      = "gpt-4o-mini"
LLM_ANSWER       = "gpt-4o-mini"

class MultiModalRAG:
    def __init__(self, db_dir: str = "data/rag_cache", force_local_embeddings: bool = False):
        """
        Init RAG with optional forced local embeddings for ingestion.
        
        Args:
            db_dir: Database directory
            force_local_embeddings: If True, skip OpenAI and use local HuggingFace embeddings directly.
                                   Used during course ingestion to avoid quota issues.
        """
        self.db_dir      = Path(db_dir)
        self.docs_cache  = self.db_dir / "docs_cache.json"
        self.summary_cache_path = self.db_dir / "summary_cache.json"

        self.vectorstore:     QdrantVectorStore | None = None
        self.client:          QdrantClient | None      = None
        self.qdrant_dir = self.db_dir / "qdrant"
        self.collection_name = COLLECTION_NAME
        self.bm25_retriever:  BM25Retriever | None     = None
        self.vector_retriever = None
        self.all_docs:        list[Document]           = []
        self.summary_cache:   dict[str, str]           = {}
        self.is_ready = False
        self.embedding_source = "none"  # "openai" ou "huggingface"
        self.embedding_model_name = "none"
        self.preferred_embedding_model = Config.RAG_EMBEDDING_MODEL or EMBEDDING_MODEL_LOCAL
        self.current_embedding_dim = _embedding_dim_for_model(self.preferred_embedding_model)
        self._openai_disabled_reason: str | None = None

        log.info("Initializing Smart Teacher Multi-Modal RAG (Qdrant) v2…")

        # ── Embeddings : modèle configuré -> fallback local ───────────────────
        self.embeddings = None
        self._embeddings_ok = False
        
        if force_local_embeddings or not _is_openai_embedding_model(self.preferred_embedding_model):
            local_model = (
                self.preferred_embedding_model
                if not _is_openai_embedding_model(self.preferred_embedding_model)
                else EMBEDDING_MODEL_LOCAL
            )
            log.info(f"🔧 MODE LOCAL: Using HuggingFace embeddings ({local_model})…")
            try:
                self._set_embeddings(
                    "huggingface",
                    local_model,
                    self._build_local_embeddings(local_model),
                )
                log.info(
                    f"✅ Local embeddings ready ({local_model}) — "
                    f"dim={self.current_embedding_dim}"
                )
            except Exception as hf_exc:
                if local_model != EMBEDDING_MODEL_LEGACY:
                    log.info(
                        f"ℹ️ Local embeddings failed ({hf_exc.__class__.__name__}). "
                        f"Fallback to {EMBEDDING_MODEL_LEGACY}…"
                    )
                    try:
                        self._set_embeddings(
                            "huggingface",
                            EMBEDDING_MODEL_LEGACY,
                            self._build_local_embeddings(EMBEDDING_MODEL_LEGACY),
                        )
                        log.info(
                            f"✅ Fallback embeddings ready ({EMBEDDING_MODEL_LEGACY}) — "
                            f"dim={self.current_embedding_dim}"
                        )
                    except Exception as legacy_exc:
                        log.error(
                            f"❌ Local embeddings failed: {legacy_exc}. "
                            f"RAG disabled — system continues with BM25 search only."
                        )
                else:
                    log.error(
                        f"❌ Local embeddings failed: {hf_exc}. "
                        f"RAG disabled — system continues with BM25 search only."
                    )
        else:
            try:
                self._set_embeddings(
                    "openai",
                    self.preferred_embedding_model,
                    self._build_openai_embeddings(self.preferred_embedding_model),
                )
                log.info(f"✅ Embeddings OpenAI ready ({self.preferred_embedding_model})")
            except Exception as exc:
                log.info(
                    f"ℹ️ Modèle distant indisponible ({exc.__class__.__name__}). "
                    f"Fallback to local BAAI/bge-m3…"
                )
                try:
                    self._set_embeddings(
                        "huggingface",
                        EMBEDDING_MODEL_LOCAL,
                        self._build_local_embeddings(EMBEDDING_MODEL_LOCAL),
                    )
                    log.info(
                        f"✅ Fallback embeddings ready ({EMBEDDING_MODEL_LOCAL}) — "
                        f"dim={self.current_embedding_dim} (quota OpenAI probable)"
                    )
                except Exception as hf_exc:
                    log.error(
                        f"❌ Both OpenAI and HuggingFace embeddings failed: {hf_exc}. "
                        f"RAG disabled — system continues with BM25 search only."
                    )

        self._load_summary_cache()

        # ── Qdrant Docker Container (redis + postgres backend) ──────────────────────
        try:
            self.client = QdrantClient(
                host=Config.QDRANT_HOST,
                port=Config.QDRANT_PORT,
                timeout=5.0
            )
            log.info(f"✅ Qdrant Docker ready → {Config.QDRANT_HOST}:{Config.QDRANT_PORT}")
            self.collection_name = self._collection_name_for_current_backend()
            if self._embeddings_ok and self.client.collection_exists(self.collection_name):
                self._load_existing_db()
            elif not self._embeddings_ok:
                self._activate_local_retrieval_fallback("no embeddings available")
            else:
                self._activate_local_retrieval_fallback(f"collection '{self.collection_name}' not found")
        except Exception as exc:
            self.client = None
            log.info(f"ℹ️ Qdrant local storage unavailable ({exc}) — local BM25 fallback active.")
            self._activate_local_retrieval_fallback(str(exc))

    # ══════════════════════════════════════════════════════════════════════════
    #  STATUS & DIAGNOSTICS
    # ══════════════════════════════════════════════════════════════════════════

    def get_status(self) -> dict[str, str | bool | int]:
        """
        Retourne le statut actuel du RAG pour monitoring/diagnostics.
        Utile pour vérifier quel backend d'embedding est utilisé.
        """
        return {
            "rag_ready": self.is_ready,
            "embeddings_ok": self._embeddings_ok,
            "embedding_source": self.embedding_source,  # "openai", "huggingface", ou "none"
            "embedding_model": self.embedding_model_name,
            "embedding_dim": self.current_embedding_dim,
            "vectorstore_available": self.vectorstore is not None,
            "bm25_available": self.bm25_retriever is not None,
            "qdrant_connected": self.client is not None,
            "docs_loaded": len(self.all_docs),
        }

    @staticmethod
    def _should_disable_openai(exc: Exception) -> bool:
        message = f"{exc.__class__.__module__}:{exc.__class__.__name__}:{exc}".lower()
        return any(
            token in message
            for token in (
                "insufficient_quota",
                "quota",
                "429",
                "rate limit",
                "ratelimit",
                "authentication",
                "unauthorized",
                "invalid_api_key",
            )
        )

    def _disable_openai(self, reason: str) -> None:
        if self._openai_disabled_reason == reason:
            return
        self._openai_disabled_reason = reason
        log.info(f"ℹ️ OpenAI désactivé pour ce RAG ({reason}) → Ollama prioritaire")

    def _embedding_cache_namespace(self) -> str:
        return f"{self.embedding_source}:{self.embedding_model_name}"

    def _collection_name_for_current_backend(self) -> str:
        namespace = self._embedding_cache_namespace()
        safe_namespace = re.sub(r"[^a-zA-Z0-9]+", "_", namespace.lower()).strip("_") or "default"
        namespace_hash = hashlib.md5(namespace.encode()).hexdigest()[:8]
        return f"{COLLECTION_NAME}__{safe_namespace}__{namespace_hash}"

    def _build_openai_embeddings(self, model_name: str) -> OpenAIEmbeddings:
        return OpenAIEmbeddings(
            model=model_name,
            max_retries=0,
        )

    def _build_local_embeddings(self, model_name: str = EMBEDDING_MODEL_LOCAL) -> HuggingFaceEmbeddings:
        return HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

    def _set_embeddings(self, source: str, model_name: str, embeddings_obj: Any) -> None:
        self.embeddings = embeddings_obj
        self._embeddings_ok = True
        self.embedding_source = source
        self.embedding_model_name = model_name
        self.current_embedding_dim = _embedding_dim_for_model(model_name)
        self.collection_name = self._collection_name_for_current_backend()

    def _switch_to_local_embeddings(self, reason: str) -> bool:
        if (
            self.embedding_source == "huggingface"
            and self.embedding_model_name == EMBEDDING_MODEL_LOCAL
            and self.embeddings is not None
        ):
            return True

        try:
            self._set_embeddings(
                "huggingface",
                EMBEDDING_MODEL_LOCAL,
                self._build_local_embeddings(EMBEDDING_MODEL_LOCAL),
            )
            log.info(
                f"ℹ️ Modèle distant indisponible ({reason}) — switching to local HuggingFace embeddings ({EMBEDDING_MODEL_LOCAL})."
            )
            return True
        except Exception as hf_exc:
            self.embeddings = None
            self._embeddings_ok = False
            log.error(
                f"❌ HuggingFace fallback failed after OpenAI error ({reason}): {hf_exc}"
            )
            return False

    @staticmethod
    def _should_fallback_to_local_embeddings(exc: Exception) -> bool:
        message = f"{exc.__class__.__module__}:{exc.__class__.__name__}:{exc}".lower()
        return any(
            token in message
            for token in (
                "openai",
                "quota",
                "rate limit",
                "ratelimit",
                "429",
                "insufficient_quota",
                "authentication",
                "api error",
            )
        )

    def _activate_local_retrieval_fallback(self, reason: str) -> None:
        """Active une recherche locale BM25 quand Qdrant n'est pas disponible."""
        if self.docs_cache.exists():
            self._load_docs_cache()

        if self.all_docs:
            self._build_hybrid_retriever()
            self.is_ready = True
            log.info(
                f"ℹ️ Mode local activé ({reason}) — BM25 uniquement avec {len(self.all_docs)} documents"
            )
        else:
            self.is_ready = False
            log.info(f"ℹ️ Mode local activé ({reason}) — aucun cache local disponible")

    def _documents_from_course_data(
        self,
        course_data: dict,
        domain: str = "general",
        course: str = "generic",
        course_id: str | None = None,
    ) -> list[Document]:
        documents: list[Document] = []
        source_file = course_data.get("file_path", "")
        slides = course_data.get("slides", []) or []
        language = course_data.get("language", "")

        for chapter_index, chapter in enumerate(course_data.get("chapters", []), start=1):
            chapter_idx = int(chapter.get("order") or chapter.get("chapter_idx") or chapter_index)
            chapter_title = chapter.get("title") or course_data.get("title") or f"Chapter {chapter_idx}"

            for section_index, section in enumerate(chapter.get("sections", []), start=1):
                content = (section.get("content") or "").strip()
                if len(content) < 10:
                    continue

                page_index = int(section.get("page_index") or section.get("order") or section_index)
                slide_index = max(0, page_index - 1)
                image_url = (section.get("image_url") or "").strip()
                if not image_url and 0 <= slide_index < len(slides):
                    image_url = slides[slide_index]

                documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "source_file": source_file,
                            "chunk_idx": len(documents),
                            "domain": domain,
                            "course": course_id or course,
                            "language": section.get("language") or language,
                            "original_text": content[:500],
                            "content_hash": hashlib.md5(content.encode()).hexdigest()[:8],
                            "chapter_idx": chapter_idx,
                            "chapter_title": chapter_title,
                            "slide_idx": page_index,
                            "section_title": section.get("title") or "",
                            "image_url": image_url,
                        },
                    )
                )

        return documents

    def run_ingestion_pipeline_from_course_data(
        self,
        course_data: dict,
        domain: str = "general",
        course: str = "generic",
        course_id: str | None = None,
        incremental: bool = True,
    ) -> bool:
        if not self._embeddings_ok or self.embeddings is None:
            if not self._switch_to_local_embeddings("embeddings unavailable before structured ingestion"):
                log.info(
                    "⚠️  run_ingestion_pipeline_from_course_data ignoré : embeddings indisponibles."
                )
                return False

        t0 = time.time()
        documents = self._documents_from_course_data(
            course_data,
            domain=domain,
            course=course,
            course_id=course_id,
        )

        if not documents:
            log.error("Structured ingestion produced no documents.")
            return False

        ok = self._store_documents(documents, incremental=incremental)
        if ok:
            self.is_ready = True
            elapsed = time.time() - t0
            log.info(f"✅ Structured ingestion terminée en {elapsed:.1f}s ({len(documents)} docs)")
        return ok

    # ══════════════════════════════════════════════════════════════════════════
    #  INGESTION GÉNÉRIQUE (Tous domaines/cours)
    # ══════════════════════════════════════════════════════════════════════════

    def run_ingestion_pipeline_for_files(
        self,
        file_paths: list[str],
        domain: str = "general",
        course: str = "generic",
        course_id: str | None = None,  # ✅ Add course_id UUID parameter
        incremental: bool = True,
    ) -> bool:
        # ── Vérification préalable : embeddings disponibles ? ─────────────────
        if not self._embeddings_ok or self.embeddings is None:
            if not self._switch_to_local_embeddings("embeddings unavailable before ingestion"):
                log.info(
                    "⚠️  run_ingestion_pipeline_for_files ignoré : "
                    "embeddings OpenAI non disponibles (quota dépassé ?). "
                    "Le cours est quand même sauvegardé en DB / local."
                )
                return False   # False = pas indexé, mais PAS une exception → import OK

        t0 = time.time()
        log.info("=" * 60)
        log.info(f"🚀 Ingestion — {len(file_paths)} fichier(s) | incremental={incremental}")
        log.info("=" * 60)

        elements = self._partition_files(file_paths)
        if not elements:
            log.error("Partitioning produced no elements.")
            return False

        chunks = self._create_chunks_by_title(elements)
        if not chunks:
            log.error("Chunking produced no chunks.")
            return False

        documents = self._summarise_chunks(chunks, domain=domain, course=course, course_id=course_id)
        if not documents:
            log.error("Summarization produced no documents.")
            return False

        ok = self._store_documents(documents, incremental=incremental)
        if ok:
            self.is_ready = True
            elapsed = time.time() - t0
            log.info(f"✅ Ingestion terminée en {elapsed:.1f}s ({len(documents)} docs)")
        return ok

    # ══════════════════════════════════════════════════════════════════════════
    #  RETRIEVAL HYBRIDE AVEC ISOLATION PAR CHAPITRE
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _doc_source_key(doc: Document) -> tuple:
        metadata = doc.metadata or {}
        return (
            metadata.get("source_file", ""),
            metadata.get("chapter_idx"),
            metadata.get("slide_idx"),
        )

    @staticmethod
    def _doc_signature(doc: Document) -> str:
        return _normalize_text_for_diversity(doc.page_content)

    @classmethod
    def _is_near_duplicate(cls, left: str, right: str) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True

        ratio = SequenceMatcher(None, left, right).ratio()
        if ratio >= 0.9:
            return True

        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return False

        overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
        return overlap >= 0.88

    def _dedupe_scored_docs(
        self,
        scored_docs: list[tuple[Document, float, str]],
        max_results: int,
    ) -> list[tuple[Document, float, str]]:
        unique_docs: list[tuple[Document, float, str]] = []
        seen_signatures: list[str] = []

        for doc, confidence, source_info in scored_docs:
            signature = self._doc_signature(doc)

            if any(self._is_near_duplicate(signature, seen) for seen in seen_signatures[-6:]):
                continue

            unique_docs.append((doc, confidence, source_info))
            if signature:
                seen_signatures.append(signature)

            if len(unique_docs) >= max_results:
                break

        return unique_docs or scored_docs[:max_results]

    @staticmethod
    def _build_chat_messages(
        system_prompt: str,
        history: list[dict],
        user_content: str,
    ) -> list[Any]:
        messages: list[Any] = [SystemMessage(content=system_prompt)]

        for msg in history[-6:]:
            role = (msg.get("role") or "").lower()
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            if role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "user":
                messages.append(HumanMessage(content=content))

        messages.append(HumanMessage(content=user_content))
        return messages

    def _dedupe_answer_text(self, text: str) -> str:
        clean_text = text.strip()
        if not clean_text:
            return clean_text

        sentences = re.split(r"(?<=[.!?])\s+", clean_text)
        kept_sentences: list[str] = []
        seen_signatures: list[str] = []

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            signature = _normalize_text_for_diversity(sentence)
            if not signature:
                continue
            if any(self._is_near_duplicate(signature, seen) for seen in seen_signatures[-4:]):
                continue

            kept_sentences.append(sentence)
            seen_signatures.append(signature)

        deduped = " ".join(kept_sentences).strip()
        return deduped or clean_text

    def retrieve_chunks(
        self,
        query: str,
        k: int = 5,
        current_chapter_idx: int | None = None,
        strict_chapter: bool = False,
        min_chunk_length: int = 50,  # Filter out tiny chunks
        course_id: str | None = None,  # ✅ Filter results by course_id
    ) -> list[tuple[Document, float, str]]:
        """
        Recherche hybride BM25 + Vectorielle + RRF avec scores de confiance.

        AMÉLIORATIONS :
        - Score de confiance pour chaque chunk
        - Filtrage des petits chunks inutiles
        - Source (chapter + file) incluse
        - Isolation par chapitre optionnelle
        - Isolation par cours optionnelle (évite contamination cross-course)

        Args:
            query:               Question de l'étudiant
            k:                   Nombre de chunks à retourner
            current_chapter_idx: Index du chapitre en cours (1-7 pour DM)
            strict_chapter:      Forcer l'isolation au chapitre courant
            min_chunk_length:    Longueur minimum du chunk (défaut 50 chars)
            course_id:           Cours actuel (optionnel, scoped retrieval)

        Returns:
            List of (Document, confidence_score, source_info)
        """
        if not self.is_ready:
            log.warning("RAG not ready — returning empty results")
            return []

        log.info(f"🔍 Retrieval | ch={current_chapter_idx} | strict={strict_chapter} | course={course_id} | q='{query[:60]}'")

        # ── Recherche vectorielle (avec filtre Qdrant si strict) ──────────────
        vector_docs = self._vector_search(query, k * 3, current_chapter_idx if strict_chapter else None, course_id=course_id)

        # ── Recherche BM25 ─────────────────────────────────────────────────────
        bm25_docs = self._bm25_search(query, k * 3, course_id=course_id)

        # ── RRF avec boost chapitre ────────────────────────────────────────────
        fused = self._rrf_with_chapter_boost(
            vector_docs, bm25_docs,
            current_chapter_idx=current_chapter_idx,
            chapter_boost=0.35,
        )

        # ── Filter + Score + Source ────────────────────────────────────────────
        results_with_scores = []
        for doc in fused:
            # Skip tiny chunks
            if len(doc.page_content) < min_chunk_length:
                continue
            
            # Compute confidence score (0-1)
            confidence = self._compute_chunk_confidence(doc, query)
            
            # Get source info
            source_info = self._format_source_info(doc)
            
            results_with_scores.append((doc, confidence, source_info))
        
        # Return top k with diversity to avoid repeated explanations
        top_results = self._dedupe_scored_docs(results_with_scores, k)
        log.info(f"✅ {len(top_results)} chunks retenus (avg confidence: {sum(s[1] for s in top_results)/max(1,len(top_results)):.2f})")
        return top_results

    def _vector_search(
        self, query: str, k: int,
        chapter_filter: int | None = None,
        course_id: str | None = None,
    ) -> list[Document]:
        """Recherche vectorielle Qdrant avec filtres optionnels sur chapter_idx et course_id.
        
        Utilise embedding_cache pour éviter recalcul des embeddings.
        """
        if not self.vectorstore:
            return []
        try:
            cache_namespace = self._embedding_cache_namespace()
            # 🔄 Vérifier cache avant de générer embedding
            query_embedding = embedding_cache.get(query, namespace=cache_namespace)
            if query_embedding is None:
                # Générer embedding et sauvegarder en cache
                query_embedding = self.embeddings.embed_query(query)
                embedding_cache.set(query, query_embedding, namespace=cache_namespace)
                log.debug(f"📍 Query embedding calculé et cachéé: {query[:50]}...")
            else:
                log.debug(f"📍 Query embedding récupéré du cache: {query[:50]}...")
            
            # ✅ Build Qdrant filter with both chapter_idx and course_id
            filter_conditions = []
            
            if chapter_filter is not None:
                filter_conditions.append(
                    FieldCondition(
                        key="metadata.chapter_idx",
                        match=MatchValue(value=chapter_filter)
                    )
                )
            
            if course_id is not None and course_id.strip():
                filter_conditions.append(
                    FieldCondition(
                        key="metadata.course",
                        match=MatchValue(value=course_id)
                    )
                )
            
            qdrant_filter = None
            if filter_conditions:
                qdrant_filter = Filter(must=filter_conditions) if len(filter_conditions) > 1 else Filter(must=[filter_conditions[0]])
            
            if qdrant_filter:
                retriever = self.vectorstore.as_retriever(
                    search_kwargs={"k": k, "filter": qdrant_filter}
                )
            else:
                retriever = self.vectorstore.as_retriever(search_kwargs={"k": k})
            
            # Invoker retriever avec embedding en cache
            return retriever.invoke(query)
        except Exception as exc:
            log.warning(f"Vector search error: {exc}")
            return []

    def _bm25_search(self, query: str, k: int, course_id: str | None = None) -> list[Document]:
        if not self.bm25_retriever:
            return []
        try:
            self.bm25_retriever.k = k
            docs = self.bm25_retriever.invoke(query)
            
            # ✅ Filter by course_id if specified
            if course_id is not None and course_id.strip():
                docs = [
                    doc for doc in docs
                    if doc.metadata.get("course") == course_id
                ]
            
            return docs
        except Exception as exc:
            log.warning(f"BM25 search error: {exc}")
            return []

    def _rrf_with_chapter_boost(
        self,
        vector_docs: list[Document],
        bm25_docs: list[Document],
        current_chapter_idx: int | None,
        chapter_boost: float = 0.3,
        rrf_k: int = 60,
    ) -> list[Document]:
        """
        Reciprocal Rank Fusion avec boost pour le chapitre courant.
        Chunks hors-chapitre reçoivent une pénalité si current_chapter_idx défini.
        """
        scores: dict[str, float] = {}
        docs_map: dict[str, Document] = {}

        def _doc_id(doc: Document) -> str:
            return doc.metadata.get("content_hash", "") or \
                   hashlib.md5(doc.page_content[:100].encode()).hexdigest()[:12]

        for rank, doc in enumerate(vector_docs):
            did = _doc_id(doc)
            scores[did] = scores.get(did, 0.0) + 1.0 / (rrf_k + rank + 1)
            docs_map[did] = doc

        for rank, doc in enumerate(bm25_docs):
            did = _doc_id(doc)
            scores[did] = scores.get(did, 0.0) + 1.0 / (rrf_k + rank + 1)
            docs_map[did] = doc

        # Boost / pénalité chapitre
        if current_chapter_idx is not None:
            for did, doc in docs_map.items():
                doc_ch = doc.metadata.get("chapter_idx")
                if doc_ch == current_chapter_idx:
                    scores[did] = scores[did] + chapter_boost
                elif doc_ch is not None:
                    # Pénalité légère pour les chunks d'autres chapitres
                    scores[did] = scores[did] * 0.7

        sorted_ids = sorted(scores, key=lambda x: -scores[x])
        return [docs_map[did] for did in sorted_ids if did in docs_map]

    def _compute_chunk_confidence(self, doc: Document, query: str) -> float:
        """
        Calcule un score de confiance (0-1) pour un chunk.
        
        Facteurs:
        - Présence du sujet dans le chunk
        - Longueur du chunk (plus long = plus détaillé)
        - Proximité chapitre courant
        """
        confidence = 0.5  # baseline
        
        # Bonus: sujet mentionné dans le chunk
        query_words = set(query.lower().split())
        chunk_words = set(doc.page_content.lower().split())
        overlap = len(query_words & chunk_words) / max(len(query_words), 1)
        confidence += overlap * 0.3
        
        # Bonus: longueur chunk (plus détaillé = plus utile)
        chunk_len = len(doc.page_content)
        if chunk_len > 500:
            confidence += 0.15
        elif chunk_len > 250:
            confidence += 0.08
        
        # Bonus: source de qualité
        metadata = doc.metadata or {}
        if metadata.get("chapter_idx"):
            confidence += 0.05
        
        return min(1.0, confidence)

    def _format_source_info(self, doc: Document) -> str:
        """Formate les infos source pour affichage."""
        metadata = doc.metadata or {}
        parts = []
        
        if chapter_idx := metadata.get("chapter_idx"):
            if chapter_title := metadata.get("chapter_title"):
                parts.append(f"Ch{chapter_idx}: {chapter_title}")
            else:
                parts.append(f"Ch{chapter_idx}")
        
        if slide_idx := metadata.get("slide_idx"):
            parts.append(f"p{slide_idx}")
        
        if source_file := metadata.get("source_file"):
            parts.append(f"({Path(source_file).stem})")
        
        return " | ".join(parts) if parts else "Unknown source"

    # ══════════════════════════════════════════════════════════════════════════
    #  DEBUG ENDPOINT SUPPORT
    # ══════════════════════════════════════════════════════════════════════════

    def debug_retrieve(
        self,
        query: str,
        k: int = 10,
        current_chapter_idx: int | None = None,
    ) -> dict:
        """
        DEBUG: Retourne chunks avec ALL details (scores, sources, confiance).
        Utile pour l'endpoint /debug/rag_test
        """
        chunks_with_scores = self.retrieve_chunks(
            query, k=k, current_chapter_idx=current_chapter_idx
        )
        
        return {
            "query": query,
            "total_chunks": len(chunks_with_scores),
            "chunks": [
                {
                    "content": doc.page_content[:300],
                    "confidence": round(confidence, 3),
                    "source": source_info,
                    "metadata": {
                        "chapter": doc.metadata.get("chapter_idx"),
                        "chapter_title": doc.metadata.get("chapter_title"),
                        "language": doc.metadata.get("language"),
                        "content_length": len(doc.page_content),
                    }
                }
                for doc, confidence, source_info in chunks_with_scores
            ]
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  GÉNÉRATION DE RÉPONSE PÉDAGOGIQUE
    # ══════════════════════════════════════════════════════════════════════════

    def generate_final_answer(
        self,
        retrieved_chunks: list[tuple] | list[Document],  # Accept both formats
        question: str | None = None,
        query: str | None = None,
        history: list[dict] | None = None,
        language: str = "fr",
        student_level: str = "université",
        current_chapter_title: str = "",
        current_section_title: str = "",
    ) -> tuple[str, float]:  # Returns (answer, confidence)
        """
        Génère une réponse pédagogique avec score de confiance.
        
        Returns:
            Tuple of (answer_text, confidence_score)
            - confidence_score = moyenne des scores des chunks utilisés
        """
        question = question if question is not None else (query or "")
        history = history or []

        if not retrieved_chunks:
            return (self._no_answer_message(language), 0.0)

        # Gérer two formats: new (doc, conf, source) ou old (doc only)
        docs = []
        chunk_confidences = []
        
        for item in retrieved_chunks:
            if isinstance(item, tuple) and len(item) >= 2:
                docs.append(item[0])  # doc
                chunk_confidences.append(item[1])  # confidence
            else:
                docs.append(item)
                chunk_confidences.append(0.5)

        deduped_pairs = self._dedupe_scored_docs(
            list(zip(docs, chunk_confidences, [""] * len(docs))),
            max_results=5,
        )
        docs = [doc for doc, _, _ in deduped_pairs]
        chunk_confidences = [confidence for _, confidence, _ in deduped_pairs]
        
        # Construire le contexte RAG
        context_parts = []
        for i, doc in enumerate(docs[:5]):
            ch_title  = doc.metadata.get("chapter_title", "")
            slide_idx = doc.metadata.get("slide_idx")
            slide_ref = f" (slide {slide_idx})" if slide_idx else ""
            prefix    = f"[Ch: {ch_title}{slide_ref}]\n" if ch_title else ""
            context_parts.append(f"{prefix}{doc.page_content}")

        context_str = "\n\n---\n\n".join(context_parts)

        # Construire le prompt système du cours
        system_prompt = self._build_course_system_prompt(
            language=language,
            student_level=student_level,
            current_chapter_title=current_chapter_title,
            current_section_title=current_section_title,
        )

        user_content = f"EXTRAITS DU COURS :\n{context_str}\n\n---\n\nQUESTION : {question}"

        try:
            if self._openai_disabled_reason:
                raise RuntimeError(f"OpenAI disabled: {self._openai_disabled_reason}")

            if not self._openai_disabled_reason:
                llm = ChatOpenAI(model=LLM_ANSWER, temperature=0.4, max_tokens=500, max_retries=0)
                response = llm.invoke(self._build_chat_messages(system_prompt, history, user_content))
                answer = self._clean_for_speech(response.content.strip())
                answer = self._dedupe_answer_text(answer)

                # Moyenne des confiances des chunks utilisés
                avg_confidence = sum(chunk_confidences) / max(len(chunk_confidences), 1) if chunk_confidences else 0.5

                log.info(f"✅ Réponse générée : {len(answer)} chars | confidence={avg_confidence:.2f}")
                return (answer, avg_confidence)
        except Exception as exc:
            is_disabled_exc = str(exc).lower().startswith("openai disabled:")
            if is_disabled_exc:
                log.info(f"ℹ️ OpenAI désactivé pour ce RAG ({self._openai_disabled_reason}) → Ollama prioritaire")
            elif self._should_disable_openai(exc):
                self._disable_openai(str(exc))
                log.error(f"❌ OpenAI error: {exc} → Trying Ollama fallback...")
            elif not is_disabled_exc:
                log.error(f"❌ OpenAI error: {exc} → Trying Ollama fallback...")
            
            # Try Ollama fallback
            try:
                from modules.ai.local_llm import LocalLLMFallback
                import requests
                
                fallback_llm = LocalLLMFallback(model="mistral")
                if fallback_llm.available:
                    log.info(f"🖥️ Ollama fallback ({fallback_llm.base_url}) with Mistral...")
                    
                    payload = {
                        "model": "mistral",
                        "prompt": f"{system_prompt}\n\n{user_content}",
                        "temperature": 0.4,
                        "num_predict": 500,
                        "stream": False,
                    }
                    response = requests.post(
                        f"{fallback_llm.base_url}/api/generate",
                        json=payload,
                        timeout=None,  # Pas de timeout pour laisser Ollama répondre à son rythme
                    )
                    
                    if response.status_code == 200:
                        ollama_text = response.json().get("response", "").strip()
                        if ollama_text:
                            answer = self._clean_for_speech(ollama_text)
                            answer = self._dedupe_answer_text(answer)
                            avg_confidence = sum(chunk_confidences) / max(len(chunk_confidences), 1) if chunk_confidences else 0.5
                            log.info(f"✅ Ollama OK: {len(answer)} chars")
                            return (answer, avg_confidence)
            except requests.exceptions.Timeout:
                log.error("❌ Ollama request failed or was interrupted")
            except Exception as fallback_err:
                log.error(f"❌ Ollama fallback failed: {fallback_err}")
            
            # All failed - return error
            return (self._error_message(language), 0.0)

    async def generate_final_answer_stream(
        self,
        retrieved_chunks: list[Document],
        question: str | None = None,
        query: str | None = None,
        history: list[dict] | None = None,
        language: str = "fr",
        student_level: str = "université",
        current_chapter_title: str = "",
        current_section_title: str = "",
    ):
        """
        🚀 STREAMING VERSION: Génère une réponse par chunks (phrases complètes).
        
        Yields:
            Tuples of (sentence_text, full_response_so_far)
            Permet streaming LLM → TTS en temps réel
        """
        question = question if question is not None else (query or "")
        history = history or []

        if not retrieved_chunks:
            yield (self._no_answer_message(language), "")
            return

        if isinstance(retrieved_chunks[0], tuple):
            docs_only = [item[0] for item in retrieved_chunks if item]
        else:
            docs_only = list(retrieved_chunks)

        deduped_docs = self._dedupe_scored_docs(
            [(doc, 0.5, "") for doc in docs_only],
            max_results=5,
        )
        docs_only = [doc for doc, _, _ in deduped_docs]

        # Construire le contexte RAG
        context_parts = []
        for i, doc in enumerate(docs_only[:5]):
            ch_title  = doc.metadata.get("chapter_title", "")
            slide_idx = doc.metadata.get("slide_idx")
            slide_ref = f" (slide {slide_idx})" if slide_idx else ""
            prefix    = f"[Ch: {ch_title}{slide_ref}]\n" if ch_title else ""
            context_parts.append(f"{prefix}{doc.page_content}")

        context_str = "\n\n---\n\n".join(context_parts)

        # Construire le prompt système du cours
        system_prompt = self._build_course_system_prompt(
            language=language,
            student_level=student_level,
            current_chapter_title=current_chapter_title,
            current_section_title=current_section_title,
        )

        user_content = f"EXTRAITS DU COURS :\n{context_str}\n\n---\n\nQUESTION : {question}"

        try:
            if self._openai_disabled_reason:
                raise RuntimeError(f"OpenAI disabled: {self._openai_disabled_reason}")

            if not self._openai_disabled_reason:
                llm = ChatOpenAI(model=LLM_ANSWER, temperature=0.4, max_tokens=500, max_retries=0)

                # Stream tokens from LLM (synchronous iterator)
                full_response = ""
                display_response = ""
                display_sentences: list[str] = []
                seen_signatures: list[str] = []
                buffer = ""
                sentence_endings = (".", "!", "?", ":\n", ";\n")

                for chunk in llm.stream(self._build_chat_messages(system_prompt, history, user_content)):
                    token = chunk.content if hasattr(chunk, 'content') else str(chunk)
                    full_response += token
                    buffer += token

                    # Check for sentence endings
                    if any(buffer.endswith(ending) for ending in sentence_endings):
                        sentence = buffer.strip()
                        if len(sentence) > 3:  # Minimum meaningful sentence length
                            cleaned = self._clean_for_speech(sentence)
                            signature = _normalize_text_for_diversity(cleaned)
                            if signature and any(self._is_near_duplicate(signature, seen) for seen in seen_signatures[-4:]):
                                log.info(f"⏭️ Repetition skipped: {cleaned[:60]}…")
                            else:
                                if signature:
                                    seen_signatures.append(signature)
                                display_sentences.append(cleaned)
                                display_response = " ".join(display_sentences).strip()
                                log.info(f"📤 Streaming chunk: {cleaned[:60]}…")
                                yield (cleaned, display_response)
                        buffer = ""

                # Yield remaining buffer
                if buffer.strip():
                    cleaned = self._clean_for_speech(buffer.strip())
                    signature = _normalize_text_for_diversity(cleaned)
                    if len(cleaned) > 3 and not (signature and any(self._is_near_duplicate(signature, seen) for seen in seen_signatures[-4:])):
                        if signature:
                            seen_signatures.append(signature)
                        display_sentences.append(cleaned)
                        display_response = " ".join(display_sentences).strip()
                        log.info(f"📤 Final chunk: {cleaned[:60]}…")
                        yield (cleaned, display_response)

                if not display_response:
                    display_response = self._dedupe_answer_text(self._clean_for_speech(full_response.strip()))

                log.info(f"✅ Stream complété : {len(display_response or full_response)} chars total")

        except Exception as exc:
            is_disabled_exc = str(exc).lower().startswith("openai disabled:")
            if is_disabled_exc:
                log.info(f"ℹ️ OpenAI désactivé pour ce RAG ({self._openai_disabled_reason}) → Ollama prioritaire")
            elif self._should_disable_openai(exc):
                self._disable_openai(str(exc))
                log.error(f"❌ OpenAI LLM stream error: {exc}")
            elif not is_disabled_exc:
                log.error(f"❌ OpenAI LLM stream error: {exc}")
            log.info("🖥️ Activating Ollama fallback for streaming...")
            
            # ══════════════════════════════════════════════════════════
            # FALLBACK: Ollama + Mistral (synchrone, mais garantit une réponse)
            # ══════════════════════════════════════════════════════════
            try:
                from modules.ai.local_llm import LocalLLMFallback
                fallback_llm = LocalLLMFallback(model="mistral")
                
                if fallback_llm.available:
                    log.info(f"🖥️ Utilizing Ollama ({fallback_llm.base_url}) with Mistral model...")
                    
                    # Build fallback prompt
                    fallback_prompt = f"{system_prompt}\n\n{user_content}"
                    
                    # Call Ollama with streaming (much faster response)
                    import requests
                    import json
                    try:
                        payload = {
                            "model": "mistral",
                            "prompt": fallback_prompt,
                            "temperature": 0.4,
                            "num_predict": 500,
                            "stream": True,  # ✅ STREAMING for fast incremental response
                        }
                        response = requests.post(
                            f"{fallback_llm.base_url}/api/generate",
                            json=payload,
                            timeout=None,  # Pas de timeout pour laisser Ollama répondre à son rythme
                            stream=True,  # ✅ Stream chunks from requests
                        )
                        
                        if response.status_code == 200:
                            full_ollama_response = ""
                            display_sentences_ollama = []
                            seen_signatures_ollama = []
                            buffer_ollama = ""
                            
                            # Stream NDJSON response from Ollama
                            for line in response.iter_lines():
                                if not line:
                                    continue
                                try:
                                    chunk_data = json.loads(line)
                                    chunk_text = chunk_data.get("response", "")
                                    if chunk_text:
                                        full_ollama_response += chunk_text
                                        buffer_ollama += chunk_text
                                        
                                        # Check for sentence endings to yield progressively
                                        sentence_endings = (".", "!", "?", ":\n", ";\n")
                                        if any(buffer_ollama.endswith(ending) for ending in sentence_endings):
                                            sentence = buffer_ollama.strip()
                                            if len(sentence) > 3:
                                                cleaned = self._clean_for_speech(sentence)
                                                signature = _normalize_text_for_diversity(cleaned)
                                                if signature and any(self._is_near_duplicate(signature, seen) for seen in seen_signatures_ollama[-4:]):
                                                    log.info(f"⏭️ Ollama: Repetition skipped")
                                                else:
                                                    if signature:
                                                        seen_signatures_ollama.append(signature)
                                                    display_sentences_ollama.append(cleaned)
                                                    display_response_ollama = " ".join(display_sentences_ollama).strip()
                                                    log.info(f"📤 Ollama chunk: {cleaned[:60]}…")
                                                    yield (cleaned, display_response_ollama)
                                            buffer_ollama = ""
                                except json.JSONDecodeError:
                                    continue
                            
                            # Yield remaining buffer from Ollama
                            if buffer_ollama.strip():
                                cleaned = self._clean_for_speech(buffer_ollama.strip())
                                signature = _normalize_text_for_diversity(cleaned)
                                if len(cleaned) > 3 and not (signature and any(self._is_near_duplicate(signature, seen) for seen in seen_signatures_ollama[-4:])):
                                    if signature:
                                        seen_signatures_ollama.append(signature)
                                    display_sentences_ollama.append(cleaned)
                                    display_response_ollama = " ".join(display_sentences_ollama).strip()
                                    log.info(f"📤 Ollama final chunk: {cleaned[:60]}…")
                                    yield (cleaned, display_response_ollama)
                            
                            log.info(f"✅ Ollama fallback OK: {len(full_ollama_response)} chars")
                            return
                    except requests.exceptions.Timeout:
                        log.error("❌ Ollama request failed or was interrupted")
                    except Exception as ollama_err:
                        log.error(f"❌ Ollama call failed: {ollama_err}")
            except Exception as fallback_err:
                log.error(f"❌ Ollama fallback activation failed: {fallback_err}")
            
            # If all else fails, yield error message
            error_msg = self._error_message(language)
            log.error(f"❌ Both OpenAI and Ollama failed - returning error message")
            yield (error_msg, "")

    def generate_quiz(
        self,
        retrieved_chunks: list[tuple] | list[Document],
        question: str | None = None,
        query: str | None = None,
        history: list[dict] | None = None,
        language: str = "fr",
        student_level: str = "université",
        current_chapter_title: str = "",
        current_section_title: str = "",
        question_count: int = 3,
    ) -> tuple[dict, float]:
        """Generate a short multiple-choice quiz grounded in retrieved course chunks."""
        topic = (question if question is not None else (query or "")).strip()
        history = history or []
        desired_question_count = max(1, min(int(question_count or 3), 5))

        def _fallback_quiz_payload() -> dict:
            base_topic = topic or current_section_title or current_chapter_title or "ce cours"
            anchor = current_section_title or current_chapter_title or base_topic
            return {
                "title": "Quiz rapide",
                "topic": base_topic,
                "difficulty": student_level,
                "language": language[:2].lower(),
                "chapter_title": current_chapter_title or "",
                "section_title": current_section_title or "",
                "questions": [
                    {
                        "question": f"Quel est le point principal de {anchor} ?",
                        "options": [
                            f"L'idee principale de {anchor}",
                            "Un detail secondaire du cours",
                            "Un element hors sujet",
                            "Une erreur de formulation",
                        ],
                        "correct_index": 0,
                        "explanation": f"La bonne reponse reprend le theme central de {anchor}.",
                        "practical": f"Appliquez cette idee a un cas concret de {anchor}.",
                        "practical_answer": f"On retient l'application la plus directe de {anchor} dans un cas reel.",
                    }
                ],
            }

        def _parse_quiz_payload(raw_text: str) -> dict | None:
            if not raw_text:
                return None

            text = raw_text.strip()
            if not text:
                return None

            candidates = [text]
            if text.startswith("```"):
                fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
                if fenced:
                    candidates.insert(0, fenced)

            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidates.insert(0, text[start : end + 1])

            for candidate in candidates:
                try:
                    payload = json.loads(candidate)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    return payload
            return None

        def _normalize_quiz_payload(payload: dict | None) -> dict | None:
            if not isinstance(payload, dict):
                return None

            questions_raw = payload.get("questions")
            if not isinstance(questions_raw, list):
                return None

            normalized_questions: list[dict] = []
            for item in questions_raw[:desired_question_count]:
                if not isinstance(item, dict):
                    continue

                question_text = str(item.get("question") or item.get("prompt") or "").strip()
                options_raw = item.get("options") or item.get("choices") or []
                if isinstance(options_raw, str):
                    options_raw = [line.strip() for line in options_raw.splitlines() if line.strip()]
                if not isinstance(options_raw, list):
                    options_raw = []
                options = [str(option).strip() for option in options_raw if str(option).strip()]
                if len(options) < 2:
                    continue

                try:
                    correct_index = int(item.get("correct_index", item.get("answer_index", 0)))
                except Exception:
                    correct_index = 0
                correct_index = max(0, min(correct_index, len(options) - 1))

                explanation = str(item.get("explanation") or item.get("feedback") or "").strip()
                if not question_text:
                    continue

                normalized_questions.append(
                    {
                        "question": question_text,
                        "options": options[:4],
                        "correct_index": correct_index,
                        "explanation": explanation,
                    }
                )

            if not normalized_questions:
                return None

            return {
                "title": str(payload.get("title") or payload.get("quiz_title") or "Quiz rapide").strip() or "Quiz rapide",
                "topic": str(payload.get("topic") or topic or current_section_title or current_chapter_title or "").strip(),
                "difficulty": str(payload.get("difficulty") or student_level).strip(),
                "language": str(payload.get("language") or language[:2].lower()).strip(),
                "chapter_title": str(payload.get("chapter_title") or current_chapter_title or "").strip(),
                "section_title": str(payload.get("section_title") or current_section_title or "").strip(),
                "questions": normalized_questions,
            }

        if not retrieved_chunks:
            return (_fallback_quiz_payload(), 0.0)

        if isinstance(retrieved_chunks[0], tuple):
            docs = [item[0] for item in retrieved_chunks if item]
            chunk_confidences = [float(item[1]) if len(item) > 1 and isinstance(item[1], (int, float)) else 0.5 for item in retrieved_chunks if item]
        else:
            docs = list(retrieved_chunks)
            chunk_confidences = [0.5 for _ in docs]

        deduped_docs = self._dedupe_scored_docs(
            [(doc, confidence, "") for doc, confidence in zip(docs, chunk_confidences)],
            max_results=5,
        )
        docs = [doc for doc, _, _ in deduped_docs]
        chunk_confidences = [confidence for _, confidence, _ in deduped_docs]

        context_parts = []
        for i, doc in enumerate(docs[:5]):
            ch_title = doc.metadata.get("chapter_title", "")
            slide_idx = doc.metadata.get("slide_idx")
            slide_ref = f" (slide {slide_idx})" if slide_idx else ""
            prefix = f"[Ch: {ch_title}{slide_ref}]\n" if ch_title else ""
            context_parts.append(f"{prefix}{doc.page_content}")

        context_str = "\n\n---\n\n".join(context_parts)
        avg_confidence = sum(chunk_confidences) / max(len(chunk_confidences), 1) if chunk_confidences else 0.5

        if language[:2].lower() == "en":
            system_prompt = (
                f"You are Smart Teacher. Create a short multiple-choice quiz grounded only in the provided course extracts. "
                f"Return ONLY valid JSON, no markdown, no extra text.\n\n"
                f"Required schema:\n"
                f"{{\n"
                f"  \"title\": \"Quick quiz\",\n"
                f"  \"topic\": \"...\",\n"
                f"  \"difficulty\": \"{student_level}\",\n"
                f"  \"language\": \"en\",\n"
                f"  \"chapter_title\": \"...\",\n"
                f"  \"section_title\": \"...\",\n"
                f"  \"questions\": [\n"
                f"    {{\"question\": \"...\", \"options\": [\"...\", \"...\", \"...\", \"...\"], \"correct_index\": 0, \"explanation\": \"...\", \"practical\": \"...\", \"practical_answer\": \"...\"}}\n"
                f"  ]\n"
                f"}}\n\n"
                f"Rules: use 2 to {desired_question_count} questions, exactly 4 options per question, one correct answer only, keep the questions concise, and add one short practical application plus its short model answer for each question."
            )
        else:
            system_prompt = (
                f"Tu es Smart Teacher. Cree un mini quiz a choix multiples base uniquement sur les extraits du cours fournis. "
                f"Reponds UNIQUEMENT en JSON valide, sans markdown ni texte en plus.\n\n"
                f"Schema attendu:\n"
                f"{{\n"
                f"  \"title\": \"Quiz rapide\",\n"
                f"  \"topic\": \"...\",\n"
                f"  \"difficulty\": \"{student_level}\",\n"
                f"  \"language\": \"fr\",\n"
                f"  \"chapter_title\": \"...\",\n"
                f"  \"section_title\": \"...\",\n"
                f"  \"questions\": [\n"
                f"    {{\"question\": \"...\", \"options\": [\"...\", \"...\", \"...\", \"...\"], \"correct_index\": 0, \"explanation\": \"...\", \"practical\": \"...\", \"practical_answer\": \"...\"}}\n"
                f"  ]\n"
                f"}}\n\n"
                f"Regles: propose 2 a {desired_question_count} questions, exactement 4 options par question, une seule bonne reponse, des distracteurs plausibles, et pour chaque question ajoute une courte application pratique avec sa courte reponse modele."
            )

        user_content = (
            f"LANGUE: {language}\n"
            f"NIVEAU: {student_level}\n"
            f"CHAPITRE: {current_chapter_title or 'N/A'}\n"
            f"SECTION: {current_section_title or 'N/A'}\n"
            f"THEME: {topic or current_section_title or current_chapter_title or 'le cours'}\n"
            f"NOMBRE_DE_QUESTIONS: {desired_question_count}\n\n"
            f"EXTRAITS DU COURS:\n{context_str}\n\n"
            f"Rends uniquement le JSON demande par le schema. Chaque question doit rester courte et couvrir un point verifiable dans les extraits."
        )

        normalized_payload: dict | None = None

        try:
            if self._openai_disabled_reason:
                raise RuntimeError(f"OpenAI disabled: {self._openai_disabled_reason}")

            if not self._openai_disabled_reason:
                llm = ChatOpenAI(model=LLM_ANSWER, temperature=0.35, max_tokens=800, max_retries=0)
                response = llm.invoke(self._build_chat_messages(system_prompt, history, user_content))
                normalized_payload = _normalize_quiz_payload(_parse_quiz_payload(response.content))
        except Exception as exc:
            is_disabled_exc = str(exc).lower().startswith("openai disabled:")
            if is_disabled_exc:
                log.info(f"ℹ️ OpenAI désactivé pour ce RAG ({self._openai_disabled_reason}) → Ollama quiz fallback prioritaire")
            elif self._should_disable_openai(exc):
                self._disable_openai(str(exc))
                log.error(f"❌ OpenAI quiz error: {exc} → Trying Ollama fallback...")
            elif not is_disabled_exc:
                log.error(f"❌ OpenAI quiz error: {exc} → Trying Ollama fallback...")

            try:
                from modules.ai.local_llm import LocalLLMFallback
                import requests

                fallback_llm = LocalLLMFallback(model="mistral")
                if fallback_llm.available:
                    log.info(f"🖥️ Ollama quiz fallback ({fallback_llm.base_url}) with Mistral...")

                    payload = {
                        "model": "mistral",
                        "prompt": f"{system_prompt}\n\n{user_content}",
                        "temperature": 0.35,
                        "num_predict": 800,
                        "stream": False,
                    }
                    response = requests.post(
                        f"{fallback_llm.base_url}/api/generate",
                        json=payload,
                        timeout=None,
                    )

                    if response.status_code == 200:
                        ollama_text = response.json().get("response", "").strip()
                        if ollama_text:
                            normalized_payload = _normalize_quiz_payload(_parse_quiz_payload(ollama_text))
            except requests.exceptions.Timeout:
                log.error("❌ Ollama quiz request failed or was interrupted")
            except Exception as fallback_err:
                log.error(f"❌ Ollama quiz fallback failed: {fallback_err}")

        if not normalized_payload:
            normalized_payload = _fallback_quiz_payload()

        normalized_payload["confidence"] = round(avg_confidence, 3)
        normalized_payload["question_count"] = len(normalized_payload.get("questions", []))
        return (normalized_payload, avg_confidence)

    # ══════════════════════════════════════════════════════════════════════════
    #  PIPELINE D'INGESTION INTERNE
    # ══════════════════════════════════════════════════════════════════════════

    def _partition_files(self, file_paths: list[str]) -> list:
        elements = []
        for fp in file_paths:
            try:
                resolved_fp = str(Path(fp).expanduser().resolve())
                elems = partition(filename=resolved_fp)
                log.info(f"  📄 {Path(resolved_fp).name} → {len(elems)} éléments")
                elements.extend(elems)
            except Exception as exc:
                log.error(f"  ❌ {fp}: {exc}")
        log.info(f"📦 Total éléments : {len(elements)}")
        return elements

    def _create_chunks_by_title(self, elements: list) -> list:
        try:
            chunks = chunk_by_title(elements, max_characters=1500, new_after_n_chars=1200)
            log.info(f"✂️  Chunks créés : {len(chunks)}")
            return chunks
        except Exception as exc:
            log.error(f"❌ Chunking error: {exc}")
            return []

    def _summarise_chunks(self, chunks: list, domain: str = "general", course: str = "generic", course_id: str | None = None) -> list[Document]:
        """Process chunks into documents with generic metadata (for backward compatibility)."""
        documents: list[Document] = []
        for i, chunk in enumerate(chunks):
            text = str(chunk).strip()
            if len(text) < 30:
                continue
            summary = self._get_or_create_summary(text, "")
            source  = self._extract_source_file(chunk)
            lang    = self._detect_language(text)

            doc = Document(
                page_content=summary or text,
                metadata={
                    "source_file":   source,
                    "chunk_idx":     i,
                    "domain":        domain,
                    "course":        course_id or course,  # ✅ Use course_id if provided (UUID), else fall back to course name
                    "language":      lang,
                    "original_text": text[:500],
                    "content_hash":  hashlib.md5(text.encode()).hexdigest()[:8],
                    "chapter_idx":   0,  # No chapter structure in generic ingestion
                    "chapter_title": "",
                    "slide_idx":     self._extract_page_number(chunk),
                }
            )
            documents.append(doc)

        if self.summary_cache:
            self._save_summary_cache()
        log.info(f"📝 Documents produits : {len(documents)}")
        return documents

    def _get_or_create_summary(self, text: str, chapter_context: str) -> str:
        """Résumé IA avec cache. Adapté pour le contenu DM."""
        key = hashlib.md5(text.encode()).hexdigest()
        if key in self.summary_cache:
            return self.summary_cache[key]

        if self._openai_disabled_reason:
            self.summary_cache[key] = text
            return text

        if len(text) < 120:
            self.summary_cache[key] = text
            return text

        try:
            llm = ChatOpenAI(model=LLM_SUMMARY, temperature=0.0, max_tokens=300, max_retries=0)
            ctx = f" (contexte : {chapter_context})" if chapter_context else ""
            prompt = (
                f"Tu es un assistant pédagogique expert dans ce cours{ctx}.\n"
                f"Résume ce contenu en 2-3 phrases claires et précises.\n"
                f"Conserve TOUS les termes techniques importants.\n"
                f"Ne simplifie pas la terminologie technique.\n\n"
                f"CONTENU :\n{text[:1200]}"
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            summary  = response.content.strip()
            self.summary_cache[key] = summary
            return summary
        except Exception as exc:
            log.warning(f"Summary error: {exc}")
            return text

    def _store_documents_once(
        self,
        documents: list[Document],
        full_documents: list[Document] | None = None,
    ) -> bool:
        documents_to_keep = full_documents if full_documents is not None else documents

        try:
            if not self.client:
                raise RuntimeError("Qdrant client unavailable")

            collection_exists = self.client.collection_exists(self.collection_name)
            if not collection_exists:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.current_embedding_dim, distance=Distance.COSINE),
                )

            self.vectorstore = QdrantVectorStore(
                client=self.client,
                collection_name=self.collection_name,
                embedding=self.embeddings,
            )
            docs_to_store = documents if collection_exists else documents_to_keep
            self.vectorstore.add_documents(docs_to_store)
            self.all_docs = documents_to_keep
            self._build_hybrid_retriever()
            self._save_docs_cache()
            self.is_ready = True
            log.info(f"✅ {len(docs_to_store)} documents stockés dans Qdrant ({self.collection_name}).")
            return True
        except Exception as exc:
            self.vectorstore = None
            self.all_docs = documents_to_keep
            self._build_hybrid_retriever()
            self._save_docs_cache()
            self.is_ready = bool(self.all_docs)
            log.info(
                f"ℹ️ Qdrant local indisponible ({exc}) — documents conservés localement, BM25 actif."
            )
            return bool(self.all_docs)

    def _store_documents(self, documents: list[Document], incremental: bool) -> bool:
        existing_docs = list(self.all_docs)
        full_documents = [*existing_docs, *documents]

        try:
            return self._store_documents_once(
                documents,
                full_documents=full_documents,
            )
        except Exception as exc:
            if self.embedding_source != "huggingface" and self._should_fallback_to_local_embeddings(exc):
                log.warning(
                    "⚠️ Local primary embeddings unavailable during ingestion; retrying with HuggingFaceEmbeddings."
                )
                if self._switch_to_local_embeddings(str(exc)):
                    try:
                        return self._store_documents_once(
                            full_documents,
                            full_documents=full_documents,
                        )
                    except Exception as retry_exc:
                        log.error(f"❌ Local fallback store error: {retry_exc}")
                        return False

            log.error(f"❌ Store error: {exc}")
            return False

    def _build_hybrid_retriever(self) -> None:
        if not self.all_docs:
            return
        try:
            self.bm25_retriever = BM25Retriever.from_documents(self.all_docs)
            log.info(f"✅ BM25 retriever construit ({len(self.all_docs)} docs)")
        except Exception as exc:
            log.warning(f"BM25 build error: {exc}")

    # ══════════════════════════════════════════════════════════════════════════
    #  PROMPTS PÉDAGOGIQUES
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _build_course_system_prompt(
        domain: str = "general",
        course: str = "generic",
        language: str = "fr",
        student_level: str = "licence",
        current_chapter_title: str = "",
        current_section_title: str = "",
    ) -> str:
        """
        Prompt système générique par domaine/cours.
        Contextualisé avec le chapitre et la section en cours.

        LANGUE : Strictement respectée. Instructions très claires.
        """
        domain_descriptions = {
            "general": "cours",
            "computer_science": "informatique",
            "mathematics": "mathématiques",
            "science": "sciences",
            "languages": "langues",
            "humanities": "humanités",
            "business": "gestion",
            "engineering": "ingénierie",
        }
        
        domain_desc = domain_descriptions.get(course, domain_descriptions.get(domain, domain.replace("_", " ").capitalize()))
        
        # Contexte chapitre/section
        ch_ctx = ""
        if current_chapter_title:
            if language[:2].lower() == "en":
                ch_ctx = f"\nWe are currently in chapter: '{current_chapter_title}'."
            else:
                ch_ctx = f"\nNous sommes actuellement dans le chapitre : '{current_chapter_title}'."
        if current_section_title:
            if language[:2].lower() == "en":
                ch_ctx += f" Section: '{current_section_title}'."
            else:
                ch_ctx += f" Section : '{current_section_title}'."

        base = {
            "fr": (
                f"Tu es Smart Teacher, un professeur expert en {domain_desc} "
                f"qui enseigne à des étudiants de niveau {student_level}.{ch_ctx}\n\n"
                f"RÈGLES ABSOLUES — tu PARLES, tu n'écris PAS :\n"
                f"- JAMAIS de markdown : pas de **, pas de #, pas de tirets -, pas de listes.\n"
                f"- JAMAIS de LaTeX : écris les formules en clair.\n"
                f"- Réponds comme tu PARLERAIS en cours : phrases naturelles, transitions fluides.\n"
                f"- Commence par : 'Bonne question !', 'Exactement !', 'Alors, pour ce concept...' etc.\n"
                f"- Utilise la terminologie technique appropriée.\n"
                f"- Si disponible, base-toi sur les extraits du cours fournis.\n"
                f"- Si plusieurs extraits disent la même chose, fusionne-les en une seule explication.\n"
                f"- Ne répète pas la même idée avec des mots proches.\n"
                f"- Un exemple concret et pertinent.\n"
                f"- 4 à 6 phrases naturelles. Termine par une question si concept difficile.\n"
                f"- [!!!CRITIQUE!!!] Réponds UNIQUEMENT en français. Aucune autre langue acceptée."
            ),
            "en": (
                f"You are Smart Teacher, an expert professor in {domain_desc} "
                f"teaching {student_level} level students.{ch_ctx}\n\n"
                f"ABSOLUTE RULES — you are SPEAKING, not writing:\n"
                f"- NEVER use markdown: no **, #, bullet points, numbered lists.\n"
                f"- NEVER use LaTeX: write formulas in plain words.\n"
                f"- Reply as if TALKING in class: natural sentences, smooth transitions.\n"
                f"- Start with: 'Great question!', 'Exactly!', 'So, for this concept...' etc.\n"
                f"- Use technical terminology accurately.\n"
                f"- Use course extracts provided when available.\n"
                f"- If several extracts say the same thing, merge them into one explanation.\n"
                f"- Do not repeat the same idea with different wording.\n"
                f"- Include a concrete relevant example.\n"
                f"- 4 to 6 natural sentences. End with a comprehension question if complex.\n"
                f"- [!!!CRITICAL!!!] Reply ONLY in English. No other language accepted."
            ),
        }
        return base.get(language[:2].lower(), base["fr"])

    # ══════════════════════════════════════════════════════════════════════════
    #  UTILITAIRES
    # ══════════════════════════════════════════════════════════════════════════

    def _detect_language(self, text: str) -> str:
        """Détecte la langue du texte."""
        if not text:
            return "en"
        fr_count  = len(re.findall(r'\b(le|la|les|de|du|des|un|une|et|est|qui|que|dans|pour|avec|sur|par)\b', text.lower()))
        en_count  = len(re.findall(r'\b(the|of|and|is|are|in|for|with|on|by|this|that|which|from)\b', text.lower()))
        if fr_count > en_count:
            return "fr"
        return "en"

    def _extract_source_file(self, chunk) -> str:
        meta = getattr(chunk, "metadata", None)
        if meta is None:
            return "unknown"
        return (
            getattr(meta, "filename", None)
            or getattr(meta, "file_path", None)
            or "unknown"
        )

    def _extract_page_number(self, chunk) -> int | None:
        meta = getattr(chunk, "metadata", None)
        page = getattr(meta, "page_number", None) if meta else None
        return int(page) if page is not None else None

    def _load_existing_db(self) -> None:
        if not self._embeddings_ok or self.embeddings is None:
            log.warning("⚠️  _load_existing_db ignoré : embeddings non disponibles (quota OpenAI ?)")
            return

        if self.docs_cache.exists():
            self._load_docs_cache()

        try:
            self.vectorstore = QdrantVectorStore(
                client=self.client,
                collection_name=self.collection_name,
                embedding=self.embeddings,
            )
            self.is_ready = True
            log.info(f"✅ Collection '{self.collection_name}' chargée.")
            if not self.all_docs:
                log.info("🔄 Pas de cache — chargement depuis Qdrant…")
                retriever  = self.vectorstore.as_retriever(search_kwargs={"k": 1000})
                self.all_docs = retriever.invoke(" ")
            self._build_hybrid_retriever()
        except Exception as exc:
            log.info(f"ℹ️ Load DB error ({exc}) — local fallback active")
            self._activate_local_retrieval_fallback(str(exc))

    def _save_docs_cache(self) -> None:
        try:
            data = [{"page_content": d.page_content, "metadata": d.metadata}
                    for d in self.all_docs]
            with open(self.docs_cache, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log.info(f"💾 Cache sauvegardé ({len(data)} docs → {self.docs_cache})")
        except Exception as exc:
            log.warning(f"Cache save error: {exc}")

    def _load_docs_cache(self) -> None:
        try:
            with open(self.docs_cache, encoding="utf-8") as f:
                data = json.load(f)
            self.all_docs = [Document(page_content=d["page_content"], metadata=d["metadata"])
                             for d in data]
            log.info(f"✅ Cache chargé ({len(self.all_docs)} docs)")
        except Exception as exc:
            log.warning(f"Cache load error: {exc}")

    def _save_summary_cache(self) -> None:
        try:
            with open(self.summary_cache_path, "w", encoding="utf-8") as f:
                json.dump(self.summary_cache, f, ensure_ascii=False)
        except Exception as exc:
            log.warning(f"Summary cache save error: {exc}")

    def _load_summary_cache(self) -> None:
        if self.summary_cache_path.exists():
            try:
                with open(self.summary_cache_path, encoding="utf-8") as f:
                    self.summary_cache = json.load(f)
                log.info(f"✅ Summary cache chargé ({len(self.summary_cache)} entrées)")
            except Exception:
                self.summary_cache = {}

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Supprime markdown et LaTeX pour la synthèse vocale."""
        import re
        text = re.sub(r'\\\[.*?\\\]', '', text, flags=re.DOTALL)
        text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)
        text = re.sub(r'\\\(.*?\\\)', '', text, flags=re.DOTALL)
        text = re.sub(r'\$[^$\n]+\$', '', text)
        text = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', text)
        text = re.sub(r'\\[a-zA-Z]+', '', text)
        text = re.sub(r'#{1,6}\s+', '', text)
        text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
        text = re.sub(r'_{1,3}([^_\n]+)_{1,3}', r'\1', text)
        text = re.sub(r'^\s*[-•–—]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+[.)]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\\n|\\t|\\r', ' ', text)
        text = text.replace('\\', '')
        text = re.sub(r'```[^`]*```', '', text, flags=re.DOTALL)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'  +', ' ', text)
        return text.strip()

    @staticmethod
    def _no_answer_message(language: str) -> str:
        return {
            "fr": "Je n'ai pas trouvé d'information pertinente dans le cours. Pouvez-vous reformuler votre question ?",
            "en": "I couldn't find relevant information in the course material. Could you rephrase your question?",
        }.get(language, "Je n'ai pas trouvé de réponse dans le cours.")

    @staticmethod
    def _error_message(language: str) -> str:
        return {
            "fr": "Une erreur s'est produite. Veuillez réessayer.",
            "en": "An error occurred. Please try again.",
        }.get(language, "Une erreur s'est produite.")

    def get_stats(self) -> dict:
        by_ch: dict[int, int] = {}
        subjects: dict[str, int] = {}
        languages: dict[str, int] = {}
        for doc in self.all_docs:
            ch = doc.metadata.get("chapter_idx", 0)
            by_ch[ch] = by_ch.get(ch, 0) + 1
            
            subj = doc.metadata.get("subject", "unknown")
            subjects[subj] = subjects.get(subj, 0) + 1
            
            lang = doc.metadata.get("language", "unknown")
            languages[lang] = languages.get(lang, 0) + 1
        
        # Ajouter stats cache
        cache_stats = embedding_cache.stats()
        
        return {
            "is_ready":        self.is_ready,
            "embeddings_ok":   self._embeddings_ok,
            "total_docs":      len(self.all_docs),
            "collection":      self.collection_name,
            "by_chapter":      by_ch,
            "subjects":        subjects,
            "languages":       languages,
            "cache_entries":   len(self.summary_cache),
            "bm25_ready":      self.bm25_retriever is not None,
            "embedding_cache": cache_stats,  # 🔄 Nouveau!
        }

    def delete_collection(self) -> None:
        if self.client and self.client.collection_exists(self.collection_name):
            self.client.delete_collection(self.collection_name)
            log.info(f"🗑️  Collection '{self.collection_name}' supprimée.")
        self.vectorstore = None
        self.bm25_retriever = None
        self.all_docs = []
        self.is_ready = False

    def reset(self) -> None:
        """
        Réinitialise complètement la base vectorielle Qdrant et le cache BM25.
        Utilisé avant une réingestion complète.
        """
        log.warning("🔄 Réinitialisation de la base RAG…")
        self.delete_collection()
        self.summary_cache.clear()
        if self.docs_cache.exists():
            self.docs_cache.unlink()
        if self.summary_cache_path.exists():
            self.summary_cache_path.unlink()
        log.info("✅ Base RAG réinitialisée (collection, BM25, caches)")