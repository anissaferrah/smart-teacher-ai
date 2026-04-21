"""LangGraph workflow orchestration for Agentic RAG."""

import logging
from typing import Literal, Optional

from infrastructure.logging import get_logger
from services.agentic_rag.graph.state import AgenticRAGState
from services.agentic_rag.agents.query_rewriter import query_rewriter_node
from services.agentic_rag.agents.query_clarifier import query_clarifier_node
from services.agentic_rag.agents.retriever_agent import retriever_agent_node
from services.agentic_rag.agents.reasoning_agent import reasoning_agent_node
from services.agentic_rag.agents.reflection_agent import reflection_agent_node

log = get_logger(__name__)

# Try to import LangGraph - graceful fallback if not installed
try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import Command
    LANGGRAPH_AVAILABLE = True
except ImportError:
    log.warning("⚠️  LangGraph not installed - using simplified workflow")
    LANGGRAPH_AVAILABLE = False


class SimpleAgenticRAGExecutor:
    """Simplified Agentic RAG executor without LangGraph dependency."""
    
    def __init__(self, llm, rag, confusion_detector):
        """Initialize executor.
        
        Args:
            llm: Language model instance
            rag: RAG retrieval engine
            confusion_detector: Unified confusion detector
        """
        self.llm = llm
        self.rag = rag
        self.confusion_detector = confusion_detector
    
    async def invoke(self, input_dict: dict) -> dict:
        """Execute the agentic RAG pipeline sequentially.
        
        Args:
            input_dict: Dict with query, course_id, student_profile, history
            
        Returns:
            Dict with final_answer and metadata
        """
        log.info(f"🚀 Starting Agentic RAG pipeline for: '{input_dict.get('query', '')}'")
        
        # Initialize state
        state = AgenticRAGState(
            query=input_dict.get("query", ""),
            course_id=input_dict.get("course_id"),
            student_profile=input_dict.get("student_profile"),
            history=input_dict.get("history", []),
        )
        
        try:
            # Step 1: Query Rewriting
            log.info("→ Step 1/5: Query Rewriter")
            rewrite_result = await query_rewriter_node(state, self.llm)
            state.rewritten_query = rewrite_result.get("rewritten_query")
            state.query_intent = rewrite_result.get("query_intent")
            state.agent_metadata.update(rewrite_result.get("agent_metadata", {}))
            
            # Step 2: Query Clarification
            log.info("→ Step 2/5: Query Clarifier")
            clarify_result = await query_clarifier_node(state, self.llm)
            state.needs_clarification = clarify_result.get("needs_clarification", False)
            state.clarification_question = clarify_result.get("clarification_question")
            state.agent_metadata.update(clarify_result.get("agent_metadata", {}))
            
            # If needs clarification, ask user (in real system, would prompt UI)
            if state.needs_clarification:
                log.warning(f"⚠️  Clarification needed: {state.clarification_question}")
                state.final_answer = f"I need clarification: {state.clarification_question}"
                state.final_confidence = 0.3
                return state.to_dict()
            
            # Step 3: Retrieval
            log.info("→ Step 3/5: Retriever Agent")
            retrieve_result = await retriever_agent_node(state, self.rag)
            state.retrieved_chunks = retrieve_result.get("retrieved_chunks", [])
            state.retrieval_confidence = retrieve_result.get("retrieval_confidence", 0.0)
            state.retrieval_strategy = retrieve_result.get("retrieval_strategy", "")
            state.agent_metadata.update(retrieve_result.get("agent_metadata", {}))
            
            # Step 4: Reasoning
            log.info("→ Step 4/5: Reasoning Agent")
            reasoning_result = await reasoning_agent_node(state, self.llm)
            state.draft_answer = reasoning_result.get("draft_answer")
            state.reasoning_confidence = reasoning_result.get("reasoning_confidence", 0.0)
            state.agent_metadata.update(reasoning_result.get("agent_metadata", {}))
            
            # Step 5: Reflection + Optional Refinement Loop
            log.info("→ Step 5/5: Reflection Agent")
            state.loop_count = 0
            while state.loop_count < state.max_loops:
                reflection_result = await reflection_agent_node(state, self.llm)
                state.is_valid = reflection_result.get("is_valid", False)
                state.reflection_score = reflection_result.get("reflection_score", 0.0)
                state.needs_refinement = reflection_result.get("needs_refinement", False)
                state.refinement_suggestions = reflection_result.get("refinement_suggestions", [])
                state.agent_metadata.update(reflection_result.get("agent_metadata", {}))
                
                # If not valid, try reasoning again
                if not state.is_valid and state.loop_count < state.max_loops - 1:
                    log.warning(f"↻ Refinement loop {state.loop_count + 1} - re-reasoning")
                    state.loop_count += 1
                    reasoning_result = await reasoning_agent_node(state, self.llm)
                    state.draft_answer = reasoning_result.get("draft_answer")
                else:
                    break
            
            # Set final answer
            state.final_answer = state.draft_answer or "Unable to generate answer"
            state.final_confidence = state.reflection_score
            
            log.info(f"✅ Pipeline complete (confidence: {state.final_confidence:.2f})")
            
        except Exception as e:
            log.error(f"❌ Pipeline failed: {e}")
            state.final_answer = f"Error: {str(e)}"
            state.final_confidence = 0.0
        
        return state.to_dict()


class LangGraphAgenticRAGExecutor:
    """Full LangGraph-based Agentic RAG executor."""
    
    def __init__(self, llm, rag, confusion_detector):
        """Initialize executor."""
        self.llm = llm
        self.rag = rag
        self.confusion_detector = confusion_detector
        self.graph = self._create_graph()
    
    def _create_graph(self):
        """Create LangGraph workflow."""
        if not LANGGRAPH_AVAILABLE:
            raise ImportError("LangGraph not available")
        
        graph = StateGraph(AgenticRAGState)
        
        # Add nodes
        graph.add_node(
            "query_rewriter",
            lambda state: query_rewriter_node(state, self.llm),
        )
        graph.add_node(
            "query_clarifier",
            lambda state: query_clarifier_node(state, self.llm),
        )
        graph.add_node(
            "retriever",
            lambda state: retriever_agent_node(state, self.rag),
        )
        graph.add_node(
            "reasoning",
            lambda state: reasoning_agent_node(state, self.llm),
        )
        graph.add_node(
            "reflection",
            lambda state: reflection_agent_node(state, self.llm),
        )
        
        # Add edges
        graph.add_edge(START, "query_rewriter")
        graph.add_edge("query_rewriter", "query_clarifier")
        
        # Conditional: if clarification needed, ask user (exit)
        # Otherwise continue to retriever
        def clarification_router(state):
            if state.needs_clarification:
                return "END_CLARIFICATION"
            return "retriever"
        
        graph.add_conditional_edges("query_clarifier", clarification_router)
        graph.add_edge("retriever", "reasoning")
        graph.add_edge("reasoning", "reflection")
        
        # Conditional: if needs refinement and loop count < max, go back to reasoning
        def refinement_router(state):
            if state.needs_refinement and state.loop_count < state.max_loops:
                state.loop_count += 1
                return "reasoning"
            return END
        
        graph.add_conditional_edges("reflection", refinement_router)
        
        return graph.compile()
    
    async def invoke(self, input_dict: dict) -> dict:
        """Execute the agentic RAG pipeline."""
        state = AgenticRAGState(
            query=input_dict.get("query", ""),
            course_id=input_dict.get("course_id"),
            student_profile=input_dict.get("student_profile"),
            history=input_dict.get("history", []),
        )
        
        result = self.graph.invoke(state)
        return result.to_dict()


def create_agentic_rag_executor(llm, rag, confusion_detector):
    """Create appropriate executor based on LangGraph availability.
    
    Args:
        llm: Language model
        rag: RAG retrieval engine
        confusion_detector: Unified confusion detector
        
    Returns:
        Executor instance (LangGraph or simplified)
    """
    if LANGGRAPH_AVAILABLE:
        log.info("📊 Using LangGraph-based executor")
        return LangGraphAgenticRAGExecutor(llm, rag, confusion_detector)
    else:
        log.info("⚙️  Using simplified executor (LangGraph not installed)")
        return SimpleAgenticRAGExecutor(llm, rag, confusion_detector)


# Singleton executor
_executor: Optional[SimpleAgenticRAGExecutor | LangGraphAgenticRAGExecutor] = None


def get_agentic_rag_executor(llm, rag, confusion_detector):
    """Get or create singleton executor."""
    global _executor
    if _executor is None:
        _executor = create_agentic_rag_executor(llm, rag, confusion_detector)
    return _executor


__all__ = [
    "create_agentic_rag_executor",
    "get_agentic_rag_executor",
    "SimpleAgenticRAGExecutor",
    "LangGraphAgenticRAGExecutor",
    "AgenticRAGState",
]
