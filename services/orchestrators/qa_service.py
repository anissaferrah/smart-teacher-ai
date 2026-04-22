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
import hashlib
import logging
import re
import time
from typing import Optional, Dict, Any, List, Tuple, Callable
from datetime import datetime
from difflib import SequenceMatcher

from domain.session_state import SessionContext, DialogState
from infrastructure.config import settings
from infrastructure.logging import get_logger
from services.analytics.clickhouse_events import get_analytics_sink
from config import Config as _Cfg

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
        self._qa_cache: Dict[str, Dict[str, Any]] = {}
        self._qa_cache_order: List[str] = []
        self._qa_cache_max_entries = 300

    def _resolve_rag_state(self) -> Dict[str, Any]:
        """Expose the effective RAG mode used for this QA turn."""
        rag_enabled = bool(settings.rag.enabled and self.rag)
        rag_class = self.rag.__class__.__name__ if self.rag else "None"
        rag_module = self.rag.__class__.__module__ if self.rag else ""

        is_agentic = "agentic" in rag_module.lower() or "agentic" in rag_class.lower()
        if not is_agentic and self.rag:
            # Heuristic for future agentic adapters exposing richer orchestration hooks.
            is_agentic = any(
                hasattr(self.rag, attr)
                for attr in ("run_pipeline", "orchestrate", "process_query", "execute")
            )

        supported_stages = {
            "analyze_question": True,
            "reformulate_query": is_agentic,
            "retrieve_documents": rag_enabled,
            "reason": True,
            "verify_answer": is_agentic,
            "improve_answer": is_agentic,
        }

        return {
            "enabled": rag_enabled,
            "mode": "agentic" if is_agentic else "classic",
            "rag_class": rag_class,
            "rag_module": rag_module,
            "supported_stages": supported_stages,
        }

    @staticmethod
    def _normalize_question(text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        normalized = re.sub(r"[^\w\s]", "", normalized)
        return normalized

    @staticmethod
    def _slide_context_key(ctx: SessionContext) -> str:
        if not ctx.slide:
            return "global"
        return f"{ctx.slide.course_id}:{ctx.slide.chapter_index}:{ctx.slide.section_index}"

    def _question_context_prefix(
        self,
        session_id: str,
        language: str,
        subject: str,
        ctx: SessionContext,
    ) -> str:
        return "|".join([
            session_id,
            (language or "").strip().lower(),
            (subject or "").strip().lower(),
            self._slide_context_key(ctx),
        ])

    def _question_cache_key(self, prefix: str, normalized_question: str) -> str:
        digest = hashlib.sha1(normalized_question.encode("utf-8")).hexdigest()
        return f"{prefix}|{digest}"

    def _find_cached_answer(
        self,
        prefix: str,
        normalized_question: str,
    ) -> Optional[Dict[str, Any]]:
        exact_key = self._question_cache_key(prefix, normalized_question)
        if exact_key in self._qa_cache:
            return self._qa_cache[exact_key]

        # Fuzzy fallback for near-duplicates in the same session+slide context.
        best_entry = None
        best_similarity = 0.0
        for cache_key, entry in self._qa_cache.items():
            if not cache_key.startswith(prefix + "|"):
                continue
            candidate_question = entry.get("normalized_question", "")
            if not candidate_question:
                continue
            similarity = SequenceMatcher(None, normalized_question, candidate_question).ratio()
            if similarity > best_similarity:
                best_similarity = similarity
                best_entry = entry

        if best_entry and best_similarity >= 0.92:
            return best_entry
        return None

    def _store_cached_answer(
        self,
        prefix: str,
        normalized_question: str,
        answer_text: str,
        audio_bytes: Optional[bytes],
    ) -> None:
        cache_key = self._question_cache_key(prefix, normalized_question)
        self._qa_cache[cache_key] = {
            "normalized_question": normalized_question,
            "answer_text": answer_text,
            "audio_bytes": audio_bytes,
            "cached_at": datetime.utcnow().isoformat(),
        }
        self._qa_cache_order.append(cache_key)

        while len(self._qa_cache_order) > self._qa_cache_max_entries:
            oldest_key = self._qa_cache_order.pop(0)
            self._qa_cache.pop(oldest_key, None)
    
    async def process_text_question(
        self,
        session_id: str,
        question_text: str,
        ctx: SessionContext,
        language: str,
        subject: str,
        history: Optional[List[Dict[str, Any]]] = None,
        on_step: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_audio_chunk: Optional[Callable[[Optional[bytes], Optional[str], bool], Any]] = None,
    ) -> Tuple[str, Optional[bytes], Dict[str, Any]]:
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
            'prompt_time_ms': 0.0,
            'confusion_time_ms': 0.0,
            'confusion_detected': False,
            'confusion_reason': '',
            'llm_time_ms': 0.0,
            'tts_time_ms': 0.0,
            'log_time_ms': 0.0,
            'cache_hit': False,
        }
        reasoning_trace: List[Dict[str, Any]] = []
        history = history or []
        rag_state = self._resolve_rag_state()
        metrics['agentic_rag_state'] = rag_state

        normalized_question = self._normalize_question(question_text)
        cache_prefix = self._question_context_prefix(session_id, language, subject, ctx)
        cached_answer = self._find_cached_answer(cache_prefix, normalized_question)
        if cached_answer:
            metrics['cache_hit'] = True
            await add_trace_step(
                step=1,
                key='retrieval',
                title='Recherche documentaire',
                state=DialogState.PROCESSING.value,
                status='done',
                summary='Réponse récupérée depuis le cache',
                duration_ms=0.0,
                details={
                    'cache_hit': True,
                    'chunks': 0,
                    'rag_enabled': bool(settings.rag.enabled and self.rag),
                    'top_score': 0.0,
                },
            )
            metrics['reasoning_trace'] = reasoning_trace
            metrics['system_state'] = DialogState.IDLE.value
            metrics['current_stage'] = 'completed'
            return (
                str(cached_answer.get('answer_text') or ''),
                cached_answer.get('audio_bytes'),
                metrics,
            )

        async def add_trace_step(
            step: int,
            key: str,
            title: str,
            state: str,
            status: str,
            summary: str,
            duration_ms: float,
            confidence: Optional[float] = None,
            details: Optional[Dict[str, Any]] = None,
        ) -> None:
            payload = {
                'step': step,
                'key': key,
                'title': title,
                'state': state,
                'status': status,
                'summary': summary,
                'duration_ms': round(duration_ms, 1),
            }
            if confidence is not None:
                payload['confidence'] = round(float(confidence), 3)
            if details:
                payload['details'] = details

            existing_index = next(
                (
                    index
                    for index, existing in enumerate(reasoning_trace)
                    if existing.get('step') == step or existing.get('key') == key
                ),
                None,
            )

            if existing_index is not None:
                reasoning_trace[existing_index] = payload
            else:
                reasoning_trace.append(payload)

            if on_step:
                try:
                    result = on_step(payload)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as step_exc:
                    log.debug(f"QA step callback failed: {step_exc}")

        async def emit_audio_chunk(
            audio_bytes: Optional[bytes],
            mime_type: Optional[str],
            is_final: bool = False,
        ) -> None:
            if not on_audio_chunk:
                return

            try:
                result = on_audio_chunk(audio_bytes, mime_type, is_final)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as audio_exc:
                log.debug(f"QA audio chunk callback failed: {audio_exc}")

        await add_trace_step(
            step=0,
            key='agentic_rag_state',
            title='État du pipeline RAG',
            state=DialogState.PROCESSING.value,
            status='done',
            summary=(
                f"Mode RAG: {rag_state['mode']} ({rag_state['rag_class']})"
                if rag_state['enabled']
                else 'RAG désactivé pour cette question'
            ),
            duration_ms=0.0,
            details=rag_state,
        )
        
        try:
            if _Cfg.RAG_MODE == "agentic":
                try:
                    from services.app_state import agentic_rag_orchestrator

                    if agentic_rag_orchestrator is not None:
                        _result = await agentic_rag_orchestrator.answer_question(
                            query=question_text,
                            course_id=ctx.slide.course_id if ctx.slide else None,
                            history=history,
                            language=language,
                            student_profile={
                                "level": ctx.student_profile.level if ctx.student_profile else "lycée",
                                "language": language,
                            },
                        )

                        _answer = _result.get("answer", "")

                        _audio, _, _eng, _voice, _mime = await self.voice.generate_audio_async(
                            _answer,
                            language=language,
                        )

                        if _audio and on_audio_chunk:
                            await on_audio_chunk(_audio, _mime, False)

                        metrics["llm_time_ms"] = (
                            _result.get("metrics", {}).get("total_time", 0) * 1000
                        )

                        metrics["reasoning_trace"] = _result.get(
                            "reasoning", {}
                        ).get("steps", [])

                        metrics["agentic_rag_state"] = {
                            "enabled": True,
                            "mode": "agentic",
                        }

                        return _answer, _audio, metrics

                except Exception as _aex:
                    log.warning(
                        f"Agentic RAG failed, falling back to classic: {_aex}"
                    )
            # Step 1: RAG retrieval
            rag_start = time.time()
            
            rag_results = []
            rag_enabled = bool(settings.rag.enabled and self.rag)
            if rag_enabled:
                await add_trace_step(
                    step=1,
                    key='retrieval',
                    title='Recherche documentaire',
                    state=DialogState.PROCESSING.value,
                    status='running',
                    summary='Recherche documentaire en cours…',
                    duration_ms=0.0,
                    details={
                        'rag_enabled': rag_enabled,
                    },
                )

                rag_results = await self.rag.retrieve(
                    question_text,
                    course_id=ctx.slide.course_id if ctx.slide else None,
                    top_k=settings.rag.num_results,
                )
                # ✅ Normalize RAG results to (Document, score, source) tuples
                try:
                    from langchain_core.documents import Document as _LCDoc
                except Exception:
                    _LCDoc = None

                _normalized = []
                for _item in rag_results:
                    if isinstance(_item, dict):
                        _doc = _item.get("document")
                        if _doc is None and _LCDoc is not None:
                            _doc = _LCDoc(
                                page_content=_item.get("content", ""),
                                metadata=_item.get("metadata", {})
                            )
                        _score = float(_item.get("score", 0.5) or 0.5)
                        _src = _item.get("source", "")
                        _normalized.append((_doc, _score, _src))
                    elif isinstance(_item, tuple):
                        _normalized.append(_item)
                    else:
                        _normalized.append((_item, 0.5, ""))
                rag_results = _normalized
            
            metrics['rag_time_ms'] = (time.time() - rag_start) * 1000
            metrics['rag_chunks'] = len(rag_results)
            if rag_results:
                metrics['rag_score'] = sum(
                    (
                        float(r.get('score', 0.0))
                        if isinstance(r, dict)
                        else float(r[1]) if isinstance(r, tuple) and len(r) > 1 else 0.0
                    )
                    for r in rag_results
                ) / len(rag_results)
            await add_trace_step(
                step=1,
                key='retrieval',
                title='Recherche documentaire',
                state=DialogState.PROCESSING.value,
                status='done' if rag_enabled else 'skipped',
                summary=(
                    f"{len(rag_results)} passages récupérés"
                    if rag_enabled
                    else 'Recherche RAG désactivée'
                ),
                duration_ms=metrics['rag_time_ms'],
                confidence=metrics['rag_score'] if rag_results else 0.0,
                details={
                    'chunks': len(rag_results),
                    'rag_enabled': rag_enabled,
                    'top_score': round(metrics['rag_score'], 3) if rag_results else 0.0,
                },
            )
            
            # Step 2: Detect confusion
            confusion_start = time.time()
            if settings.confusion.enabled:
                await add_trace_step(
                    step=2,
                    key='confusion_detection',
                    title='Détection de confusion',
                    state=DialogState.PROCESSING.value,
                    status='running',
                    summary='Détection de confusion en cours…',
                    duration_ms=0.0,
                    details={
                        'language': language,
                    },
                )

            confusion_result = await self._detect_confusion(question_text, language)
            metrics['confusion_time_ms'] = (time.time() - confusion_start) * 1000
            metrics['confusion_detected'] = confusion_result['detected']
            metrics['confusion_reason'] = confusion_result['reason']
            await add_trace_step(
                step=2,
                key='confusion_detection',
                title='Détection de confusion',
                state=DialogState.PROCESSING.value,
                status='done' if settings.confusion.enabled else 'skipped',
                summary=(
                    'Confusion détectée' if confusion_result['detected'] else 'Aucune confusion détectée'
                ) if settings.confusion.enabled else 'Détection de confusion désactivée',
                duration_ms=metrics['confusion_time_ms'],
                confidence=0.85 if confusion_result['detected'] else 1.0,
                details={
                    'detected': confusion_result['detected'],
                    'reason': confusion_result['reason'],
                    'language': language,
                },
            )
            
            # Step 3: Build LLM prompt
            prompt_start = time.time()
            await add_trace_step(
                step=3,
                key='prompt_build',
                title='Construction du prompt',
                state=DialogState.PROCESSING.value,
                status='running',
                summary='Construction du prompt en cours…',
                duration_ms=0.0,
                details={
                    'subject': subject,
                    'language': language,
                },
            )

            prompt = self._build_qa_prompt(
                question_text,
                rag_results,
                confusion_result['detected'],
                language,
                subject,
                ctx,
            )
            metrics['prompt_time_ms'] = (time.time() - prompt_start) * 1000
            await add_trace_step(
                step=3,
                key='prompt_build',
                title='Construction du prompt',
                state=DialogState.PROCESSING.value,
                status='done',
                summary='Prompt pédagogique construit',
                duration_ms=metrics['prompt_time_ms'],
                details={
                    'subject': subject,
                    'language': language,
                    'context_length': len(prompt),
                },
            )
            
            # Step 4 + 5: generate the answer and stream TTS clips.
            llm_start = time.time()
            await add_trace_step(
                step=4,
                key='answer_generation',
                title='Génération de la réponse',
                state=DialogState.PROCESSING.value,
                status='running',
                summary='Réponse en cours…',
                duration_ms=0.0,
                details={
                    'question_length': len(question_text),
                },
            )

            await add_trace_step(
                step=5,
                key='tts_synthesis',
                title='Synthèse vocale',
                state=DialogState.RESPONDING.value,
                status='running',
                summary='Synthèse vocale en cours…',
                duration_ms=0.0,
                details={
                    'language': language,
                },
            )

            full_response = ""
            final_audio_bytes: Optional[bytes] = None
            audio_clip_count = 0
            tts_engine = "none"
            tts_voice = "none"

            streaming_supported = bool(
                rag_enabled and rag_results and self.rag and hasattr(self.rag, "generate_final_answer_stream")
            )

            stream_input_docs = []
            for item in rag_results:
                if isinstance(item, dict):
                    doc = item.get("document")
                    if doc is not None:
                        stream_input_docs.append(doc)
                elif isinstance(item, tuple) and item:
                    stream_input_docs.append(item[0])
                else:
                    stream_input_docs.append(item)

            streaming_supported = streaming_supported and bool(stream_input_docs)

            if streaming_supported:
                try:
                    student_level = ctx.student_profile.level if ctx.student_profile else "université"
                    async for sentence, full_so_far in self.rag.generate_final_answer_stream(
                        stream_input_docs,
                        question=question_text,
                        history=history,
                        language=language,
                        student_level=student_level,
                        current_chapter_title=ctx.slide.chapter_title if ctx.slide else "",
                        current_section_title=ctx.slide.section_title if ctx.slide else "",
                    ):
                        full_response = full_so_far or full_response
                        cleaned_sentence = str(sentence or "").strip()
                        if not cleaned_sentence:
                            continue

                        clip_start = time.time()
                        audio_bytes, _, tts_engine, tts_voice, mime = await self.voice.generate_audio_async(
                            cleaned_sentence,
                            language=language,
                        )
                        metrics['tts_time_ms'] += (time.time() - clip_start) * 1000

                        if audio_bytes:
                            final_audio_bytes = audio_bytes
                            audio_clip_count += 1
                            await emit_audio_chunk(audio_bytes, mime, False)

                    full_response = full_response.strip()
                except Exception as stream_exc:
                    log.warning(f"Streaming answer failed, fallback direct synthesis: {stream_exc}")
                    streaming_supported = False

            if not streaming_supported:
                answer_text = await self.llm.generate(prompt, temperature=0.7, max_tokens=400)
                full_response = str(answer_text or "").strip()

                clip_start = time.time()
                audio_bytes, _, tts_engine, tts_voice, mime = await self.voice.generate_audio_async(
                    full_response,
                    language=language,
                )
                metrics['tts_time_ms'] += (time.time() - clip_start) * 1000

                if audio_bytes:
                    final_audio_bytes = audio_bytes
                    audio_clip_count = 1
                    await emit_audio_chunk(audio_bytes, mime, False)

            if full_response and audio_clip_count == 0:
                clip_start = time.time()
                audio_bytes, _, tts_engine, tts_voice, mime = await self.voice.generate_audio_async(
                    full_response,
                    language=language,
                )
                metrics['tts_time_ms'] += (time.time() - clip_start) * 1000

                if audio_bytes:
                    final_audio_bytes = audio_bytes
                    audio_clip_count = 1
                    await emit_audio_chunk(audio_bytes, mime, False)

            metrics['llm_time_ms'] = (time.time() - llm_start) * 1000

            await add_trace_step(
                step=4,
                key='answer_generation',
                title='Génération de la réponse',
                state=DialogState.RESPONDING.value,
                status='done',
                summary=f'Réponse générée ({len(full_response)} caractères)',
                duration_ms=metrics['llm_time_ms'],
                confidence=0.8,
                details={
                    'answer_preview': full_response[:140],
                    'answer_length': len(full_response),
                    'audio_clips': audio_clip_count,
                },
            )

            await add_trace_step(
                step=5,
                key='tts_synthesis',
                title='Synthèse vocale',
                state=DialogState.RESPONDING.value,
                status='done',
                summary=(
                    f'Audio synthétisé ({len(final_audio_bytes)} octets)'
                    if final_audio_bytes
                    else 'Synthèse vocale terminée'
                ),
                duration_ms=metrics['tts_time_ms'],
                details={
                    'audio_bytes': len(final_audio_bytes) if final_audio_bytes else 0,
                    'audio_clips': audio_clip_count,
                    'tts_engine': tts_engine,
                    'tts_voice': tts_voice,
                },
            )
            
            # Step 6: Log to analytics
            log_start = time.time()
            await add_trace_step(
                step=6,
                key='analytics_logging',
                title='Journalisation',
                state=DialogState.IDLE.value,
                status='running',
                summary="Enregistrement de l'interaction…",
                duration_ms=0.0,
                details={
                    'session_id': session_id,
                    'question_length': len(question_text),
                },
            )

            await self._log_learning_turn(
                session_id, question_text, full_response, ctx, language, subject, metrics
            )
            metrics['log_time_ms'] = (time.time() - log_start) * 1000
            await add_trace_step(
                step=6,
                key='analytics_logging',
                title='Journalisation',
                state=DialogState.IDLE.value,
                status='done',
                summary='Interaction enregistrée',
                duration_ms=metrics['log_time_ms'],
                details={
                    'session_id': session_id,
                    'question_length': len(question_text),
                },
            )

            metrics['reasoning_trace'] = reasoning_trace
            metrics['system_state'] = DialogState.IDLE.value
            metrics['current_stage'] = 'completed'

            self._store_cached_answer(
                cache_prefix,
                normalized_question,
                full_response,
                final_audio_bytes,
            )
            
            return full_response, final_audio_bytes, metrics
        
        except Exception as e:
            log.error(f"QA processing failed: {e}")
            metrics['reasoning_trace'] = reasoning_trace
            metrics['system_state'] = DialogState.PROCESSING.value if reasoning_trace else DialogState.IDLE.value
            metrics['current_stage'] = 'error'
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
            detected = bool(result.get('is_confused', False))
            reason = str(result.get('reason', '') if detected else '')
            return {
                'detected': detected,
                'reason': reason,
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
