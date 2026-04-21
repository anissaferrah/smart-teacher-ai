# database/models.py
"""
Smart Teacher — SQLAlchemy Models for PostgreSQL.

Database schema with hierarchical structure:
    Course → Chapter → Section → Concept

Supports:
    - Course management with metadata (subject, language, level)
    - Chapter organization with ordering
    - Sections with original course content
    - Key concepts tied to sections
    - Student learning sessions with state tracking
    - Interaction logging for analytics

All models use UUID primary keys and timestamps for audit trails.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship, Mapped

# ════════════════════════════════════════════════════════════════════════
# BASE DECLARATION
# ════════════════════════════════════════════════════════════════════════

Base = declarative_base()


# ════════════════════════════════════════════════════════════════════════
# AUTHENTICATION MODEL
# ════════════════════════════════════════════════════════════════════════


class Student(Base):
    """
    Student model — user account for authentication.
    
    Attributes
    ----------
    id : UUID
        Unique student identifier (auto-generated)
    email : str
        Unique email address
    password_hash : str
        Hashed password (bcrypt)
    first_name : str
        Student's first name
    last_name : str
        Student's last name
    preferred_language : str
        ISO 639-1 language code (e.g., "fr", "en")
    account_level : str
        Account level (e.g., "student", "teacher", "admin")
    is_active : bool
        Account active status
    created_at : datetime
        Account creation timestamp (UTC)
    updated_at : datetime
        Last update timestamp (UTC)
    """

    __tablename__ = "students"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=True)
    first_name = Column(String(100), nullable=False, default="Utilisateur")
    last_name = Column(String(100), nullable=True)
    preferred_language = Column(String(5), nullable=False, default="fr")
    account_level = Column(String(20), nullable=False, default="student")
    is_active = Column(Integer, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# ════════════════════════════════════════════════════════════════════════
# COURSE HIERARCHY MODELS
# ════════════════════════════════════════════════════════════════════════


class Course(Base):
    """
    Course model — represents a complete course offering.
    
    Attributes
    ----------
    id : UUID
        Unique identifier (auto-generated)
    title : str
        Course title (e.g., "Fundamentals of Statistics")
    subject : str
        Subject area (e.g., "data_science", "mathematics", "general")
    language : str
        ISO 639-1 language code (e.g., "fr", "en")
    level : str
        Course level (e.g., "lycée", "master", "phd")
    description : str, optional
        Long-form description of course content
    file_path : str, optional
        Path to source PDF or course file
    created_at : datetime
        Course creation timestamp (UTC)
    updated_at : datetime
        Last update timestamp (UTC)
    chapters : List[Chapter]
        One-to-many relationship with Chapter
    """

    __tablename__ = "courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False, index=True)
    domain = Column(String(100), nullable=False, default="general", index=True)  # 🎯 Domaine (informatique, general, etc.)
    subject = Column(String(255), nullable=False, default="general", index=True)
    language = Column(String(5), nullable=False, default="fr")
    level = Column(String(20), nullable=False, default="lycée")
    description = Column(Text)
    file_path = Column(String(500))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    chapters: Mapped[List["Chapter"]] = relationship(
        "Chapter",
        back_populates="course",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Chapter.order"
    )


class Chapter(Base):
    """
    Chapter model — represents a chapter within a course.
    
    Attributes
    ----------
    id : UUID
        Unique identifier (auto-generated)
    course_id : UUID
        Foreign key to parent Course
    title : str
        Chapter title (e.g., "Chapter 1: Introduction")
    order : int
        Sequential order within course (0-indexed)
    summary : str, optional
        Brief summary or learning objectives
    created_at : datetime
        Creation timestamp (UTC)
    course : Course
        Back-reference to parent Course
    sections : List[Section]
        One-to-many relationship with Section
    """

    __tablename__ = "chapters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    title = Column(String(255), nullable=False, index=True)
    order = Column(Integer, nullable=False, default=0)
    summary = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relations
    course: Mapped[Course] = relationship("Course", back_populates="chapters")
    sections: Mapped[List["Section"]] = relationship(
        "Section",
        back_populates="chapter",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Section.order"
    )


class Section(Base):
    """
    Section model — represents a section within a chapter.
    
    Attributes
    ----------
    id : UUID
        Unique identifier (auto-generated)
    chapter_id : UUID
        Foreign key to parent Chapter
    title : str
        Section title
    order : int
        Sequential order within chapter (0-indexed)
    content : str
        Original course text (exact PDF content)
    duration_s : int
        Estimated reading/teaching time in seconds
    image_urls : list[str]
        URLs to associated slide images (JSON array)
    created_at : datetime
        Creation timestamp (UTC)
    chapter : Chapter
        Back-reference to parent Chapter
    concepts : List[Concept]
        One-to-many relationship with Concept
    """

    __tablename__ = "sections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chapter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    title = Column(String(255), nullable=False, index=True)
    order = Column(Integer, nullable=False, default=0)
    content = Column(Text)  # Original course content from PDF
    image_url = Column(String(500))  # 🎨 PNG slide path (e.g., /media/slides/general/mon_cours/chapter_1/page_001.png)
    duration_s = Column(Integer, nullable=False, default=120)
    image_urls = Column(JSON, nullable=False, default=list)  # Array of slide image URLs
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relations
    chapter: Mapped[Chapter] = relationship("Chapter", back_populates="sections")
    concepts: Mapped[List["Concept"]] = relationship(
        "Concept",
        back_populates="section",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Concept.created_at"
    )


class Concept(Base):
    """
    Concept model — represents a key concept within a section.
    
    Attributes
    ----------
    id : UUID
        Unique identifier (auto-generated)
    section_id : UUID
        Foreign key to parent Section
    term : str
        The concept term or name (e.g., "k-means clustering")
    definition : str, optional
        Formal definition or explanation
    example : str, optional
        Concrete example or use case
    concept_type : str
        Type of concept: "definition", "formula", "theorem", "example"
    created_at : datetime
        Creation timestamp (UTC)
    section : Section
        Back-reference to parent Section
    """

    __tablename__ = "concepts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    term = Column(String(100), nullable=False, index=True)
    definition = Column(Text)
    example = Column(Text)
    concept_type = Column(String(20), nullable=False, default="definition")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relations
    section: Mapped[Section] = relationship("Section", back_populates="concepts")


# ════════════════════════════════════════════════════════════════════════
# SESSION & INTERACTION MODELS
# ════════════════════════════════════════════════════════════════════════


class LearningSession(Base):
    """
    Learning session model — tracks a student's learning session.
    
    Attributes
    ----------
    id : UUID
        Unique session identifier (auto-generated)
    student_id : str
        Anonymous student identifier (hash or UUID)
    course_id : UUID, optional
        Foreign key to enrolled Course
    language : str
        ISO 639-1 language code (e.g., "fr", "en")
    level : str
        Student level (e.g., "lycée", "master")
    state : str
        Current state: "IDLE", "PRESENTING", "LISTENING", "PROCESSING", "RESPONDING"
    chapter_index : int
        Zero-indexed chapter currently being studied
    section_index : int
        Zero-indexed section within current chapter
    char_position : int
        Character position within current section (for resume capability)
    started_at : datetime
        Session start time (UTC)
    ended_at : datetime, optional
        Session end time (UTC) — null if still active
    updated_at : datetime
        Last activity timestamp (UTC)
    """

    __tablename__ = "learning_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(String(100), nullable=False, index=True)
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="SET NULL"),
        index=True
    )
    language = Column(String(5), nullable=False, default="fr")
    level = Column(String(20), nullable=False, default="lycée")
    state = Column(String(20), nullable=False, default="IDLE")
    chapter_index = Column(Integer, nullable=False, default=0)
    section_index = Column(Integer, nullable=False, default=0)
    char_position = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Interaction(Base):
    """
    Interaction model — logs each student-teacher exchange.
    
    Attributes
    ----------
    id : UUID
        Unique interaction identifier (auto-generated)
    session_id : UUID
        Foreign key to parent LearningSession
    student_id : str
        Anonymous student identifier (hash or UUID)
    course_id : UUID, optional
        Foreign key to Course
    type : str
        Interaction type: "qa" (question/answer), "interrupt", "navigation"
    question : str, optional
        Student's question (from STT)
    answer : str, optional
        Teacher's response (LLM output)
    language : str
        Language used in interaction (ISO 639-1)
    stt_time : float
        Speech-to-text processing time in seconds
    llm_time : float
        Language model inference time in seconds
    tts_time : float
        Text-to-speech generation time in seconds
    total_time : float
        Total wall-clock time in seconds
    kpi_ok : int
        Binary flag: 1 if response met performance KPI, 0 otherwise
    created_at : datetime
        Interaction timestamp (UTC)
    """

    __tablename__ = "interactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("learning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    student_id = Column(String(100), nullable=False, index=True)
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="SET NULL"),
        index=True
    )
    type = Column(String(20), nullable=False, default="qa", index=True)
    question = Column(Text)
    answer = Column(Text)
    language = Column(String(5), nullable=False, default="fr")
    stt_time = Column(Float, nullable=False, default=0.0)
    llm_time = Column(Float, nullable=False, default=0.0)
    tts_time = Column(Float, nullable=False, default=0.0)
    total_time = Column(Float, nullable=False, default=0.0)
    kpi_ok = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class LearningEvent(Base):
    """Detailed pedagogical event log for model readiness and offline training."""

    __tablename__ = "learning_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("learning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id = Column(String(100), nullable=False, index=True)
    course_id = Column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="SET NULL"),
        index=True,
    )
    event_type = Column(String(30), nullable=False, default="qa", index=True)
    input_text = Column(Text)
    output_text = Column(Text)
    concept = Column(String(255), index=True)
    action_taken = Column(String(100), index=True)
    confusion_score = Column(Float, nullable=False, default=0.0)
    reward = Column(Float, nullable=False, default=0.0)
    stt_time = Column(Float, nullable=False, default=0.0)
    llm_time = Column(Float, nullable=False, default=0.0)
    tts_time = Column(Float, nullable=False, default=0.0)
    total_time = Column(Float, nullable=False, default=0.0)
    student_state = Column(JSON, nullable=False, default=dict)
    event_payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


# ════════════════════════════════════════════════════════════════════════
# ADVANCED FEATURES MODELS
# ════════════════════════════════════════════════════════════════════════


class StudentProfile(Base):
    """Student profile with preferences and learning metadata."""
    __tablename__ = "student_profiles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    learning_style = Column(String(50), default="visual")  # visual, auditory, kinesthetic
    preferred_difficulty = Column(String(20), default="intermediate")
    topics_of_interest = Column(JSON, default=list)
    total_xp = Column(Integer, default=0)
    streak_days = Column(Integer, default=0)
    last_activity = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StudentMistake(Base):
    """Track student mistakes for adaptive learning."""
    __tablename__ = "student_mistakes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(String(100), nullable=False, index=True)
    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=True)
    mistake_type = Column(String(50), nullable=False)  # typo, logic, understanding, etc.
    context = Column(Text)
    frequency = Column(Integer, default=1)
    last_occurred = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class RAGChunk(Base):
    """Vector database chunks for RAG retrieval."""
    __tablename__ = "rag_chunks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    section_id = Column(UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), nullable=True)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer)
    vector_id = Column(String(100))  # Qdrant vector ID
    chunk_metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemLog(Base):
    """System-level logging and monitoring."""
    __tablename__ = "system_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    level = Column(String(20), default="INFO")  # INFO, WARNING, ERROR, DEBUG
    module = Column(String(100))
    message = Column(Text)
    context = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class PerformanceMetric(Base):
    """Performance metrics and KPIs."""
    __tablename__ = "performance_metrics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    metric_name = Column(String(100), nullable=False, index=True)
    metric_value = Column(Float)
    student_id = Column(String(100), index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"))
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)


class LLMCache(Base):
    """Cache for LLM responses to reduce API calls."""
    __tablename__ = "llm_cache"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_hash = Column(String(64), nullable=False, unique=True, index=True)
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    model = Column(String(50), default="gpt-3.5-turbo")
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=True)  # For TTL management