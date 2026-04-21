"""
Parent Store Manager for managing parent-child chunk relationships.
Enables efficient context retrieval with full hierarchical context.
"""

import logging
import json
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime

log = logging.getLogger("SmartTeacher.ParentStoreManager")


class ParentStoreManager:
    """
    Manages hierarchical chunk relationships for efficient retrieval.
    Stores parent-child mappings and enables context expansion.
    """

    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize parent store.

        Args:
            storage_path: Optional path for persistent storage (JSON file)
        """
        self.storage_path = storage_path
        # In-memory storage: parent_id -> {children: [chunk_ids], metadata: {...}}
        self.parent_index: Dict[str, Dict] = {}
        # In-memory storage: chunk_id -> parent_id
        self.child_to_parent: Dict[str, str] = {}
        # Document index: document_id -> [chunk_ids]
        self.document_chunks: Dict[str, List[str]] = {}

        if storage_path:
            self._load_from_disk()

    def add_parent_chunk(
        self,
        parent_id: str,
        content: str,
        metadata: Optional[Dict] = None,
        children_ids: Optional[List[str]] = None
    ) -> None:
        """
        Add a parent chunk and register its children.

        Args:
            parent_id: Unique identifier for parent chunk
            content: Parent chunk content
            metadata: Parent chunk metadata (section_title, document_id, etc.)
            children_ids: List of child chunk IDs that belong to this parent
        """
        self.parent_index[parent_id] = {
            "content": content,
            "metadata": metadata or {},
            "children": children_ids or [],
            "created_at": datetime.utcnow().isoformat(),
            "access_count": 0
        }

        # Register children -> parent mapping
        for child_id in (children_ids or []):
            self.child_to_parent[child_id] = parent_id

        # Register in document index
        if metadata and "document_id" in metadata:
            doc_id = metadata["document_id"]
            if doc_id not in self.document_chunks:
                self.document_chunks[doc_id] = []
            self.document_chunks[doc_id].append(parent_id)

        log.debug(f"Added parent chunk: {parent_id} with {len(children_ids or [])} children")

    def add_child_chunk(
        self,
        parent_id: str,
        child_id: str,
        content: Optional[str] = None
    ) -> bool:
        """
        Register a child chunk under a parent.

        Args:
            parent_id: Parent chunk ID
            child_id: Child chunk ID to register
            content: Optional child content for verification

        Returns:
            True if successful, False if parent not found
        """
        if parent_id not in self.parent_index:
            log.warning(f"Parent {parent_id} not found")
            return False

        if child_id not in self.parent_index[parent_id]["children"]:
            self.parent_index[parent_id]["children"].append(child_id)

        self.child_to_parent[child_id] = parent_id
        log.debug(f"Registered child {child_id} under parent {parent_id}")
        return True

    def get_parent(self, parent_id: str) -> Optional[Dict]:
        """Retrieve parent chunk and metadata."""
        parent = self.parent_index.get(parent_id)
        if parent:
            parent["access_count"] += 1
        return parent

    def get_children(self, parent_id: str) -> List[str]:
        """Get all child chunk IDs for a parent."""
        if parent_id not in self.parent_index:
            return []
        return self.parent_index[parent_id].get("children", [])

    def get_parent_of_child(self, child_id: str) -> Optional[str]:
        """Get parent ID for a child chunk."""
        return self.child_to_parent.get(child_id)

    def expand_context(
        self,
        chunk_id: str,
        include_siblings: bool = True,
        max_chars: int = 5000
    ) -> str:
        """
        Expand a chunk with its parent and siblings for better context.

        Args:
            chunk_id: Chunk to expand
            include_siblings: Whether to include sibling chunks
            max_chars: Maximum characters to return

        Returns:
            Expanded context string
        """
        parts = []

        # Get parent
        parent_id = self.child_to_parent.get(chunk_id)
        if parent_id:
            parent = self.parent_index.get(parent_id)
            if parent:
                parts.append(f"[SECTION] {parent['metadata'].get('section_title', '')}")
                parts.append(parent.get("content", ""))

        # Include siblings
        if include_siblings and parent_id:
            siblings = self.parent_index[parent_id].get("children", [])
            for sibling_id in siblings:
                if sibling_id != chunk_id:
                    parts.append(f"[RELATED] {sibling_id}")

        context = "\n\n".join(parts)
        return context[:max_chars]

    def get_document_hierarchy(self, document_id: str) -> Dict[str, List[str]]:
        """
        Get complete hierarchy for a document.

        Returns:
            Dict of parent_id -> [child_ids]
        """
        chunk_ids = self.document_chunks.get(document_id, [])
        hierarchy = {}

        for parent_id in chunk_ids:
            if parent_id in self.parent_index:
                hierarchy[parent_id] = self.parent_index[parent_id].get("children", [])

        return hierarchy

    def search_by_section(self, section_title: str) -> List[str]:
        """Find all chunks in a section by title."""
        results = []
        for parent_id, data in self.parent_index.items():
            if section_title.lower() in data.get("metadata", {}).get("section_title", "").lower():
                results.append(parent_id)
        return results

    def search_by_metadata(self, **filters) -> List[str]:
        """
        Search chunks by metadata filters.

        Example:
            search_by_metadata(document_id="doc123", section_type="chapter")
        """
        results = []
        for parent_id, data in self.parent_index.items():
            metadata = data.get("metadata", {})
            if all(metadata.get(k) == v for k, v in filters.items()):
                results.append(parent_id)
        return results

    def get_statistics(self) -> Dict:
        """Get store statistics for monitoring."""
        total_parents = len(self.parent_index)
        total_children = len(self.child_to_parent)
        total_documents = len(self.document_chunks)

        most_accessed = sorted(
            self.parent_index.items(),
            key=lambda x: x[1].get("access_count", 0),
            reverse=True
        )[:5]

        return {
            "total_parents": total_parents,
            "total_children": total_children,
            "total_documents": total_documents,
            "avg_children_per_parent": total_children / max(1, total_parents),
            "most_accessed": [
                (pid, data.get("access_count", 0))
                for pid, data in most_accessed
            ]
        }

    def delete_document(self, document_id: str) -> int:
        """
        Remove all chunks related to a document.

        Returns:
            Number of chunks deleted
        """
        chunk_ids = self.document_chunks.get(document_id, [])
        deleted_count = 0

        for parent_id in chunk_ids:
            if parent_id in self.parent_index:
                children = self.parent_index[parent_id].get("children", [])
                for child_id in children:
                    if child_id in self.child_to_parent:
                        del self.child_to_parent[child_id]
                        deleted_count += 1

                del self.parent_index[parent_id]
                deleted_count += 1

        if document_id in self.document_chunks:
            del self.document_chunks[document_id]

        log.info(f"Deleted {deleted_count} chunks for document {document_id}")
        return deleted_count

    def save_to_disk(self) -> None:
        """Persist store to JSON file."""
        if not self.storage_path:
            log.warning("No storage path configured for persistence")
            return

        data = {
            "parent_index": self.parent_index,
            "child_to_parent": self.child_to_parent,
            "document_chunks": self.document_chunks,
            "saved_at": datetime.utcnow().isoformat()
        }

        try:
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            log.info(f"Parent store saved to {self.storage_path}")
        except Exception as e:
            log.error(f"Failed to save parent store: {e}")

    def _load_from_disk(self) -> None:
        """Load store from JSON file."""
        if not self.storage_path:
            return

        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
                self.parent_index = data.get("parent_index", {})
                self.child_to_parent = data.get("child_to_parent", {})
                self.document_chunks = data.get("document_chunks", {})
            log.info(f"Parent store loaded from {self.storage_path}")
        except FileNotFoundError:
            log.debug(f"No existing parent store at {self.storage_path}")
        except Exception as e:
            log.error(f"Failed to load parent store: {e}")

    def clear(self) -> None:
        """Clear all data."""
        self.parent_index.clear()
        self.child_to_parent.clear()
        self.document_chunks.clear()
        log.info("Parent store cleared")
