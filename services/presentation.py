from __future__ import annotations

import logging

from database.repositories import get_course_with_structure
from modules.pedagogy.course_analyzer import get_analyzer

log = logging.getLogger("SmartTeacher.Presentation")

_COURSE_ANALYSIS_CACHE: dict[str, dict] = {}


def _build_course_analysis(course) -> dict:
    cache_key = str(course.id)
    cached = _COURSE_ANALYSIS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    analyzer = get_analyzer()
    course_data = {
        "title": course.title,
        "domain": course.domain or "general",
        "chapters": [
            {
                "title": chapter.title,
                "sections": [
                    {"title": section.title, "content": section.content or ""}
                    for section in sorted(chapter.sections, key=lambda item: item.order or 0)
                ],
            }
            for chapter in sorted(course.chapters, key=lambda item: item.order or 0)
        ],
    }

    try:
        analysis = analyzer.analyze(course_data) or {}
    except Exception as exc:
        log.debug("Course analysis error for %s: %s", course.id, exc)
        analysis = {}

    analysis.setdefault("course_domain", analysis.get("domain", course.domain or "general"))
    analysis.setdefault("course_subject", course.subject)
    analysis.setdefault("course_title", course.title)
    analysis.setdefault("course_language", analysis.get("language", course.language))

    _COURSE_ANALYSIS_CACHE[cache_key] = analysis
    return analysis


async def load_course_slide_context(course_id: str, chapter_index: int, section_index: int) -> dict | None:
    if not course_id:
        return None

    try:
        import uuid

        from database.core import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            course = await get_course_with_structure(db, uuid.UUID(course_id))
            if not course:
                return None

            chapters = sorted(course.chapters, key=lambda ch: ch.order or 0)
            if chapter_index < 0 or chapter_index >= len(chapters):
                return None

            chapter = chapters[chapter_index]
            sections = sorted(chapter.sections, key=lambda sec: sec.order or 0)
            if section_index < 0 or section_index >= len(sections):
                return None

            section = sections[section_index]
            slide_path = section.image_url or (section.image_urls[0] if getattr(section, "image_urls", None) else "")
            total_sections = sum(len(sorted(ch.sections, key=lambda sec: sec.order or 0)) for ch in chapters)
            global_slide_index = sum(len(sorted(ch.sections, key=lambda sec: sec.order or 0)) for ch in chapters[:chapter_index]) + section_index
            progress_pct = round(global_slide_index / max(total_sections - 1, 1) * 100) if total_sections > 1 else 0

            analysis = _build_course_analysis(course)

            return {
                "course_id": str(course.id),
                "course_title": course.title,
                "course_subject": course.subject,
                "course_domain": course.domain or "general",
                "language": course.language,
                "level": course.level,
                "chapter_index": chapter_index,
                "chapter_order": chapter.order or chapter_index + 1,
                "chapter_title": chapter.title,
                "section_index": section_index,
                "section_order": section.order or section_index + 1,
                "section_title": section.title,
                "content": section.content or "",
                "slide_path": slide_path,
                "image_url": slide_path,
                "slide_index": global_slide_index,
                "slide_type": "image" if slide_path else "section",
                "keywords": [c.term for c in section.concepts if c.term],
                "concepts": [
                    {"term": c.term, "definition": c.definition, "example": c.example, "type": c.concept_type}
                    for c in section.concepts
                ],
                "progress_pct": progress_pct,
                "course_summary": analysis.get("summary", ""),
                "course_analysis": analysis,
            }
    except Exception:
        return None


async def load_current_slide_context(course_id: str, chapter_index: int, section_index: int) -> dict | None:
    return await load_course_slide_context(course_id, chapter_index, section_index)
