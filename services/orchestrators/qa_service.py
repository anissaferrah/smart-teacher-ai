"""QA service - question answering, confusion detection, quiz generation.

Responsibilities:
- Process student questions (text/audio)
- Retrieve relevant context using RAG
- Detect student confusion
- Generate LLM responses
- Generate quizzes
- Log learning interactions
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from domain.session_state import SessionContext, DialogState
from infrastructure.config import settings
from infrastructure.logging import get_logger
from services.analytics.clickhouse_events import get_analytics_sink

log = get_logger(__name__)


class QAService:
    """Service for question-answering interactions."""
    
    def __init__(self, rag, llm, voice, confusion_detector, analytics_sink=None):
        """Initialize QA service.
        
        Args:
            rag: RAG retrieval engine
            llm: Language model
            voice: Text-to-speech synthesizer
            confusion_detector: Confusion detection model
            analytics_sink: Analytics event sink (uses global if None)
        """
        self.rag = rag
        self.llm = llm
        self.voice = voice
        self.confusion_detector = confusion_detector
        self.analytics = analytics_sink or get_analytics_sink()
    
    async def process_text_question(
        self,
        session_id: str,
        question_text: str,
        ctx: SessionContext,
        language: str,
        subject: str,
    ) -> Tuple[str, Optional[str], Dict[str, Any]]:
        """Process a text-based student question.
        
        Args:
            session_id: Session identifier
            question_text: Student's question
            ctx: Session context
            language: Question language
            subject: Subject area
            
        Returns:
            Tuple[str, Optional[str], Dict]: (answer_text, audio_bytes, metrics)
        """
        metrics = {
            'rag_time_ms': 0.0,
            'rag_chunks': 0,
            'rag_score': 0.0,
            'confusion_detected': False,
            'confusion_reason': '',
            'llm_time_ms': 0.0,
            'tts_time_ms': 0.0,
        }
        
        try:
            # Step 1: RAG retrieval
            import time
            rag_start = time.time()
            
            rag_results = []
            if settings.rag.enabled and self.rag:
                rag_results = await self.rag.retrieve(
                    question_text,
                    course_id=ctx.slide.course_id if ctx.slide else None,
                    top_k=settings.rag.num_results,
                )
            
            metrics['rag_time_ms'] = (time.time() - rag_start) * 1000
            metrics['rag_chunks'] = len(rag_results)
            if rag_results:
                metrics['rag_score'] = sum(r.get('score', 0) for r in rag_results) / len(rag_results)
            
            # Step 2: Detect confusion
            confusion_result = await self._detect_confusion(question_text, language)
            metrics['confusion_detected'] = confusion_result['detected']
            metrics['confusion_reason'] = confusion_result['reason']
            
            # Step 3: Build LLM prompt
            prompt = self._build_qa_prompt(
                question_text,
                rag_results,
                confusion_result['detected'],
                language,
                subject,
                ctx,
            )
            
            # Step 4: Generate answer
            llm_start = time.time()
            answer_text = await self.llm.generate(prompt, temperature=0.7, max_tokens=400)
            metrics['llm_time_ms'] = (time.time() - llm_start) * 1000
            
            # Step 5: Convert to speech
            tts_start = time.time()
            audio_bytes = await self.voice.generate_audio_async(answer_text, language=language)
            metrics['tts_time_ms'] = (time.time() - tts_start) * 1000
            
            # Step 6: Log to analytics
            await self._log_learning_turn(
                session_id, question_text, answer_text, ctx, language, subject, metrics
            )
            
            return answer_text, audio_bytes, metrics
        
        except Exception as e:
            log.error(f"QA processing failed: {e}")
            self.analytics.record_error(
                session_id,
                'qa_service',
                type(e).__name__,
                str(e),
            )
            return "", None, metrics
    
    async def process_quiz(
        self,
        session_id: str,
        ctx: SessionContext,
        language: str,
        subject: str,
        topic: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate a quiz based on current course material.
        
        Args:
            session_id: Session identifier
            ctx: Session context
            language: Language code
            subject: Subject area
            topic: Optional specific topic
            
        Returns:
            Tuple[str, Dict]: (quiz_question, metadata)
        """
        try:
            # Retrieve relevant material
            rag_results = []
            if settings.rag.enabled and self.rag:
                query = topic or ctx.slide.section_title if ctx.slide else "general"
                rag_results = await self.rag.retrieve(
                    query,
                    course_id=ctx.slide.course_id if ctx.slide else None,
                    top_k=3,
                )
            
            # Generate quiz question
            prompt = self._build_quiz_prompt(
                rag_results,
                subject,
                language,
                ctx.student_profile.level if ctx.student_profile else "lycée",
            )
            
            quiz_question = await self.llm.generate(prompt, temperature=0.8, max_tokens=150)
            
            metadata = {
                'topic': topic,
                'rag_chunks': len(rag_results),
                'generated_at': datetime.utcnow().isoformat(),
            }
            
            return quiz_question, metadata
        
        except Exception as e:
            log.error(f"Quiz generation failed: {e}")
            return "", {}
    
    async def _detect_confusion(self, text: str, language: str) -> Dict[str, Any]:
        """Detect if student is confused.
        
        Args:
            text: Student's text input
            language: Language code
            
        Returns:
            Dict: {'detected': bool, 'reason': str}
        """
        if not settings.confusion.enabled or not self.confusion_detector:
            return {'detected': False, 'reason': ''}
        
        try:
            result = await self.confusion_detector.detect(text, language=language)
            return {
                'detected': result.get('is_confused', False),
                'reason': result.get('reason', ''),
            }
        except Exception as e:
            log.debug(f"Confusion detection failed: {e}")
            return {'detected': False, 'reason': ''}
    
    def _build_qa_prompt(
        self,
        question: str,
        rag_results: List[Dict],
        is_confused: bool,
        language: str,
        subject: str,
        ctx: SessionContext,
    ) -> str:
        """Build LLM prompt for QA.
        
        Args:
            question: Student question
            rag_results: Retrieved documents
            is_confused: Whether confusion detected
            language: Language code
            subject: Subject area
            ctx: Session context
            
        Returns:
            str: LLM prompt
        """
        context_doc = ""
        if rag_results:
            context_doc = "\n".join(r.get('content', '') for r in rag_results[:3])
        
        confusion_note = ""
        if is_confused:
            confusion_note = "\n⚠️ L'étudiant semble confus. Sois particulièrement clair et pédagogue."
        
        slide_context = ""
        if ctx.slide:
            slide_context = f"\nDe la section actuelle: {ctx.slide.section_title}"
        
        prompt = f"""Tu es un professeur IA patient et pédagogue.
Réponds à la question suivante en {language}, dans le contexte de {subject}.{confusion_note}{slide_context}

Documents pertinents:
{context_doc}

Question de l'étudiant:
{question}

Réponse claire et adaptée:"""
        
        return prompt
    
    def _build_quiz_prompt(
        self,
        rag_results: List[Dict],
        subject: str,
        language: str,
        level: str,
    ) -> str:
        """Build LLM prompt for quiz generation.
        
        Args:
            rag_results: Retrieved documents
            subject: Subject area
            language: Language code
            level: Student level
            
        Returns:
            str: LLM prompt
        """
        context = ""
        if rag_results:
            context = "\n".join(r.get('content', '') for r in rag_results[:2])
        
        prompt = f"""Génère une question de quiz pertinente et intéressante.

Niveau: {level}
Matière: {subject}
Langue: {language}

Contexte pédagogique:
{context}

Question de quiz:"""
        
        return prompt
    
    async def _log_learning_turn(
        self,
        session_id: str,
        question: str,
        answer: str,
        ctx: SessionContext,
        language: str,
        subject: str,
        metrics: Dict[str, Any],
    ) -> None:
        """Log learning interaction to analytics.
        
        Args:
            session_id: Session identifier
            question: Question text
            answer: Answer text
            ctx: Session context
            language: Language code
            subject: Subject area
            metrics: Interaction metrics
        """
        try:
            self.analytics.record_learning_turn(
                session_id=session_id,
                question_text=question,
                answer_text=answer,
                language=language,
                subject=subject,
                course_id=ctx.slide.course_id if ctx.slide else None,
                confusion_detected=metrics.get('confusion_detected', False),
                confusion_reason=metrics.get('confusion_reason', ''),
                stt_time_ms=0.0,  # Not applicable for text input
                llm_time_ms=metrics.get('llm_time_ms', 0.0),
                tts_time_ms=metrics.get('tts_time_ms', 0.0),
                total_time_ms=sum([
                    metrics.get(k, 0.0) for k in ['rag_time_ms', 'llm_time_ms', 'tts_time_ms']
                ]),
                rag_chunks=metrics.get('rag_chunks', 0),
                rag_score=metrics.get('rag_score', 0.0),
                student_level=ctx.student_profile.level if ctx.student_profile else "",
                chapter_index=ctx.slide.chapter_index if ctx.slide else None,
                section_index=ctx.slide.section_index if ctx.slide else None,
            )
        except Exception as e:
            log.error(f"Failed to log learning turn: {e}")


__all__ = [
    "QAService",
]
