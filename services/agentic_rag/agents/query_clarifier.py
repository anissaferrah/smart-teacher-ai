"""
Stage 2: Query Clarifier Agent
Detects ambiguous questions and requests clarification from students.
Adapted from Repo 1 (agentic-rag-for-dummies) clarification pattern.
"""

import logging
import time
from typing import Tuple, Optional
from services.agentic_rag.prompts import CLARIFICATION_PROMPT

log = logging.getLogger("SmartTeacher.QueryClarifier")


class QueryClarifier:
    """
    Stage 2 of the agentic RAG pipeline.
    Detects query ambiguity and asks for clarification when needed.

    Returns:
        (needs_clarification: bool, clarification_question: str)
    """

    def __init__(self, llm):
        """Initialize clarifier with LLM."""
        self.llm = llm
        self.system_prompt = CLARIFICATION_PROMPT

    async def check_clarity(
        self,
        query: str,
        course_context: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Check if query is clear or needs clarification.

        Args:
            query: Student's query
            course_context: Optional course context

        Returns:
            (needs_clarification, clarification_question_or_empty_string)
        """
        start_time = time.time()

        try:
            context = ""
            if course_context:
                context = f"\nCourse context: {course_context}"

            messages = [
                {
                    "role": "system",
                    "content": self.system_prompt
                },
                {
                    "role": "user",
                    "content": f"Analyze this query for clarity:{context}\n\nQuery: {query}"
                }
            ]

            response = await self.llm.agenerate(
                messages,
                temperature=0.2,
                max_tokens=200
            )

            result = response.content.strip()

            # Check if response indicates clarity
            if "CLEAR_TO_PROCEED" in result.upper():
                log.info(f"Query is clear: '{query}'")
                return False, ""

            # Extract clarification question
            needs_clarif = True
            log.info(f"Query needs clarification: '{query}'")

            duration_ms = (time.time() - start_time) * 1000
            log.debug(f"Clarity check completed in {duration_ms:.1f}ms")

            return needs_clarif, result

        except Exception as e:
            log.error(f"Clarity check failed: {e}")
            # On error, assume clear to proceed
            return False, ""

    async def check_clarity_with_trace(
        self,
        query: str,
        course_context: Optional[str] = None
    ) -> dict:
        """
        Check clarity and return detailed trace.

        Returns:
            Dictionary with clarity assessment
        """
        start_time = time.time()
        needs_clarif, clarif_question = await self.check_clarity(query, course_context)
        duration_ms = (time.time() - start_time) * 1000

        return {
            "query": query,
            "needs_clarification": needs_clarif,
            "clarification_question": clarif_question if needs_clarif else None,
            "duration_ms": duration_ms,
            "course_context": course_context
        }
