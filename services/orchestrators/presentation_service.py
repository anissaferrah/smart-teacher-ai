# """Presentation service - slide narration, caching, prefetch logic.

# Responsibilities:
# - Load course slides from database
# - Generate narration using LLM + TTS
# - Cache audio for performance
# - Prefetch next slides
# - Handle pause/resume logic
# """

# import asyncio
# import logging
# import uuid
# import threading
# from typing import Optional, Tuple, Dict, Any
# from datetime import datetime

# from domain.session_state import SessionContext, DialogState, CourseSlide
# from infrastructure.config import settings
# from infrastructure.logging import get_logger

# log = get_logger(__name__)


# class PresentationService:
#     """Service for course slide presentation and narration."""
    
#     def __init__(self, dialogue_mgr, rag, llm, voice):
#         """Initialize presentation service.
        
#         Args:
#             dialogue_mgr: Dialogue manager for multi-turn conversation
#             rag: RAG retrieval engine
#             llm: Language model (brain)
#             voice: Text-to-speech synthesizer
#         """
#         self.dialogue = dialogue_mgr
#         self.rag = rag
#         self.llm = llm
#         self.voice = voice
#         self.narration_cache: Dict[Tuple[str, int, int], str] = {}
#         self.audio_cache: Dict[Tuple[str, int, int], bytes] = {}
    
#     async def load_slide(
#         self,
#         course_id: str,
#         chapter_index: int,
#         section_index: int,
#     ) -> Optional[CourseSlide]:
#         """Load a course slide metadata.
        
#         Args:
#             course_id: Course identifier
#             chapter_index: Chapter index (0-based)
#             section_index: Section index (0-based)
            
#         Returns:
#             CourseSlide: Slide metadata, or None if not found
#         """
#         try:
#             from database.repositories.crud import get_course_with_structure
#             from database.core import AsyncSessionLocal

#             try:
#                 course_uuid = uuid.UUID(str(course_id))
#             except Exception:
#                 log.warning("Invalid course id for slide loading: %s", course_id)
#                 return None
            
#             async with AsyncSessionLocal() as db:
#                 course_struct = await get_course_with_structure(db, course_uuid)
#                 if not course_struct:
#                     return None
#                 # Navigate the ORM hierarchy directly: Course -> Chapter -> Section
#                 chapters = sorted(course_struct.chapters or [], key=lambda chapter: chapter.order or 0)
#                 chapter_index = max(0, int(chapter_index))

#                 # Try to find chapter by its order number (e.g., chapter_index=2 → finds Chapter with order=2)
#                 chapter = None
#                 for ch in chapters:
#                     if (ch.order or 0) == chapter_index:
#                         chapter = ch
#                         break

#                 # Fallback: treat as array index
#                 if chapter is None:
#                     arr_idx = chapter_index if chapter_index < len(chapters) else len(chapters) - 1
#                     chapter = chapters[arr_idx]

#                 sections = sorted(chapter.sections or [], key=lambda section: section.order or 0)
#                 if not sections:
#                     return None

#                 if section_index >= len(sections):
#                     # If caller asks for "next" past chapter end, move to next chapter first section.
#                     if chapter_index + 1 < len(chapters):
#                         chapter_index += 1
#                         chapter = chapters[chapter_index]
#                         sections = sorted(chapter.sections or [], key=lambda section: section.order or 0)
#                         if not sections:
#                             return None
#                         section_index = 0
#                     else:
#                         # Clamp to the last available section of the last chapter.
#                         section_index = len(sections) - 1
                
#                 section = sections[section_index]
#                 slide_path = section.image_url or (
#                     section.image_urls[0] if getattr(section, "image_urls", None) else ""
#                 )
                
#                 return CourseSlide(
#                     course_id=course_id,
#                     course_title=course_struct.title or "",
#                     course_domain=course_struct.domain or "",
#                     chapter_index=chapter_index,
#                     chapter_number=int(chapter.order or (chapter_index + 1)),
#                     chapter_title=chapter.title or "",
#                     section_index=section_index,
#                     section_number=int(section.order or (section_index + 1)),
#                     section_title=section.title or "",
#                     slide_path=slide_path,
#                     slide_content=section.content or "",
#                 )
#         except Exception as e:
#             log.error(f"Failed to load slide: {e}")
#             return None
    
#     async def explain_slide_focused(
#         self,
#         slide: CourseSlide,
#         student_profile,
#         language: str,
#         cancel_event: threading.Event | None = None,
#     ) -> Tuple[str, bytes]:
#         """Generate focused narration for a slide.
        
#         Args:
#             slide: Course slide
#             student_profile: Student profile (for level adaptation)
#             language: Target language
            
#         Returns:
#             Tuple[str, str]: (narration_text, audio_bytes)
#         """
#         try:
#             cache_key = (slide.course_id, slide.chapter_index, slide.section_index)
            
#             # Check narration cache
#             if cache_key in self.narration_cache:
#                 narration = self.narration_cache[cache_key]
#             else:
#                 # Generate narration using the Brain presentation API
#                 student_level = student_profile.level if student_profile else "lycée"
#                 narration, _duration = await asyncio.to_thread(
#                     self.llm.present,
#                     section_content=slide.slide_content,
#                     language=language,
#                     student_level=student_level,
#                     chapter_idx=slide.chapter_index,
#                     chapter_title=slide.chapter_title,
#                     section_title=slide.section_title,
#                     domain=slide.course_domain or None,
#                     cancel_event=cancel_event,
#                 )
#                 self.narration_cache[cache_key] = narration

#             if cancel_event and cancel_event.is_set():
#                 return "", b""
            
#             # Check audio cache
#             if cache_key in self.audio_cache:
#                 audio_bytes = self.audio_cache[cache_key]
#             else:
#                 if cancel_event and cancel_event.is_set():
#                     return "", b""

#                 # Generate audio using TTS
#                 audio_bytes, _duration, _engine, _voice, _mime = await self.voice.generate_audio_async(
#                     narration,
#                     language=language,
#                     rate_override="+0%" if not settings.realtime_session.enable_rate_adaptation else "+10%",
#                 )
#                 if cancel_event and cancel_event.is_set():
#                     return "", b""
#                 audio_bytes = audio_bytes or b""
#                 self.audio_cache[cache_key] = audio_bytes
            
#             return narration, audio_bytes
        
#         except Exception as e:
#             log.error(f"Failed to explain slide: {e}")
#             return "", b""
    
#     def _build_narration_prompt(self, slide: CourseSlide, profile, language: str) -> str:
#         """Build LLM prompt for narration generation.
        
#         Args:
#             slide: Course slide
#             profile: Student profile
#             language: Target language
            
#         Returns:
#             str: Prompt for LLM
#         """
#         level = profile.level if profile else "lycée"
#         chunk_size = settings.audio.chunk_size
        
#         prompt = f"""Tu es un professeur IA. Génère une explication courte et engageante pour cette section de cours.

# Contexte:
# - Niveau: {level}
# - Langue: {language}
# - Durée: max {chunk_size} caractères

# Titre: {slide.section_title}
# Contenu: {slide.slide_content}

# Explication:"""
        
#         return prompt
    
#     async def prefetch_next_slide(
#         self,
#         course_id: str,
#         current_chapter: int,
#         current_section: int,
#         student_profile,
#         language: str,
#     ) -> bool:
#         """Prefetch next slide narration and audio.
        
#         Args:
#             course_id: Course identifier
#             current_chapter: Current chapter index
#             current_section: Current section index
#             student_profile: Student profile
#             language: Language code
            
#         Returns:
#             bool: True if prefetch succeeded
#         """
#         if not settings.realtime_session.prefetch_next_slide:
#             return False
        
#         try:
#             next_slide = await self.load_slide(
#                 course_id,
#                 current_chapter,
#                 current_section + 1,
#             )
            
#             if next_slide:
#                 await self.explain_slide_focused(next_slide, student_profile, language)
#                 return True
#         except Exception as e:
#             log.debug(f"Prefetch failed (non-critical): {e}")
        
#         return False
    
#     async def handle_pause(self, ctx: SessionContext, reason: str) -> Dict[str, Any]:
#         """Handle pause point recording.
        
#         Args:
#             ctx: Session context
#             reason: Reason for pause
            
#         Returns:
#             Dict: Pause state checkpoint
#         """
#         checkpoint = {
#             'timestamp': datetime.utcnow().isoformat(),
#             'course_id': ctx.slide.course_id if ctx.slide else None,
#             'chapter_index': ctx.slide.chapter_index if ctx.slide else None,
#             'section_index': ctx.slide.section_index if ctx.slide else None,
#             'narration_cursor': ctx.narration_cursor,
#             'reason': reason,
#         }
        
#         log.info(f"📌 Pause checkpoint: {checkpoint}")
#         return checkpoint


# __all__ = [
#     "PresentationService",
# ]
"""
FIXED presentation_service.py
FIX-5: Slides sorted strictly by order ASC (sequential 1→2→3→…)
FIX-1: course_language stored on the returned CourseSlide object
FIX-3: chapter_index = real DB order value
FIX-4: section_index = real DB order value (= PDF page number)
"""

import asyncio
import logging
import uuid
import threading
from typing import Optional, Tuple, Dict, Any
from datetime import datetime

from domain.session_state import SessionContext, DialogState, CourseSlide
from infrastructure.config import settings
from infrastructure.logging import get_logger

log = get_logger(__name__)


class PresentationService:
    """Service for course slide presentation and narration."""

    def __init__(self, dialogue_mgr, rag, llm, voice):
        self.dialogue = dialogue_mgr
        self.rag = rag
        self.llm = llm
        self.voice = voice
        self.narration_cache: Dict[Tuple[str, int, int], str] = {}
        self.audio_cache: Dict[Tuple[str, int, int], bytes] = {}

    async def load_slide(
        self,
        course_id: str,
        chapter_index: int,
        section_index: int,
    ) -> Optional[CourseSlide]:
        """
        Load slide metadata.

        FIX-3: chapter_index respects DB order (not always 0).
        FIX-4: section_index respects DB order which equals PDF page number.
        FIX-5: chapters and sections sorted strictly by `order` ASC before indexing.
        FIX-1: course language stored on returned CourseSlide.
        """
        try:
            from database.repositories.crud import get_course_with_structure
            from database.core import AsyncSessionLocal

            try:
                course_uuid = uuid.UUID(str(course_id))
            except Exception:
                log.warning("Invalid course id for slide loading: %s", course_id)
                return None

            async with AsyncSessionLocal() as db:
                course_struct = await get_course_with_structure(db, course_uuid)
                if not course_struct:
                    return None

                # FIX-5: sort chapters strictly by order ASC
                chapters = sorted(
                    course_struct.chapters or [],
                    key=lambda ch: int(ch.order or 0)
                )

                if not chapters:
                    return None

                chapter_index = max(0, int(chapter_index))
                section_index = max(0, int(section_index))

                if chapter_index >= len(chapters):
                    chapter_index = len(chapters) - 1

                chapter = chapters[chapter_index]

                # FIX-5: sort sections strictly by order ASC (= PDF page order)
                sections = sorted(
                    chapter.sections or [],
                    key=lambda sec: int(sec.order or 0)
                )

                if not sections:
                    return None

                if section_index >= len(sections):
                    # Move to next chapter's first section
                    if chapter_index + 1 < len(chapters):
                        chapter_index += 1
                        chapter = chapters[chapter_index]
                        sections = sorted(
                            chapter.sections or [],
                            key=lambda sec: int(sec.order or 0)
                        )
                        if not sections:
                            return None
                        section_index = 0
                    else:
                        section_index = len(sections) - 1

                section = sections[section_index]
                slide_path = section.image_url or (
                    section.image_urls[0]
                    if getattr(section, "image_urls", None)
                    else ""
                )

                # FIX-4: section_number = section.order (= PDF page number)
                section_number = int(section.order or (section_index + 1))
                # FIX-3: chapter_number = chapter.order
                chapter_number = int(chapter.order or (chapter_index + 1))

                return CourseSlide(
                    course_id=course_id,
                    course_title=course_struct.title or "",
                    course_domain=course_struct.domain or "",
                    # FIX-1: store course language so session can sync
                    course_language=course_struct.language or "fr",
                    chapter_index=chapter_index,              # FIX-3
                    chapter_number=chapter_number,            # FIX-3
                    chapter_title=chapter.title or "",
                    section_index=section_index,              # FIX-4
                    section_number=section_number,            # FIX-4
                    section_title=section.title or "",
                    slide_path=slide_path,
                    slide_content=section.content or "",
                )

        except Exception as e:
            log.error(f"Failed to load slide: {e}")
            return None

    async def explain_slide_focused(
        self,
        slide: CourseSlide,
        student_profile,
        language: str,
        cancel_event: threading.Event | None = None,
    ) -> Tuple[str, bytes]:
        try:
            cache_key = (slide.course_id, slide.chapter_index, slide.section_index)

            if cache_key in self.narration_cache:
                narration = self.narration_cache[cache_key]
            else:
                student_level = student_profile.level if student_profile else "lycée"
                narration, _duration = await asyncio.to_thread(
                    self.llm.present,
                    section_content=slide.slide_content,
                    language=language,
                    student_level=student_level,
                    chapter_idx=slide.chapter_index,
                    chapter_title=slide.chapter_title,
                    section_title=slide.section_title,
                    domain=slide.course_domain or None,
                    cancel_event=cancel_event,
                )
                self.narration_cache[cache_key] = narration

            if cancel_event and cancel_event.is_set():
                return "", b""

            if cache_key in self.audio_cache:
                audio_bytes = self.audio_cache[cache_key]
            else:
                if cancel_event and cancel_event.is_set():
                    return "", b""

                audio_bytes, _duration, _engine, _voice, _mime = (
                    await self.voice.generate_audio_async(
                        narration,
                        language=language,
                        rate_override=(
                            "+0%"
                            if not settings.realtime_session.enable_rate_adaptation
                            else "+10%"
                        ),
                    )
                )
                if cancel_event and cancel_event.is_set():
                    return "", b""
                audio_bytes = audio_bytes or b""
                self.audio_cache[cache_key] = audio_bytes

            return narration, audio_bytes

        except Exception as e:
            log.error(f"Failed to explain slide: {e}")
            return "", b""

    async def handle_pause(self, ctx: SessionContext, reason: str) -> dict:
        checkpoint = {
            "timestamp": datetime.utcnow().isoformat(),
            "course_id": ctx.slide.course_id if ctx.slide else None,
            "chapter_index": ctx.slide.chapter_index if ctx.slide else None,
            "section_index": ctx.slide.section_index if ctx.slide else None,
            "narration_cursor": ctx.narration_cursor,
            "reason": reason,
        }
        log.info(f"📌 Pause checkpoint: {checkpoint}")
        return checkpoint


__all__ = ["PresentationService"]