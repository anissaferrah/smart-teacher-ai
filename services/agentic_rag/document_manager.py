"""Document management for agentic RAG course materials."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from config import Config
from services.agentic_rag.document_chunker import Chunk, HierarchicalDocumentChunker
from services.agentic_rag.parent_store_manager import ParentStoreManager
from services.agentic_rag.vector_db_manager import VectorDBManager

try:
    from langchain_core.documents import Document
except Exception:  # pragma: no cover
    Document = None

log = logging.getLogger("SmartTeacher.DocumentManager")


class DocumentManager:
    """Manage document uploads, chunking, indexing, and deletion."""

    def __init__(
        self,
        rag_system=None,
        vector_db_manager: Optional[VectorDBManager] = None,
        parent_store_manager: Optional[ParentStoreManager] = None,
        chunker: Optional[HierarchicalDocumentChunker] = None,
        storage_path: Optional[str] = None,
    ):
        self.rag_system = rag_system
        self.vector_db_manager = vector_db_manager or VectorDBManager(rag_system)
        self.parent_store = parent_store_manager or ParentStoreManager(
            storage_path=storage_path or str(Path(Config.RAG_DB_DIR) / "agentic_parent_store.json")
        )
        self.chunker = chunker or HierarchicalDocumentChunker()
        self.storage_path = Path(storage_path) if storage_path else Path(Config.RAG_DB_DIR) / "agentic_documents.json"
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.course_documents: Dict[str, List[str]] = {}
        self._load_manifest()

    def _load_manifest(self) -> None:
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, encoding="utf-8") as handle:
                payload = json.load(handle)
            self.course_documents = {
                course_id: list(document_ids)
                for course_id, document_ids in payload.get("course_documents", {}).items()
            }
        except Exception as exc:
            log.warning("Document manifest could not be loaded: %s", exc)

    def _save_manifest(self) -> None:
        payload = {
            "course_documents": self.course_documents,
            "saved_at": datetime.utcnow().isoformat(),
        }
        try:
            with open(self.storage_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        except Exception as exc:
            log.warning("Document manifest could not be saved: %s", exc)

    def _extract_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            try:
                from unstructured.partition.auto import partition

                elements = partition(filename=str(file_path))
                text_parts = []
                for element in elements:
                    text = getattr(element, "text", None) or str(element)
                    text = str(text).strip()
                    if text:
                        text_parts.append(text)
                return "\n\n".join(text_parts)
            except Exception as exc:
                log.debug("PDF partition fallback used for %s: %s", file_path, exc)

        try:
            return file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def index_document_text(
        self,
        text: str,
        document_id: str,
        course_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = dict(metadata or {})
        metadata.setdefault("document_id", document_id)
        metadata.setdefault("course", course_id)
        metadata.setdefault("course_id", course_id)
        metadata.setdefault("source", document_id)

        chunks = self.chunker.chunk_document(text, document_id=document_id, metadata=metadata)
        if not chunks:
            return {"ok": False, "error": "No chunks produced", "document_id": document_id}

        documents: List[Any] = []
        chunk_ids: List[str] = []
        parent_count = 0
        child_count = 0

        for chunk in chunks:
            chunk_metadata = dict(chunk.metadata)
            chunk_metadata.setdefault("chunk_id", chunk.id)
            chunk_metadata.setdefault("chunk_type", chunk.chunk_type)
            chunk_metadata.setdefault("chunk_level", chunk.level)
            chunk_metadata.setdefault("parent_id", chunk.parent_id)
            chunk_metadata.setdefault("course", course_id)
            chunk_metadata.setdefault("course_id", course_id)
            chunk_metadata.setdefault("document_id", document_id)
            if Document is not None:
                documents.append(Document(page_content=chunk.content, metadata=chunk_metadata))
            else:
                documents.append({"content": chunk.content, "metadata": chunk_metadata})
            chunk_ids.append(chunk.id)

            if chunk.chunk_type == "parent":
                parent_count += 1
            else:
                child_count += 1

        self.vector_db_manager.add_documents(
            documents,
            ids=chunk_ids,
            default_metadata={"course": course_id, "course_id": course_id, "document_id": document_id},
            course_id=course_id,
        )

        for parent_chunk in [chunk for chunk in chunks if chunk.chunk_type == "parent"]:
            child_ids = [chunk.id for chunk in chunks if chunk.parent_id == parent_chunk.id]
            self.parent_store.add_parent_chunk(
                parent_chunk.id,
                parent_chunk.content,
                metadata=dict(parent_chunk.metadata),
                children_ids=child_ids,
            )
            for child_id in child_ids:
                self.parent_store.add_child_chunk(parent_chunk.id, child_id)

        if course_id not in self.course_documents:
            self.course_documents[course_id] = []
        if document_id not in self.course_documents[course_id]:
            self.course_documents[course_id].append(document_id)
        self._save_manifest()
        self.parent_store.save_to_disk()

        return {
            "ok": True,
            "document_id": document_id,
            "course_id": course_id,
            "chunk_count": len(chunks),
            "parent_count": parent_count,
            "child_count": child_count,
            "chunk_ids": chunk_ids,
        }

    def index_document_file(
        self,
        file_path: str,
        course_id: str,
        document_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        path = Path(file_path)
        document_id = document_id or path.stem
        text = self._extract_text(path)
        if not text.strip():
            return {"ok": False, "error": f"No text extracted from {file_path}", "document_id": document_id}

        full_metadata = dict(metadata or {})
        full_metadata.setdefault("source_file", str(path.resolve()))
        full_metadata.setdefault("file_name", path.name)
        return self.index_document_text(text=text, document_id=document_id, course_id=course_id, metadata=full_metadata)

    def upload_course_material(
        self,
        file_path: str,
        course_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.index_document_file(file_path=file_path, course_id=course_id, metadata=metadata)

    def index_course_data(
        self,
        course_data: Dict[str, Any],
        domain: str = "general",
        course: str = "uploaded",
        course_id: Optional[str] = None,
        incremental: bool = True,
    ) -> bool:
        return self.vector_db_manager.index_course_data(
            course_data,
            domain=domain,
            course=course,
            course_id=course_id,
            incremental=incremental,
        )

    def index_course_files(
        self,
        file_paths: Sequence[str],
        domain: str = "general",
        course: str = "uploaded",
        course_id: Optional[str] = None,
        incremental: bool = False,
    ) -> bool:
        return self.vector_db_manager.index_course_files(
            file_paths,
            domain=domain,
            course=course,
            course_id=course_id,
            incremental=incremental,
        )

    def get_course_documents(self, course_id: str) -> List[Dict[str, Any]]:
        return self.vector_db_manager.list_course_documents(course_id)

    def delete_course_material(self, course_id: str) -> Dict[str, Any]:
        document_ids = list(self.course_documents.get(course_id, []))
        parent_deleted = 0
        for document_id in document_ids:
            parent_deleted += self.parent_store.delete_document(document_id)

        vector_deleted = self.vector_db_manager.delete_course(course_id)
        self.course_documents.pop(course_id, None)
        self._save_manifest()

        return {
            "ok": True,
            "course_id": course_id,
            "documents_removed": len(document_ids),
            "parent_chunks_removed": parent_deleted,
            "vector_records_removed": vector_deleted,
        }
