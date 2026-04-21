"""
Pydantic models for Agentic RAG state management and validation.
Used throughout the pipeline for type safety and serialization.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class ChunkResult(BaseModel):
    """Represents a retrieved document chunk with metadata."""
    content: str = Field(..., description="The text content of the chunk")
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Relevance score (0-1)")
    source: str = Field(default="", description="Source document or section identifier")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class ReasoningTrace(BaseModel):
    """Tracks a single reasoning step through the pipeline."""
    stage: str = Field(..., description="Pipeline stage name (e.g., 'rewriter', 'clarifier')")
    input_text: str = Field(..., description="Input to this stage")
    output_text: str = Field(..., description="Output from this stage")
    duration_ms: float = Field(default=0.0, ge=0, description="Execution time in milliseconds")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence in this stage's output")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Stage-specific metadata")


class QueryAnalysis(BaseModel):
    """Result of query clarity analysis."""
    is_clear: bool = Field(..., description="Whether query is clear and unambiguous")
    clarification_question: Optional[str] = Field(default=None, description="If ambiguous, what to ask")
    suggested_answers: List[str] = Field(default_factory=list, description="Multiple choice options if needed")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence in clarity assessment")


class SubQuery(BaseModel):
    """A sub-question for multi-agent reasoning."""
    index: int = Field(..., ge=1, description="Order of this sub-query (1, 2, 3, ...)")
    question: str = Field(..., description="The specific sub-question")
    context: str = Field(default="", description="Context for this sub-query")
    response: Optional[str] = Field(default=None, description="Response once answered")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence in response")


class AnswerValidation(BaseModel):
    """Quality assessment of a generated answer."""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0, description="How well answer addresses query")
    coverage_score: float = Field(default=0.0, ge=0.0, le=1.0, description="How complete the answer is")
    accuracy_score: float = Field(default=0.0, ge=0.0, le=1.0, description="How grounded in retrieved chunks")
    clarity_score: float = Field(default=0.0, ge=0.0, le=1.0, description="How understandable")
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Combined confidence score")
    feedback: str = Field(default="", description="Specific feedback for improvement")
    needs_refinement: bool = Field(default=False, description="Whether to loop for refinement")
    refinement_suggestions: List[str] = Field(default_factory=list, description="How to improve")


class ConversationExchange(BaseModel):
    """A single query-response exchange in conversation history."""
    student_query: str = Field(..., description="Student's question")
    ai_answer: str = Field(..., description="AI's response")
    timestamp: datetime = Field(default_factory=datetime.now, description="When this exchange occurred")
    confusion_detected: bool = Field(default=False, description="Was confusion detected in student response?")
    confusion_type: Optional[str] = Field(default=None, description="Type of confusion if detected")


class StudentProfile(BaseModel):
    """Student learning profile for personalization."""
    student_id: str = Field(..., description="Unique student identifier")
    current_level: str = Field(default="beginner", description="Learning level: beginner, intermediate, advanced")
    confusion_topics: List[str] = Field(default_factory=list, description="Topics where student struggles")
    prerequisite_gaps: List[str] = Field(default_factory=list, description="Prerequisite knowledge missing")
    learning_style: Optional[str] = Field(default=None, description="Preferred explanation style")
    recent_focus: Optional[str] = Field(default=None, description="Current topic of study")


class AgenticRAGInput(BaseModel):
    """Input parameters for the agentic RAG pipeline."""
    query: str = Field(..., description="Student's question")
    course_id: Optional[str] = Field(default=None, description="Course context")
    student_id: Optional[str] = Field(default=None, description="Student identifier")
    student_profile: Optional[StudentProfile] = Field(default=None, description="Student learning profile")
    conversation_history: List[ConversationExchange] = Field(default_factory=list, description="Recent exchanges")
    language: str = Field(default="en", description="Response language")
    max_retrieval_chunks: int = Field(default=5, ge=1, le=20, description="Maximum chunks to retrieve")


class AgenticRAGOutput(BaseModel):
    """Output from the agentic RAG pipeline."""
    answer: str = Field(..., description="Final synthesized answer")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Overall confidence (0-1)")
    mode: str = Field(default="agentic", description="Pipeline mode used ('agentic' or 'classic')")

    # Reasoning information
    reasoning: Dict[str, Any] = Field(default_factory=dict, description="Reasoning trace for transparency")
    rewritten_query: Optional[str] = Field(default=None, description="Query after rewriting stage")
    refinement_loops: int = Field(default=0, ge=0, le=10, description="Number of refinement iterations")

    # Source information
    sources: List[ChunkResult] = Field(default_factory=list, description="Retrieved source chunks")

    # Performance metrics
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Performance metrics (timing, etc)")

    # Educational insights (if applicable)
    confusion_note: Optional[str] = Field(default=None, description="Note if student confusion was detected")
    prerequisite_recommendation: Optional[str] = Field(default=None, description="Suggested prerequisite topics")


class PipelineMetrics(BaseModel):
    """Performance metrics for the pipeline."""
    total_time_ms: float = Field(..., ge=0, description="Total pipeline execution time")
    stage_times: Dict[str, float] = Field(default_factory=dict, description="Time per stage in milliseconds")
    retrieval_count: int = Field(default=0, ge=0, description="Number of chunks retrieved")
    reasoning_paths: int = Field(default=0, ge=0, description="Number of reasoning branches (sub-queries)")
    refinement_iterations: int = Field(default=0, ge=0, le=10, description="Refinement loops executed")
    error_occurred: bool = Field(default=False, description="Whether an error occurred")
    error_message: Optional[str] = Field(default=None, description="Error details if applicable")
