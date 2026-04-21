"""Vector database adapter for the agentic RAG workflow."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from uuid import uuid4

from config import Config
from qdrant_client.http.models import FieldCondition, Filter, FilterSelector, MatchValue

try:
    from langchain_core.documents import Document
except Exception:  # pragma: no cover - fallback for unusual environments
    Document = None

log = logging.getLogger("SmartTeacher.VectorDBManager")


@dataclass
class VectorRecord:
    chunk_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class VectorDBManager:
    """Thin adapter around the existing MultiModalRAG engine and Qdrant store."""

    def __init__(self, rag_system=None, storage_path: Optional[str] = None):
        self.rag_system = rag_system
        self.storage_path = Path(storage_path) if storage_path else Path(Config.RAG_DB_DIR) / "agentic_vector_index.json"
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, VectorRecord] = {}
        self._course_index: Dict[str, List[str]] = {}
        self._load_index()

    def _resolve_rag_system(self):
        if self.rag_system is not None:
            return self.rag_system

        try:
            from services.app_state import knowledge_retrieval_engine

            self.rag_system = knowledge_retrieval_engine
        except Exception:
            self.rag_system = None
        return self.rag_system

    def _load_index(self) -> None:
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, encoding="utf-8") as handle:
                payload = json.load(handle)
            for chunk_id, raw_record in payload.get("records", {}).items():
                self._records[chunk_id] = VectorRecord(
                    chunk_id=chunk_id,
                    text=raw_record.get("text", ""),
                    metadata=raw_record.get("metadata", {}),
                    created_at=raw_record.get("created_at", datetime.utcnow().isoformat()),
                )
            self._course_index = {
                course_id: list(chunk_ids)
                for course_id, chunk_ids in payload.get("course_index", {}).items()
            }
        except Exception as exc:
            log.warning("Vector index could not be loaded: %s", exc)

    def _save_index(self) -> None:
        payload = {
            "records": {chunk_id: asdict(record) for chunk_id, record in self._records.items()},
            "course_index": self._course_index,
            "saved_at": datetime.utcnow().isoformat(),
        }
        try:
            with open(self.storage_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        except Exception as exc:
            log.warning("Vector index could not be saved: %s", exc)

    def _normalize_document(self, document: Any) -> tuple[str, Dict[str, Any]]:
        if Document is not None and isinstance(document, Document):
            return document.page_content, dict(document.metadata or {})

        if isinstance(document, dict):
            text = document.get("content") or document.get("page_content") or document.get("text") or ""
            metadata = dict(document.get("metadata", {})) if isinstance(document.get("metadata", {}), dict) else {}
            for key, value in document.items():
                if key not in {"content", "page_content", "text", "metadata"}:
                    metadata.setdefault(key, value)
            return str(text), metadata

        return str(document), {}

    def _normalize_result(self, item: Any) -> Dict[str, Any]:
        if isinstance(item, tuple) and len(item) >= 3:
            document, score, source = item[:3]
            content = getattr(document, "page_content", str(document))
            metadata = dict(getattr(document, "metadata", {}) or {})
            return {
                "content": content,
                "score": float(score),
                "confidence": float(score),
                "source": source or metadata.get("source") or metadata.get("document_id") or "unknown",
                "metadata": metadata,
                "method": "rag",
            }

        if isinstance(item, dict):
            metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
            content = item.get("content") or item.get("page_content") or item.get("text") or ""
            return {
                "content": content,
                "score": float(item.get("score", item.get("confidence", 0.0)) or 0.0),
                "confidence": float(item.get("confidence", item.get("score", 0.0)) or 0.0),
                "source": item.get("source") or metadata.get("source") or metadata.get("document_id") or "unknown",
                "metadata": metadata,
                "method": item.get("method", "rag"),
            }

        content = getattr(item, "page_content", str(item))
        metadata = dict(getattr(item, "metadata", {}) or {})
        return {
            "content": content,
            "score": float(getattr(item, "score", 0.0) or 0.0),
            "confidence": float(getattr(item, "confidence", getattr(item, "score", 0.0)) or 0.0),
            "source": metadata.get("source") or metadata.get("document_id") or "unknown",
            "metadata": metadata,
            "method": "rag",
        }

    def _matches_filters(self, metadata: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
        if not filters:
            return True

        for key, value in filters.items():
            if value is None:
                continue
            if key in {"course", "course_id"}:
                if metadata.get("course") != value and metadata.get("course_id") != value:
                    return False
                continue
            if metadata.get(key) != value:
                return False
        return True

    def _local_similarity_search(self, query: str, k: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        query_tokens = set(re.findall(r"\w+", query.lower()))
        ranked = []
        for record in self._records.values():
            if not self._matches_filters(record.metadata, filters):
                continue
            text_tokens = set(re.findall(r"\w+", record.text.lower()))
            overlap = len(query_tokens & text_tokens)
            score = overlap / max(len(query_tokens), 1)
            if overlap == 0 and query_tokens:
                continue
            ranked.append(
                {
                    "content": record.text,
                    "score": score,
                    "confidence": score,
                    "source": record.metadata.get("source") or record.metadata.get("document_id") or "unknown",
                    "metadata": dict(record.metadata),
                    "method": "local",
                }
            )

        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:k]

    def get_status(self) -> Dict[str, Any]:
        rag = self._resolve_rag_system()
        if rag and hasattr(rag, "get_status"):
            try:
                return dict(rag.get_status())
            except Exception as exc:
                log.debug("RAG status unavailable: %s", exc)

        return {
            "rag_ready": False,
            "vectorstore_available": False,
            "bm25_available": False,
            "qdrant_connected": False,
            "docs_loaded": len(self._records),
        }

    def get_stats(self) -> Dict[str, Any]:
        rag = self._resolve_rag_system()
        if rag and hasattr(rag, "get_stats"):
            try:
                return dict(rag.get_stats())
            except Exception as exc:
                log.debug("RAG stats unavailable: %s", exc)

        course_count = len(self._course_index)
        return {
            "is_ready": bool(self._records),
            "embeddings_ok": False,
            "total_docs": len(self._records),
            "collection": "agentic_vector_index",
            "by_chapter": {},
            "subjects": {},
            "languages": {},
            "cache_entries": 0,
            "bm25_ready": False,
            "embedding_cache": {},
            "course_count": course_count,
        }

    def search_similar(
        self,
        query: str,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        rag = self._resolve_rag_system()
        course_id = (filters or {}).get("course_id") or (filters or {}).get("course")
        chapter_idx = (filters or {}).get("chapter_idx")
        strict_chapter = bool((filters or {}).get("strict_chapter", False))

        if rag and hasattr(rag, "retrieve_chunks"):
            try:
                raw_results = rag.retrieve_chunks(
                    query,
                    k=k,
                    current_chapter_idx=chapter_idx,
                    strict_chapter=strict_chapter,
                    course_id=course_id,
                )
                normalized = [self._normalize_result(item) for item in raw_results]
                filtered = [item for item in normalized if self._matches_filters(item.get("metadata", {}), filters)]
                if filtered:
                    return filtered[:k]
            except Exception as exc:
                log.warning("Search via RAG engine failed: %s", exc)

        return self._local_similarity_search(query, k, filters)

    def add_documents(
        self,
        documents: Sequence[Any],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[Sequence[str]] = None,
        default_metadata: Optional[Dict[str, Any]] = None,
        course_id: Optional[str] = None,
    ) -> List[str]:
        docs = list(documents)
        if not docs:
            return []

        texts: List[str] = []
        metadata_list: List[Dict[str, Any]] = []
        chunk_ids: List[str] = []
        default_metadata = dict(default_metadata or {})

        for index, document in enumerate(docs):
            text, metadata = self._normalize_document(document)
            if metadatas and index < len(metadatas):
                metadata.update(metadatas[index])
            metadata.update(default_metadata)
            if course_id:
                metadata.setdefault("course", course_id)
                metadata.setdefault("course_id", course_id)
            metadata.setdefault("chunk_index", index)

            chunk_id = ids[index] if ids and index < len(ids) else str(uuid4())
            metadata.setdefault("chunk_id", chunk_id)

            texts.append(text)
            metadata_list.append(metadata)
            chunk_ids.append(chunk_id)

        rag = self._resolve_rag_system()
        stored_ids = list(chunk_ids)
        if rag and getattr(rag, "vectorstore", None) is not None:
            try:
                stored_ids = list(rag.vectorstore.add_texts(texts=texts, metadatas=metadata_list, ids=chunk_ids))
            except Exception as exc:
                log.warning("Vector store add failed, keeping local manifest only: %s", exc)

        if rag is not None:
            try:
                new_documents = [Document(page_content=text, metadata=metadata) for text, metadata in zip(texts, metadata_list)]
                existing_docs = list(getattr(rag, "all_docs", []))
                rag.all_docs = [*existing_docs, *new_documents]
                if hasattr(rag, "_save_docs_cache"):
                    rag._save_docs_cache()
                if hasattr(rag, "_build_hybrid_retriever"):
                    rag._build_hybrid_retriever()
            except Exception as exc:
                log.debug("RAG cache refresh skipped: %s", exc)

        for chunk_id, text, metadata in zip(stored_ids, texts, metadata_list):
            self._records[chunk_id] = VectorRecord(chunk_id=chunk_id, text=text, metadata=metadata)
            course_key = metadata.get("course") or metadata.get("course_id") or "default"
            self._course_index.setdefault(course_key, []).append(chunk_id)

        self._save_index()
        return stored_ids

    def batch_embed_store(
        self,
        documents: Sequence[Any],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[Sequence[str]] = None,
        default_metadata: Optional[Dict[str, Any]] = None,
        course_id: Optional[str] = None,
    ) -> List[str]:
        return self.add_documents(
            documents,
            metadatas=metadatas,
            ids=ids,
            default_metadata=default_metadata,
            course_id=course_id,
        )

    def index_course_data(
        self,
        course_data: Dict[str, Any],
        domain: str = "general",
        course: str = "uploaded",
        course_id: Optional[str] = None,
        incremental: bool = True,
    ) -> bool:
        rag = self._resolve_rag_system()
        if not rag or not hasattr(rag, "run_ingestion_pipeline_from_course_data"):
            log.warning("RAG engine unavailable for course-data ingestion")
            return False

        return bool(
            rag.run_ingestion_pipeline_from_course_data(
                course_data,
                domain=domain,
                course=course,
                course_id=course_id,
                incremental=incremental,
            )
        )

    def index_course_files(
        self,
        file_paths: Sequence[str],
        domain: str = "general",
        course: str = "uploaded",
        course_id: Optional[str] = None,
        incremental: bool = False,
    ) -> bool:
        rag = self._resolve_rag_system()
        if not rag or not hasattr(rag, "run_ingestion_pipeline_for_files"):
            log.warning("RAG engine unavailable for file ingestion")
            return False

        return bool(
            rag.run_ingestion_pipeline_for_files(
                list(file_paths),
                domain=domain,
                course=course,
                course_id=course_id,
                incremental=incremental,
            )
        )

    def get_metadata(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        record = self._records.get(chunk_id)
        return dict(record.metadata) if record else None

    def list_course_documents(self, course_id: str) -> List[Dict[str, Any]]:
        chunk_ids = self._course_index.get(course_id, [])
        return [asdict(self._records[chunk_id]) for chunk_id in chunk_ids if chunk_id in self._records]

    def delete_course(self, course_id: str) -> int:
        rag = self._resolve_rag_system()
        deleted_count = 0

        if rag and getattr(rag, "client", None) is not None and getattr(rag, "collection_name", None):
            try:
                selector = FilterSelector(
                    filter=Filter(
                        must=[FieldCondition(key="metadata.course", match=MatchValue(value=course_id))]
                    )
                )
                rag.client.delete(
                    collection_name=rag.collection_name,
                    points_selector=selector,
                    wait=True,
                )
            except Exception as exc:
                log.warning("Qdrant delete by filter failed: %s", exc)

        if rag is not None and hasattr(rag, "all_docs"):
            try:
                original_docs = list(rag.all_docs)
                filtered_docs = [
                    doc
                    for doc in original_docs
                    if doc.metadata.get("course") != course_id and doc.metadata.get("course_id") != course_id
                ]
                deleted_count += len(original_docs) - len(filtered_docs)
                rag.all_docs = filtered_docs
                if hasattr(rag, "_save_docs_cache"):
                    rag._save_docs_cache()
                if hasattr(rag, "_build_hybrid_retriever"):
                    rag._build_hybrid_retriever()
            except Exception as exc:
                log.debug("RAG cache refresh after delete skipped: %s", exc)

        removed_ids = self._course_index.pop(course_id, [])
        for chunk_id in removed_ids:
            self._records.pop(chunk_id, None)
        deleted_count += len(removed_ids)
        self._save_index()
        return deleted_count

    def clear(self) -> None:
        self._records.clear()
        self._course_index.clear()
        self._save_index()
