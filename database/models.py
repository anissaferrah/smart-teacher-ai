# database/models.py
"""
Smart Teacher — Modèles SQLAlchemy pour PostgreSQL
Structure hiérarchique : Course → Chapter → Section → Concept
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Course(Base):
    """Cours principal."""
    __tablename__ = "courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    subject = Column(String(50), nullable=False, default="general")
    language = Column(String(5), nullable=False, default="fr")
    level = Column(String(20), nullable=False, default="lycée")
    description = Column(Text)
    file_path = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    chapters = relationship("Chapter", back_populates="course", cascade="all, delete-orphan")


class Chapter(Base):
    """Chapitre d'un cours."""
    __tablename__ = "chapters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    order = Column(Integer, default=0)
    summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relations
    course = relationship("Course", back_populates="chapters")
    sections = relationship("Section", back_populates="chapter", cascade="all, delete-orphan")


class Section(Base):
    """Section d'un chapitre."""
    __tablename__ = "sections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    order = Column(Integer, default=0)
    content = Column(Text)  # Texte ORIGINAL du cours
    duration_s = Column(Integer, default=120)
    image_urls = Column(JSON, default=list)  # URLs des images associées
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relations
    chapter = relationship("Chapter", back_populates="sections")
    concepts = relationship("Concept", back_populates="section", cascade="all, delete-orphan")


class Concept(Base):
    """Concept clé d'une section."""
    __tablename__ = "concepts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), nullable=False)
    term = Column(String(100), nullable=False)
    definition = Column(Text)
    example = Column(Text)
    concept_type = Column(String(20), default="definition")  # definition, formula, theorem, example
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relations
    section = relationship("Section", back_populates="concepts")


class LearningSession(Base):
    """Session d'apprentissage d'un étudiant."""
    __tablename__ = "learning_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(String(100), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"))
    language = Column(String(5), default="fr")
    level = Column(String(20), default="lycée")
    state = Column(String(20), default="IDLE")  # IDLE, PRESENTING, LISTENING, PROCESSING, RESPONDING
    chapter_index = Column(Integer, default=0)
    section_index = Column(Integer, default=0)
    char_position = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Interaction(Base):
    """Interaction entre étudiant et professeur IA."""
    __tablename__ = "interactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("learning_sessions.id", ondelete="CASCADE"))
    student_id = Column(String(100), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"))
    type = Column(String(20), default="qa")  # qa, interrupt, navigation
    question = Column(Text)
    answer = Column(Text)
    language = Column(String(5), default="fr")
    stt_time = Column(Float, default=0.0)
    llm_time = Column(Float, default=0.0)
    tts_time = Column(Float, default=0.0)
    total_time = Column(Float, default=0.0)
    kpi_ok = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)