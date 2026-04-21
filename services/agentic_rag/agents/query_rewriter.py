"""
Stage 1: Query Rewriter Agent
Improves query clarity and specificity for better retrieval and understanding.
Adapted from Repo 1 (agentic-rag-for-dummies) query rewriting pattern.
"""

import logging
import time
from typing import Optional
from services.agentic_rag.prompts import REWRITE_PROMPT
from config import Config

log = logging.getLogger("SmartTeacher.QueryRewriter")


class QueryRewriter:
    """
    Stage 1 of the agentic RAG pipeline.
    Transforms vague student queries into clear, specific questions.

    Example:
        Input: "What is photo?"
        Output: "Explain the process of photosynthesis in plants and its role in energy conversion"
    """

    def __init__(self, llm):
        """
        Initialize the rewriter with an LLM.

        Args:
            llm: Language model instance (e.g., OpenAI GPT-4)
        """
        self.llm = llm
        self.system_prompt = REWRITE_PROMPT

    async def rewrite(self, query: str, course_context: Optional[str] = None) -> str:
        """
        Rewrite a student query for improved clarity.

        Args:
            query: Original student query
            course_context: Optional course/topic context

        Returns:
            Rewritten query or original if no improvement needed
        """
        start_time = time.time()

        try:
            # Build context for the rewriter
            context = ""
            if course_context:
                context = f"\nCourse context: {course_context}"

            # Create messages for LLM
            messages = [
                {
                    "role": "system",
                    "content": self.system_prompt
                },
                {
                    "role": "user",
                    "content": f"Please rewrite this student query for clarity:\n\nQuery: {query}{context}"
                }
            ]

            # Call LLM
            response = await self.llm.agenerate(
                messages,
                temperature=0.3,  # Lower temperature for consistency
                max_tokens=150
            )

            rewritten = response.content.strip()

            # Validate: if rewritten query is significantly shorter or empty, use original
            if len(rewritten) < 10 or not rewritten:
                rewritten = query
                log.info(f"Rewrite validation: kept original query (rewrite too short)")
            else:
                log.info(f"Query rewritten: '{query}' → '{rewritten}'")

            duration_ms = (time.time() - start_time) * 1000
            log.debug(f"Query rewrite completed in {duration_ms:.1f}ms")

            return rewritten

        except Exception as e:
            log.error(f"Query rewrite failed: {e}")
            log.warning(f"Falling back to original query: '{query}'")
            return query

    async def rewrite_with_trace(self, query: str, course_context: Optional[str] = None) -> dict:
        """
        Rewrite query and return detailed trace.

        Args:
            query: Original query
            course_context: Optional context

        Returns:
            Dictionary with rewritten query and metadata
        """
        start_time = time.time()
        rewritten = await self.rewrite(query, course_context)
        duration_ms = (time.time() - start_time) * 1000

        return {
            "original_query": query,
            "rewritten_query": rewritten,
            "was_modified": query != rewritten,
            "duration_ms": duration_ms,
            "course_context": course_context
        }
