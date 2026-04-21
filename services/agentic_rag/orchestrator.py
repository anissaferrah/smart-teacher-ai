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
from services.agentic_rag.reasoner_agent import ReasonerAgent
from services.agentic_rag.agents.reflection_agent import ReflectionAgent
from services.agentic_rag.document_manager import DocumentManager
from services.agentic_rag.vector_db_manager import VectorDBManager
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

        # Initialize document and vector helpers around the active RAG engine
        self.vector_db_manager = VectorDBManager(rag_system=rag)
        self.document_manager = DocumentManager(rag_system=rag, vector_db_manager=self.vector_db_manager)

        # Initialize hybrid retriever
        self.hybrid_retriever = HybridRetriever(rag_system=rag)

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
        reasoning_trace: list[dict] = []

        def add_trace_step(
            step: int,
            key: str,
            title: str,
            state_name: str,
            status: str,
            summary: str,
            duration_ms: float,
            confidence: Optional[float] = None,
            details: Optional[dict] = None,
        ) -> None:
            payload = {
                "step": step,
                "key": key,
                "title": title,
                "state": state_name,
                "status": status,
                "summary": summary,
                "duration_ms": round(duration_ms, 1),
            }
            if confidence is not None:
                payload["confidence"] = round(float(confidence), 3)
            if details:
                payload["details"] = details
            reasoning_trace.append(payload)

        try:
            # STAGE 1: Query Rewriting
            log.info("→ Stage 1/5: Query Rewriter")
            stage_start = time.time()
            state.rewritten_query = await self._stage_rewrite(query)
            metrics["rewrite_time"] = time.time() - stage_start
            add_trace_step(
                1,
                "rewrite",
                "Query Rewriter",
                "processing",
                "done",
                state.rewritten_query[:160],
                (time.time() - stage_start) * 1000,
                details={
                    "original_query": query,
                    "rewritten_query": state.rewritten_query,
                },
            )
            log.info("  ✅ Rewritten")

            # STAGE 2: Query Clarification
            log.info("→ Stage 2/5: Query Clarifier")
            stage_start = time.time()
            needs_clarif, clarif_q = await self._stage_clarify(state.rewritten_query)
            add_trace_step(
                2,
                "clarify",
                "Query Clarifier",
                "waiting" if needs_clarif else "processing",
                "needs_clarification" if needs_clarif else "done",
                clarif_q if needs_clarif else "Query claire, poursuite du pipeline",
                (time.time() - stage_start) * 1000,
                confidence=0.2 if needs_clarif else 1.0,
                details={
                    "needs_clarification": needs_clarif,
                },
            )
            if needs_clarif:
                log.warning("  ⚠️ Clarification needed")
                return {
                    "answer": "I need clarification: " + clarif_q,
                    "confidence": 0.2,
                    "reasoning": {
                        "needs_clarification": True,
                        "steps": reasoning_trace,
                        "current_state": "waiting",
                    },
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
            add_trace_step(
                3,
                "retrieve",
                "Retriever Agent",
                "processing",
                "done",
                f"{len(state.retrieved_chunks)} chunks récupérés",
                (time.time() - stage_start) * 1000,
                confidence=state.retrieved_chunks[0].get("score", 0.0) if state.retrieved_chunks else 0.0,
                details={
                    "chunks": len(state.retrieved_chunks),
                    "course_id": course_id,
                },
            )

            # STAGE 4: Reasoning
            log.info("→ Stage 4/5: Reasoner Agent")
            stage_start = time.time()
            state.draft_answer = await self._stage_reason(
                state.rewritten_query, state.retrieved_chunks, history or [], student_profile or {}
            )
            metrics["reason_time"] = time.time() - stage_start
            add_trace_step(
                4,
                "reason",
                "Reasoner Agent",
                "responding",
                "done",
                f"Réponse brouillon générée ({len(state.draft_answer)} caractères)",
                (time.time() - stage_start) * 1000,
                confidence=0.8,
                details={
                    "draft_preview": state.draft_answer[:160],
                },
            )

            # STAGE 5: Reflection
            log.info("→ Stage 5/5: Reflection Agent")
            stage_start = time.time()
            state.final_answer, state.confidence, state.loop_count = await self._stage_reflect(
                state.draft_answer, state.retrieved_chunks, state.rewritten_query
            )
            metrics["reflect_time"] = time.time() - stage_start
            add_trace_step(
                5,
                "reflect",
                "Reflection Agent",
                "idle",
                "done",
                f"Confiance finale {state.confidence:.2f} ({state.loop_count} boucles)",
                (time.time() - stage_start) * 1000,
                confidence=state.confidence,
                details={
                    "refinement_loops": state.loop_count,
                    "final_answer_preview": state.final_answer[:160],
                },
            )

            total_time = time.time() - total_start
            log.info("✅ Agentic RAG complete (%.2fs)" % total_time)

            return {
                "answer": state.final_answer,
                "confidence": state.confidence,
                "reasoning": {
                    "rewritten_query": state.rewritten_query,
                    "refinement_loops": state.loop_count,
                    "steps": reasoning_trace,
                    "current_state": "idle",
                },
                "sources": [
                    {
                        "text": (
                            c.get("content", "")[:200]
                            if isinstance(c, dict)
                            else (c.page_content[:200] if hasattr(c, 'page_content') else str(c)[:200])
                        ),
                        "source": (
                            c.get("source", "") if isinstance(c, dict)
                            else getattr(c, 'metadata', {}).get('source', '')
                        ),
                    }
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
                "reasoning": {
                    "error": str(e),
                    "steps": reasoning_trace,
                    "current_state": "error",
                },
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
