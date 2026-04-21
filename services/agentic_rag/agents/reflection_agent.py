"""
Stage 5: Reflection Agent
Self-correction loop with answer quality validation.
Based on Repo 1 (agentic-rag-for-dummies) reflection pattern.
"""

import logging
import time
from typing import Tuple, Optional, List, Dict, Any
from services.agentic_rag.prompts import REFLECTION_SYSTEM_PROMPT
from config import Config

log = logging.getLogger("SmartTeacher.ReflectionAgent")


class ReflectionAgent:
    """
    Stage 5 of the agentic RAG pipeline.
    Validates answer quality and triggers refinement loops if needed.

    Returns:
        (final_answer, confidence_score, refinement_count)
    """

    def __init__(self, llm):
        """Initialize reflection agent."""
        self.llm = llm
        self.system_prompt = REFLECTION_SYSTEM_PROMPT
        self.max_loops = Config.AGENTIC_MAX_LOOPS

    async def reflect_and_refine(
        self,
        draft_answer: str,
        chunks: List[Dict[str, Any]],
        original_query: str,
        max_refinements: int = 3
    ) -> Tuple[str, float, int]:
        """
        Validate answer quality and refine if needed.

        Args:
            draft_answer: Initial answer from reasoner
            chunks: Retrieved source chunks
            original_query: Original student question
            max_refinements: Maximum refinement loops

        Returns:
            (final_answer, confidence_score 0-1, refinement_loops_executed)
        """
        start_time = time.time()
        current_answer = draft_answer
        refinement_count = 0

        try:
            for loop in range(max_refinements):
                # Validate current answer
                confidence, feedback, needs_refinement = await self._validate_answer(
                    current_answer, chunks, original_query
                )

                log.info(f"Reflection loop {loop+1}: confidence={confidence:.2f}, needs_refinement={needs_refinement}")

                if not needs_refinement or confidence >= 0.8:
                    # Answer is good enough
                    log.info(f"Answer accepted with confidence {confidence:.2f}")
                    break

                if loop < max_refinements - 1:
                    # Refine answer
                    current_answer = await self._refine_answer(
                        current_answer, feedback, chunks, original_query
                    )
                    refinement_count += 1
                    log.info(f"Answer refined (attempt {refinement_count+1})")
                else:
                    # Final iteration
                    refinement_count = loop + 1

            duration_ms = (time.time() - start_time) * 1000
            log.debug(f"Reflection completed in {duration_ms:.1f}ms ({refinement_count} refinements)")

            return current_answer, confidence, refinement_count

        except Exception as e:
            log.error(f"Reflection failed: {e}")
            return draft_answer, 0.5, 0

    async def _validate_answer(
        self,
        answer: str,
        chunks: List[Dict[str, Any]],
        query: str
    ) -> Tuple[float, str, bool]:
        """
        Validate answer quality across multiple dimensions.

        Returns:
            (confidence_score, feedback, needs_refinement)
        """
        try:
            chunk_context = "\n".join([chunk.get("content", "")[:200] for chunk in chunks[:3]])

            messages = [
                {
                    "role": "system",
                    "content": self.system_prompt
                },
                {
                    "role": "user",
                    "content": f"""Validate this answer:

Query: {query}

Answer: {answer}

Source Material: {chunk_context}

Score from 0-1 and provide feedback."""
                }
            ]

            response = await self.llm.agenerate(messages, temperature=0.2, max_tokens=200)
            result = response.content.strip()

            # Parse confidence score from response
            confidence = 0.7  # Default
            feedback = result
            needs_refinement = confidence < 0.7

            # Try to extract confidence
            for line in result.split("\n"):
                if "confidence" in line.lower() or "score" in line.lower():
                    try:
                        parts = line.split(":")
                        if len(parts) > 1:
                            score_str = parts[-1].strip().rstrip("%")
                            confidence = float(score_str) / 100 if "%" in line else float(score_str)
                            confidence = max(0.0, min(1.0, confidence))
                    except ValueError:
                        pass

            return confidence, feedback, needs_refinement

        except Exception as e:
            log.warning(f"Validation failed: {e}")
            return 0.6, "", True

    async def _refine_answer(
        self,
        current_answer: str,
        feedback: str,
        chunks: List[Dict[str, Any]],
        query: str
    ) -> str:
        """
        Refine answer based on validation feedback.

        Args:
            current_answer: Current answer
            feedback: Validation feedback
            chunks: Source chunks
            query: Original query

        Returns:
            Refined answer
        """
        try:
            chunk_context = "\n".join([chunk.get("content", "")[:200] for chunk in chunks[:3]])

            messages = [
                {
                    "role": "system",
                    "content": "You are an answer refinement expert. Improve answers based on feedback while staying grounded in source material."
                },
                {
                    "role": "user",
                    "content": f"""Improve this answer based on feedback:

Original Query: {query}

Current Answer: {current_answer}

Feedback: {feedback}

Source Material: {chunk_context}

Provide an improved answer that addresses the feedback."""
                }
            ]

            response = await self.llm.agenerate(messages, temperature=0.7, max_tokens=300)
            refined = response.content.strip()

            return refined if refined else current_answer

        except Exception as e:
            log.error(f"Refinement failed: {e}")
            return current_answer
