"""Session state domain model and state machine.

This module defines the core domain logic for session lifecycle:
- SessionState: Immutable state representation
- Valid state transitions (state machine)
- Session context data

The state machine is strict: only defined transitions are allowed.
This prevents invalid state combinations and catches bugs early.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Set, Tuple
from datetime import datetime
import uuid


class DialogState(str, Enum):
    """Session conversation states (strict state machine)."""
    
    # Initial: no activity
    WAITING = "waiting"
    
    # Listening: recording student audio
    LISTENING = "listening"
    
    # Processing: STT + RAG + LLM (no audio feedback)
    PROCESSING = "processing"

    # Presenting: course narration playback in progress
    PRESENTING = "presenting"
    
    # Responding: TTS playback of AI response
    RESPONDING = "responding"
    
    # Paused: user interrupted presentation
    PAUSED = "paused"
    
    # Idle: session alive but no active interaction
    IDLE = "idle"
    
    # Ended: session terminated
    ENDED = "ended"


# Valid state transitions (strict)
STATE_TRANSITIONS: Dict[DialogState, Set[DialogState]] = {
    DialogState.WAITING: {DialogState.IDLE, DialogState.LISTENING, DialogState.PRESENTING, DialogState.ENDED},
    DialogState.IDLE: {DialogState.WAITING, DialogState.LISTENING, DialogState.PRESENTING, DialogState.ENDED},
    DialogState.PRESENTING: {DialogState.LISTENING, DialogState.PAUSED, DialogState.IDLE, DialogState.ENDED},
    DialogState.LISTENING: {DialogState.PROCESSING, DialogState.IDLE, DialogState.PAUSED, DialogState.PRESENTING},
    DialogState.PROCESSING: {DialogState.RESPONDING, DialogState.IDLE, DialogState.PAUSED},
    DialogState.RESPONDING: {DialogState.LISTENING, DialogState.IDLE, DialogState.PAUSED, DialogState.PRESENTING, DialogState.ENDED},
    DialogState.PAUSED: {DialogState.IDLE, DialogState.LISTENING, DialogState.PRESENTING, DialogState.ENDED},
    DialogState.ENDED: set(),  # Terminal state
}


def can_transition(from_state: DialogState, to_state: DialogState) -> bool:
    """Check if transition is valid.
    
    Args:
        from_state: Current state
        to_state: Desired next state
        
    Returns:
        bool: True if transition is allowed
    """
    if from_state == to_state:
        return True  # Self-transitions are always allowed
    return to_state in STATE_TRANSITIONS.get(from_state, set())


@dataclass
class CourseSlide:
    """Course slide reference."""
    course_id: str
    course_title: str = ""
    course_domain: str = ""
    chapter_index: int = 0
    chapter_number: int = 1
    chapter_title: str = ""
    section_index: int = 0
    section_number: int = 1
    section_title: str = ""
    slide_path: str = ""
    slide_content: str = ""
    narration: str = ""


@dataclass
class StudentProfile:
    """Student proficiency and learning style."""
    student_id: str
    level: str = "lycée"  # elementary, middle, lycée, university
    language: str = "fr"
    learning_speed: float = 1.0  # adaptive rate multiplier
    confusion_threshold: float = 0.5  # sensitivity to confusion detection
    extra_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionContext:
    """Session state snapshot.
    
    This is the central state object passed through the session lifecycle.
    It is immutable once created; modifications create new instances.
    """
    
    # Session identity
    session_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    # Student
    student_id: Optional[str] = None
    student_profile: Optional[StudentProfile] = None
    
    # Course slide context
    slide: Optional[CourseSlide] = None
    current_slide_narration: str = ""
    narration_cursor: int = 0  # Position in narration text
    
    # Conversation
    state: DialogState = DialogState.WAITING
    language: str = "fr"
    subject: str = ""
    
    # Metrics
    interaction_count: int = 0
    confusion_detected: bool = False
    confusion_reason: str = ""
    
    # Timestamps (milliseconds)
    stt_time_ms: float = 0.0
    llm_time_ms: float = 0.0
    tts_time_ms: float = 0.0
    total_time_ms: float = 0.0
    
    # Extra metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def create(
        cls,
        student_id: Optional[str] = None,
        profile: Optional[StudentProfile] = None,
        language: str = "fr",
    ) -> "SessionContext":
        """Create a new session context.
        
        Args:
            student_id: Student identifier
            profile: Student profile
            language: Session language
            
        Returns:
            SessionContext: New context
        """
        return cls(
            session_id=str(uuid.uuid4()),
            student_id=student_id,
            student_profile=profile,
            language=language,
        )
    
    def transition_to(self, new_state: DialogState) -> "SessionContext":
        """Create new context with state transition.
        
        Args:
            new_state: Target state
            
        Returns:
            SessionContext: New context with updated state
            
        Raises:
            ValueError: If transition is invalid
        """
        if not can_transition(self.state, new_state):
            raise ValueError(
                f"Invalid state transition: {self.state.value} -> {new_state.value}"
            )
        
        # Create new context (immutable copy)
        new_ctx = SessionContext(
            session_id=self.session_id,
            created_at=self.created_at,
            student_id=self.student_id,
            student_profile=self.student_profile,
            slide=self.slide,
            current_slide_narration=self.current_slide_narration,
            narration_cursor=self.narration_cursor,
            state=new_state,
            language=self.language,
            subject=self.subject,
            interaction_count=self.interaction_count,
            confusion_detected=self.confusion_detected,
            confusion_reason=self.confusion_reason,
            stt_time_ms=self.stt_time_ms,
            llm_time_ms=self.llm_time_ms,
            tts_time_ms=self.tts_time_ms,
            total_time_ms=self.total_time_ms,
            metadata={**self.metadata},
        )
        return new_ctx
    
    def with_metrics(
        self,
        stt_time: float = 0.0,
        llm_time: float = 0.0,
        tts_time: float = 0.0,
    ) -> "SessionContext":
        """Create new context with updated metrics.
        
        Args:
            stt_time: STT processing time (ms)
            llm_time: LLM processing time (ms)
            tts_time: TTS synthesis time (ms)
            
        Returns:
            SessionContext: New context with metrics updated
        """
        new_ctx = SessionContext(
            session_id=self.session_id,
            created_at=self.created_at,
            student_id=self.student_id,
            student_profile=self.student_profile,
            slide=self.slide,
            current_slide_narration=self.current_slide_narration,
            narration_cursor=self.narration_cursor,
            state=self.state,
            language=self.language,
            subject=self.subject,
            interaction_count=self.interaction_count,
            confusion_detected=self.confusion_detected,
            confusion_reason=self.confusion_reason,
            stt_time_ms=stt_time,
            llm_time_ms=llm_time,
            tts_time_ms=tts_time,
            total_time_ms=stt_time + llm_time + tts_time,
            metadata={**self.metadata},
        )
        return new_ctx


__all__ = [
    "DialogState",
    "CourseSlide",
    "StudentProfile",
    "SessionContext",
    "STATE_TRANSITIONS",
    "can_transition",
]
