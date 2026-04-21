"""Shared state for Agentic RAG workflow."""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime


@dataclass
class AgenticRAGState:
    """Shared state across all agents in LangGraph workflow.
    
    This is the central state object passed through the graph.
    Each agent reads from and writes to this state.
    """
    
    # === INPUT ===
    query: str = ""
    course_id: Optional[str] = None
    student_profile: Optional[Dict[str, Any]] = None
    history: List[Dict[str, str]] = field(default_factory=list)
    
    # === QUERY REWRITING ===
    rewritten_query: Optional[str] = None
    query_intent: Optional[str] = None
    
    # === CLARIFICATION ===
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    
    # === RETRIEVAL ===
    retrieved_chunks: List[Dict[str, Any]] = field(default_factory=list)
    retrieval_confidence: float = 0.0
    retrieval_strategy: str = ""
    
    # === REASONING ===
    reasoning: Optional[str] = None
    draft_answer: Optional[str] = None
    reasoning_confidence: float = 0.0
    
    # === REFLECTION ===
    is_valid: bool = False
    reflection_score: float = 0.0
    reflection_notes: Optional[str] = None
    needs_refinement: bool = False
    refinement_suggestions: List[str] = field(default_factory=list)
    
    # === FINAL OUTPUT ===
    final_answer: Optional[str] = None
    final_confidence: float = 0.0
    
    # === METADATA ===
    agent_metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    loop_count: int = 0
    max_loops: int = 2
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "query": self.query,
            "rewritten_query": self.rewritten_query,
            "needs_clarification": self.needs_clarification,
            "retrieval_confidence": self.retrieval_confidence,
            "draft_answer": self.draft_answer,
            "is_valid": self.is_valid,
            "reflection_score": self.reflection_score,
            "final_answer": self.final_answer,
            "final_confidence": self.final_confidence,
            "agent_metadata": self.agent_metadata,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgenticRAGState":
        """Create state from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


__all__ = [
    "AgenticRAGState",
]
