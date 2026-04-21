"""Presentation service - slide narration, caching, prefetch logic.

Responsibilities:
- Load course slides from database
- Generate narration using LLM + TTS
- Cache audio for performance
- Prefetch next slides
- Handle pause/resume logic
"""

import asyncio
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime

from domain.session_state import SessionContext, DialogState, CourseSlide
from infrastructure.config import settings
from infrastructure.logging import get_logger

log = get_logger(__name__)


class PresentationService:
    """Service for course slide presentation and narration."""
    
    def __init__(self, dialogue_mgr, rag, llm, voice):
        """Initialize presentation service.
        
        Args:
            dialogue_mgr: Dialogue manager for multi-turn conversation
            rag: RAG retrieval engine
            llm: Language model (brain)
            voice: Text-to-speech synthesizer
        """
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
        """Load a course slide metadata.
        
        Args:
            course_id: Course identifier
            chapter_index: Chapter index (0-based)
            section_index: Section index (0-based)
            
        Returns:
            CourseSlide: Slide metadata, or None if not found
        """
        try:
            from database.repositories.crud import get_course_with_structure
            from database.core import AsyncSessionLocal
            
            async with AsyncSessionLocal() as db:
                course_struct = await get_course_with_structure(db, course_id)
                if not course_struct:
                    return None
                
                # Navigate to chapter/section
                course_data = course_struct.get("data", {})
                chapters = course_data.get("chapters", [])
                
                if chapter_index >= len(chapters):
                    return None
                
                chapter = chapters[chapter_index]
                sections = chapter.get("sections", [])
                
                if section_index >= len(sections):
                    return None
                
                section = sections[section_index]
                
                return CourseSlide(
                    course_id=course_id,
                    course_title=course_data.get("title", ""),
                    course_domain=course_data.get("domain", ""),
                    chapter_index=chapter_index,
                    chapter_title=chapter.get("title", ""),
                    section_index=section_index,
                    section_title=section.get("title", ""),
                    slide_content=section.get("content", ""),
                )
        except Exception as e:
            log.error(f"Failed to load slide: {e}")
            return None
    
    async def explain_slide_focused(
        self,
        slide: CourseSlide,
        student_profile,
        language: str,
    ) -> Tuple[str, str]:
        """Generate focused narration for a slide.
        
        Args:
            slide: Course slide
            student_profile: Student profile (for level adaptation)
            language: Target language
            
        Returns:
            Tuple[str, str]: (narration_text, audio_bytes)
        """
        try:
            cache_key = (slide.course_id, slide.chapter_index, slide.section_index)
            
            # Check narration cache
            if cache_key in self.narration_cache:
                narration = self.narration_cache[cache_key]
            else:
                # Generate narration using LLM
                prompt = self._build_narration_prompt(slide, student_profile, language)
                narration = await self.llm.generate(prompt, temperature=0.6)
                self.narration_cache[cache_key] = narration
            
            # Check audio cache
            if cache_key in self.audio_cache:
                audio_bytes = self.audio_cache[cache_key]
            else:
                # Generate audio using TTS
                audio_bytes = await self.voice.generate_audio_async(
                    narration,
                    language=language,
                    rate_override="+0%" if not settings.realtime_session.enable_rate_adaptation else "+10%",
                )
                self.audio_cache[cache_key] = audio_bytes
            
            return narration, audio_bytes
        
        except Exception as e:
            log.error(f"Failed to explain slide: {e}")
            return "", b""
    
    def _build_narration_prompt(self, slide: CourseSlide, profile, language: str) -> str:
        """Build LLM prompt for narration generation.
        
        Args:
            slide: Course slide
            profile: Student profile
            language: Target language
            
        Returns:
            str: Prompt for LLM
        """
        level = profile.level if profile else "lycée"
        chunk_size = settings.audio.chunk_size
        
        prompt = f"""Tu es un professeur IA. Génère une explication courte et engageante pour cette section de cours.

Contexte:
- Niveau: {level}
- Langue: {language}
- Durée: max {chunk_size} caractères

Titre: {slide.section_title}
Contenu: {slide.slide_content}

Explication:"""
        
        return prompt
    
    async def prefetch_next_slide(
        self,
        course_id: str,
        current_chapter: int,
        current_section: int,
        student_profile,
        language: str,
    ) -> bool:
        """Prefetch next slide narration and audio.
        
        Args:
            course_id: Course identifier
            current_chapter: Current chapter index
            current_section: Current section index
            student_profile: Student profile
            language: Language code
            
        Returns:
            bool: True if prefetch succeeded
        """
        if not settings.realtime_session.prefetch_next_slide:
            return False
        
        try:
            next_slide = await self.load_slide(
                course_id,
                current_chapter,
                current_section + 1,
            )
            
            if next_slide:
                await self.explain_slide_focused(next_slide, student_profile, language)
                return True
        except Exception as e:
            log.debug(f"Prefetch failed (non-critical): {e}")
        
        return False
    
    async def handle_pause(self, ctx: SessionContext, reason: str) -> Dict[str, Any]:
        """Handle pause point recording.
        
        Args:
            ctx: Session context
            reason: Reason for pause
            
        Returns:
            Dict: Pause state checkpoint
        """
        checkpoint = {
            'timestamp': datetime.utcnow().isoformat(),
            'course_id': ctx.slide.course_id if ctx.slide else None,
            'chapter_index': ctx.slide.chapter_index if ctx.slide else None,
            'section_index': ctx.slide.section_index if ctx.slide else None,
            'narration_cursor': ctx.narration_cursor,
            'reason': reason,
        }
        
        log.info(f"📌 Pause checkpoint: {checkpoint}")
        return checkpoint


__all__ = [
    "PresentationService",
]
