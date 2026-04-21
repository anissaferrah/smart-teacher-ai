"""
Agentic RAG - Multi-stage reasoning pipeline
Using Repo 1 (architecture) + Repo 2 (production patterns)
"""

__version__ = "1.0.0"
__author__ = "Smart Teacher Team"

from services.agentic_rag.advanced_prompts import (  # noqa: F401
	AGGREGATION_PROMPT,
	COMPLEX_REASONING_PROMPT,
	FALLBACK_PROMPTS,
	ROLE_PROMPTS,
	build_aggregation_prompt,
	build_reasoning_prompt,
	get_fallback_prompt,
)
from services.agentic_rag.document_chunker import Chunk, HierarchicalDocumentChunker  # noqa: F401
from services.agentic_rag.document_manager import DocumentManager  # noqa: F401
from services.agentic_rag.parent_store_manager import ParentStoreManager  # noqa: F401
from services.agentic_rag.reasoner_agent import ReasonerAgent  # noqa: F401
from services.agentic_rag.vector_db_manager import VectorDBManager  # noqa: F401
  