"""
Hierarchical document chunking for smart PDF parsing and context preservation.
Creates parent-child chunk relationships for better retrieval context.
"""

import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

log = logging.getLogger("SmartTeacher.DocumentChunker")


@dataclass
class Chunk:
    """Represents a document chunk with hierarchy information."""
    id: str
    content: str
    chunk_type: str  # "parent" | "child" | "leaf"
    parent_id: Optional[str] = None
    level: int = 0  # 0=parent, 1=child, 2=leaf
    start_char: int = 0
    end_char: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        """Approximate token count (words / 0.75)"""
        return max(1, int(len(self.content.split()) / 0.75))


class HierarchicalDocumentChunker:
    """
    Intelligent document chunker that preserves hierarchy and context.
    Supports PDF sections, subsections, and smart sentence boundaries.
    """

    # Configurable chunk sizes
    PARENT_CHUNK_TOKENS = 1000      # ~4 KB
    CHILD_CHUNK_TOKENS = 300        # ~1 KB
    OVERLAP_TOKENS = 50             # ~200 chars

    # Section detection patterns
    SECTION_PATTERNS = [
        (r'^#+\s+(.+)$', 'markdown'),
        (r'^(Chapter|Section|Unit|Part|Module)\s+\d+[.:]?\s+(.+)$', 'chapter'),
        (r'^([\d\.]+)\s+([A-Z][^\n]{10,})$', 'numbered'),
    ]

    def __init__(
        self,
        parent_tokens: int = PARENT_CHUNK_TOKENS,
        child_tokens: int = CHILD_CHUNK_TOKENS,
        overlap_tokens: int = OVERLAP_TOKENS
    ):
        self.parent_tokens = parent_tokens
        self.child_tokens = child_tokens
        self.overlap_tokens = overlap_tokens
        self._chunk_counter = 0

    def create_parent_child_chunks(
        self,
        text: str,
        document_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Chunk]:
        """Compatibility helper that mirrors chunk_document."""
        return self.chunk_document(text, document_id, metadata)

    def preserve_metadata(self, chunk: Chunk, source_metadata: Optional[Dict[str, Any]] = None) -> Chunk:
        """Merge source metadata into an existing chunk."""
        merged_metadata = dict(source_metadata or {})
        merged_metadata.update(chunk.metadata)
        chunk.metadata = merged_metadata
        return chunk

    def parse_pdf(self, file_path: str) -> str:
        """Extract text from a PDF file, with a text fallback."""
        path = Path(file_path)
        if path.suffix.lower() != ".pdf":
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""

        try:
            from unstructured.partition.auto import partition
        except Exception as exc:
            log.warning("PDF partition unavailable for %s: %s", file_path, exc)
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""

        try:
            elements = partition(filename=str(path))
            text_parts = []
            for element in elements:
                text = getattr(element, "text", None) or str(element)
                text = str(text).strip()
                if text:
                    text_parts.append(text)
            return "\n\n".join(text_parts)
        except Exception as exc:
            log.warning("PDF extraction failed for %s: %s", file_path, exc)
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""

    def chunk_document(
        self,
        text: str,
        document_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[Chunk]:
        """
        Chunk a document hierarchically.

        Returns:
            List of Chunk objects with parent-child relationships
        """
        if not text or not text.strip():
            log.warning(f"Empty document: {document_id}")
            return []

        metadata = metadata or {}
        self._chunk_counter = 0

        # Step 1: Detect sections and hierarchical structure
        sections = self._detect_sections(text)

        # Step 2: Create parent chunks (sections)
        parent_chunks = self._create_parent_chunks(sections, text, document_id, metadata)

        # Step 3: Create child chunks (subsections within parents)
        all_chunks = []
        for parent in parent_chunks:
            all_chunks.append(parent)
            child_chunks = self._create_child_chunks(parent, document_id, metadata)
            all_chunks.extend(child_chunks)

        log.info(f"Chunked {document_id}: {len(parent_chunks)} parents, {len(all_chunks) - len(parent_chunks)} children")
        return all_chunks

    def _detect_sections(self, text: str) -> List[Tuple[str, int, int, str]]:
        """
        Detect document sections/headers.

        Returns:
            List of (section_title, start_pos, end_pos, section_type)
        """
        sections = []
        lines = text.split('\n')
        current_pos = 0

        for i, line in enumerate(lines):
            # Try each section pattern
            for pattern, section_type in self.SECTION_PATTERNS:
                match = re.match(pattern, line.strip(), re.MULTILINE)
                if match:
                    title = match.group(match.lastindex or 0)
                    sections.append((title.strip(), current_pos, current_pos, section_type))
                    break

            current_pos += len(line) + 1  # +1 for newline

        # Update end positions
        for i in range(len(sections) - 1):
            sections[i] = (sections[i][0], sections[i][1], sections[i+1][1], sections[i][3])

        if sections:
            sections[-1] = (sections[-1][0], sections[-1][1], current_pos, sections[-1][3])

        return sections if sections else [("Document", 0, current_pos, "document")]

    def _create_parent_chunks(
        self,
        sections: List[Tuple[str, int, int, str]],
        document_text: str,
        document_id: str,
        base_metadata: Dict[str, Any]
    ) -> List[Chunk]:
        """Create top-level (parent) chunks from sections."""
        chunks = []

        for section_title, start_pos, end_pos, section_type in sections:
            chunk_id = f"{document_id}#parent_{self._chunk_counter}"
            self._chunk_counter += 1
            section_text = document_text[start_pos:end_pos].strip()
            if not section_text:
                section_text = section_title

            chunk = Chunk(
                id=chunk_id,
                content=section_text,
                chunk_type="parent",
                level=0,
                start_char=start_pos,
                end_char=end_pos,
                metadata={
                    **base_metadata,
                    "document_id": document_id,
                    "section_type": section_type,
                    "section_title": section_title,
                }
            )
            chunks.append(chunk)

        return chunks

    def _create_child_chunks(
        self,
        parent_chunk: Chunk,
        document_id: str,
        base_metadata: Dict[str, Any]
    ) -> List[Chunk]:
        """Create sub-level (child) chunks within a parent section."""
        chunks = []

        child_texts = self.chunk_by_tokens(parent_chunk.content, self.child_tokens, self.overlap_tokens)
        if not child_texts:
            child_texts = [parent_chunk.content]

        cursor = 0
        for child_index, child_text in enumerate(child_texts):
            normalized_text = child_text.strip()
            if not normalized_text:
                continue

            start = parent_chunk.content.find(normalized_text, cursor)
            if start < 0:
                start = cursor
            end = start + len(normalized_text)
            cursor = end

            chunk_id = f"{document_id}#child_{self._chunk_counter}"
            self._chunk_counter += 1

            child_chunk = Chunk(
                id=chunk_id,
                content=normalized_text,
                chunk_type="child",
                parent_id=parent_chunk.id,
                level=1,
                start_char=parent_chunk.start_char + start,
                end_char=parent_chunk.start_char + end,
                metadata={
                    **base_metadata,
                    "document_id": document_id,
                    "parent_id": parent_chunk.id,
                    "parent_title": parent_chunk.metadata.get("section_title", ""),
                    "chunk_index": child_index,
                }
            )
            chunks.append(child_chunk)

        return chunks

    def chunk_by_tokens(self, text: str, max_tokens: int, overlap_tokens: int = 0) -> List[str]:
        """
        Chunk text by approximate token count with optional overlap.

        Args:
            text: Text to chunk
            max_tokens: Maximum tokens per chunk
            overlap_tokens: Tokens to overlap between chunks

        Returns:
            List of text chunks
        """
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = max(1, int(len(sentence.split()) / 0.75))

            if current_tokens + sentence_tokens > max_tokens and current_chunk:
                # Start new chunk
                chunk_text = ' '.join(current_chunk)
                chunks.append(chunk_text)

                # Add overlap to next chunk
                if overlap_tokens > 0 and current_chunk:
                    overlap_text = ' '.join(current_chunk[-1:])
                    current_chunk = [overlap_text, sentence]
                    current_tokens = len(overlap_text.split()) + sentence_tokens
                else:
                    current_chunk = [sentence]
                    current_tokens = sentence_tokens
            else:
                current_chunk.append(sentence)
                current_tokens += sentence_tokens

        if current_chunk:
            chunks.append(' '.join(current_chunk))

        return chunks

    def merge_chunks(self, chunks: List[Chunk], max_size_tokens: int = 500) -> List[Chunk]:
        """
        Merge small adjacent chunks to avoid fragmentation.

        Args:
            chunks: List of chunks to merge
            max_size_tokens: Target size for merging

        Returns:
            Merged chunk list
        """
        if not chunks:
            return []

        merged = []
        current = chunks[0]

        for next_chunk in chunks[1:]:
            combined_tokens = current.token_count + next_chunk.token_count

            if combined_tokens <= max_size_tokens and current.chunk_type == next_chunk.chunk_type:
                # Merge
                current = Chunk(
                    id=current.id,
                    content=f"{current.content}\n\n{next_chunk.content}",
                    chunk_type=current.chunk_type,
                    parent_id=current.parent_id or next_chunk.parent_id,
                    level=current.level,
                    start_char=current.start_char,
                    end_char=next_chunk.end_char,
                    metadata={**current.metadata, **next_chunk.metadata}
                )
            else:
                # Flush current and start new
                merged.append(current)
                current = next_chunk

        merged.append(current)
        return merged
