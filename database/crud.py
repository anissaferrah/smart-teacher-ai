# database/crud.py
"""
Smart Teacher — Opérations CRUD pour PostgreSQL
"""

import uuid
import logging
from typing import Optional, List
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Course, Chapter, Section, Concept, LearningSession, Interaction

log = logging.getLogger("SmartTeacher.CRUD")


# ══════════════════════════════════════════════════════════════════════
# COURS
# ══════════════════════════════════════════════════════════════════════

async def create_course(db: AsyncSession, course_data: dict) -> Course:
    """Crée un nouveau cours."""
    course = Course(**course_data)
    db.add(course)
    await db.flush()
    return course


async def create_course_with_structure(db: AsyncSession, course_data: dict) -> uuid.UUID:
    """
    Crée un cours complet avec sa structure hiérarchique.
    course_data = {
        "title": "...",
        "subject": "...",
        "language": "...",
        "level": "...",
        "chapters": [
            {
                "title": "...",
                "order": 1,
                "sections": [
                    {
                        "title": "...",
                        "order": 1,
                        "content": "...",
                        "duration_s": 120,
                        "concepts": [
                            {"term": "...", "definition": "...", "example": "..."}
                        ]
                    }
                ]
            }
        ]
    }
    """
    # Créer le cours
    course = Course(
        title=course_data["title"],
        subject=course_data.get("subject", "general"),
        language=course_data.get("language", "fr"),
        level=course_data.get("level", "lycée"),
        description=course_data.get("description", ""),
        file_path=course_data.get("file_path", ""),
    )
    db.add(course)
    await db.flush()

    # Créer les chapitres et sections
    for ch_idx, ch_data in enumerate(course_data.get("chapters", [])):
        chapter = Chapter(
            course_id=course.id,
            title=ch_data["title"],
            order=ch_data.get("order", ch_idx + 1),
            summary=ch_data.get("summary", ""),
        )
        db.add(chapter)
        await db.flush()

        for sec_idx, sec_data in enumerate(ch_data.get("sections", [])):
            section = Section(
                chapter_id=chapter.id,
                title=sec_data["title"],
                order=sec_data.get("order", sec_idx + 1),
                content=sec_data.get("content", ""),
                duration_s=sec_data.get("duration_s", 120),
                image_urls=sec_data.get("image_urls", []),
            )
            db.add(section)
            await db.flush()

            for c_data in sec_data.get("concepts", []):
                concept = Concept(
                    section_id=section.id,
                    term=c_data["term"],
                    definition=c_data.get("definition", ""),
                    example=c_data.get("example", ""),
                    concept_type=c_data.get("type", "definition"),
                )
                db.add(concept)

    await db.commit()
    return course.id


async def get_course(db: AsyncSession, course_id: uuid.UUID) -> Optional[Course]:
    """Récupère un cours par son ID."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    return result.scalar_one_or_none()


async def get_course_with_structure(db: AsyncSession, course_id: uuid.UUID) -> Optional[Course]:
    """Récupère un cours avec tous ses chapitres, sections et concepts."""
    result = await db.execute(
        select(Course)
        .where(Course.id == course_id)
        .options(
            selectinload(Course.chapters)
            .selectinload(Chapter.sections)
            .selectinload(Section.concepts)
        )
    )
    return result.scalar_one_or_none()


async def get_all_courses(db: AsyncSession) -> List[Course]:
    """Récupère tous les cours."""
    result = await db.execute(select(Course).order_by(Course.created_at.desc()))
    return result.scalars().all()


async def delete_course(db: AsyncSession, course_id: uuid.UUID) -> bool:
    """Supprime un cours."""
    course = await get_course(db, course_id)
    if course:
        await db.delete(course)
        await db.commit()
        return True
    return False


# ══════════════════════════════════════════════════════════════════════
# SESSIONS D'APPRENTISSAGE
# ══════════════════════════════════════════════════════════════════════

async def create_learning_session(
    db: AsyncSession,
    student_id: str,
    course_id: Optional[uuid.UUID] = None,
    language: str = "fr",
    level: str = "lycée"
) -> LearningSession:
    """Crée une nouvelle session d'apprentissage."""
    session = LearningSession(
        student_id=student_id,
        course_id=course_id,
        language=language,
        level=level,
    )
    db.add(session)
    await db.flush()
    return session


async def update_session_state(
    db: AsyncSession,
    session_id: uuid.UUID,
    state: str,
    chapter_index: int = None,
    section_index: int = None,
    char_position: int = None
) -> Optional[LearningSession]:
    """Met à jour l'état d'une session."""
    stmt = update(LearningSession).where(LearningSession.id == session_id)
    updates = {"state": state}
    if chapter_index is not None:
        updates["chapter_index"] = chapter_index
    if section_index is not None:
        updates["section_index"] = section_index
    if char_position is not None:
        updates["char_position"] = char_position
    await db.execute(stmt.values(**updates))
    await db.commit()
    return await get_session(db, session_id)


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> Optional[LearningSession]:
    """Récupère une session par son ID."""
    result = await db.execute(select(LearningSession).where(LearningSession.id == session_id))
    return result.scalar_one_or_none()


async def end_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    """Termine une session."""
    from datetime import datetime
    await db.execute(
        update(LearningSession)
        .where(LearningSession.id == session_id)
        .values(ended_at=datetime.utcnow(), state="IDLE")
    )
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# INTERACTIONS
# ══════════════════════════════════════════════════════════════════════

async def log_interaction(
    db: AsyncSession,
    session_id: uuid.UUID,
    student_id: str,
    question: str,
    answer: str,
    language: str = "fr",
    stt_time: float = 0.0,
    llm_time: float = 0.0,
    tts_time: float = 0.0,
    total_time: float = 0.0,
    kpi_ok: bool = False,
    course_id: Optional[uuid.UUID] = None,
    interaction_type: str = "qa"
) -> Interaction:
    """Enregistre une interaction."""
    interaction = Interaction(
        session_id=session_id,
        student_id=student_id,
        course_id=course_id,
        type=interaction_type,
        question=question,
        answer=answer,
        language=language,
        stt_time=stt_time,
        llm_time=llm_time,
        tts_time=tts_time,
        total_time=total_time,
        kpi_ok=1 if kpi_ok else 0,
    )
    db.add(interaction)
    await db.flush()
    return interaction


async def get_session_stats(db: AsyncSession, session_id: uuid.UUID) -> dict:
    """Retourne les statistiques d'une session."""
    result = await db.execute(
        select(func.count(Interaction.id))
        .where(Interaction.session_id == session_id)
    )
    total_interactions = result.scalar() or 0

    result = await db.execute(
        select(func.avg(Interaction.total_time))
        .where(Interaction.session_id == session_id)
    )
    avg_time = result.scalar() or 0.0

    result = await db.execute(
        select(func.sum(Interaction.kpi_ok))
        .where(Interaction.session_id == session_id)
    )
    kpi_ok_count = result.scalar() or 0

    return {
        "total_interactions": total_interactions,
        "avg_response_time": round(avg_time, 2),
        "kpi_rate": round(kpi_ok_count / total_interactions * 100, 1) if total_interactions else 0,
    }


# Import pour les relations
from sqlalchemy.orm import selectinload