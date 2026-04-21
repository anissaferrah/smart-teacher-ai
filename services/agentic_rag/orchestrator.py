"""
Agentic RAG Orchestrator - Main controller for multi-stage pipeline.
Based on Repo 2 (LangGraph patterns) + Repo 1 (5-stage workflow).

Pipeline:
1. Query Rewriter   - Improve clarity
2. Query Clarifier  - Check ambiguity
3. Retriever Agent  - Search chunks
4. Reasoner Agent   - Multi-agent thinking
5. Reflection Agent - Validate & refine
"""

import logging
import time
from typing import Optional
from dataclasses import dataclass, field

from config import Config
from services.agentic_rag.agents.query_rewriter import QueryRewriter
from services.agentic_rag.agents.query_clarifier import QueryClarifier
from services.agentic_rag.agents.retriever_agent import RetrieverAgent
from services.agentic_rag.agents.reasoner_agent import ReasonerAgent
from services.agentic_rag.agents.reflection_agent import ReflectionAgent
from services.agentic_rag.memory.short_term import ShortTermMemory
from services.agentic_rag.memory.long_term import LongTermMemory
from services.agentic_rag.retrieval.hybrid_retriever import HybridRetriever

log = logging.getLogger("SmartTeacher.AgenticRAG")


@dataclass
class AgenticRAGState:
    """Pipeline state tracking (Repo 2 pattern)"""
    query: str
    rewritten_query: str = ""
    needs_clarification: bool = False
    clarification_question: str = ""
    retrieved_chunks: list = field(default_factory=list)
    draft_answer: str = ""
    final_answer: str = ""
    confidence: float = 0.0
    reasoning_trace: dict = field(default_factory=dict)
    loop_count: int = 0


class AgenticRAGOrchestrator:
    """
    Orchestrates the 5-stage agentic RAG pipeline.
    Routes between stages and manages state.
    """

    def __init__(self, llm, rag, short_term_memory=None, long_term_memory=None):
        """Initialize orchestrator with services."""
        self.llm = llm
        self.rag = rag
        self.short_term_memory = short_term_memory or ShortTermMemory()
        self.long_term_memory = long_term_memory or LongTermMemory()
        self.max_loops = Config.AGENTIC_MAX_LOOPS

        # Initialize hybrid retriever
        self.hybrid_retriever = HybridRetriever()

        # Initialize agents
        self.query_rewriter = QueryRewriter(llm)
        self.query_clarifier = QueryClarifier(llm)
        self.retriever = RetrieverAgent(rag, self.hybrid_retriever)
        self.reasoner = ReasonerAgent(llm, self.short_term_memory, self.long_term_memory)
        self.reflection = ReflectionAgent(llm)

        log.info("✅ AgenticRAGOrchestrator initialized (max_loops=%d)" % self.max_loops)

    async def answer_question(
        self,
        query: str,
        course_id: Optional[str] = None,
        history: Optional[list] = None,
        language: str = "fr",
        student_profile: Optional[dict] = None,
    ) -> dict:
        """Execute full agentic RAG pipeline."""

        total_start = time.time()
        state = AgenticRAGState(query=query)
        metrics = {}

        try:
            # STAGE 1: Query Rewriting
            log.info("→ Stage 1/5: Query Rewriter")
            stage_start = time.time()
            state.rewritten_query = await self._stage_rewrite(query)
            metrics["rewrite_time"] = time.time() - stage_start
            log.info("  ✅ Rewritten")

            # STAGE 2: Query Clarification
            log.info("→ Stage 2/5: Query Clarifier")
            stage_start = time.time()
            needs_clarif, clarif_q = await self._stage_clarify(state.rewritten_query)
            if needs_clarif:
                log.warning("  ⚠️ Clarification needed")
                return {
                    "answer": "I need clarification: " + clarif_q,
                    "confidence": 0.2,
                    "reasoning": {"needs_clarification": True},
                    "sources": [],
                    "mode": "agentic",
                    "metrics": {"total_time": time.time() - total_start}
                }
            metrics["clarify_time"] = time.time() - stage_start

            # STAGE 3: Retrieval
            log.info("→ Stage 3/5: Retriever Agent")
            stage_start = time.time()
            state.retrieved_chunks = await self._stage_retrieve(state.rewritten_query, course_id)
            metrics["retrieve_time"] = time.time() - stage_start

            # STAGE 4: Reasoning
            log.info("→ Stage 4/5: Reasoner Agent")
            stage_start = time.time()
            state.draft_answer = await self._stage_reason(
                state.rewritten_query, state.retrieved_chunks, history or [], student_profile or {}
            )
            metrics["reason_time"] = time.time() - stage_start

            # STAGE 5: Reflection
            log.info("→ Stage 5/5: Reflection Agent")
            stage_start = time.time()
            state.final_answer, state.confidence, state.loop_count = await self._stage_reflect(
                state.draft_answer, state.retrieved_chunks, state.rewritten_query
            )
            metrics["reflect_time"] = time.time() - stage_start

            total_time = time.time() - total_start
            log.info("✅ Agentic RAG complete (%.2fs)" % total_time)

            return {
                "answer": state.final_answer,
                "confidence": state.confidence,
                "reasoning": {
                    "rewritten_query": state.rewritten_query,
                    "refinement_loops": state.loop_count,
                },
                "sources": [
                    {"text": (c.page_content[:200] if hasattr(c, 'page_content') else str(c)[:200])}
                    for c in state.retrieved_chunks[:3]
                ],
                "mode": "agentic",
                "metrics": {"total_time": total_time, "stages": metrics}
            }

        except Exception as e:
            log.error("❌ Agentic RAG error: %s" % str(e))
            return {
                "answer": "Error: " + str(e),
                "confidence": 0.0,
                "reasoning": {"error": str(e)},
                "sources": [],
                "mode": "agentic",
                "metrics": {"total_time": time.time() - total_start, "error": True}
            }

    async def _stage_rewrite(self, query: str) -> str:
        """Stage 1: Query Rewriter"""
        return await self.query_rewriter.rewrite(query)

    async def _stage_clarify(self, query: str) -> tuple:
        """Stage 2: Query Clarifier"""
        return await self.query_clarifier.check_clarity(query)

    async def _stage_retrieve(self, query: str, course_id: Optional[str]) -> list:
        """Stage 3: Retriever Agent"""
        return await self.retriever.retrieve(query, course_id)

    async def _stage_reason(self, query: str, chunks: list, history: list, profile: dict) -> str:
        """Stage 4: Reasoner Agent"""
        return await self.reasoner.reason(query, chunks, history, profile)

    async def _stage_reflect(self, draft: str, chunks: list, query: str) -> tuple:
        """Stage 5: Reflection Agent"""
        return await self.reflection.reflect_and_refine(draft, chunks, query, self.max_loops)
