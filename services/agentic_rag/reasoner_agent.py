"""Stage 4 reasoner for the agentic RAG pipeline."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from typing import Any, Dict, Iterable, List, Optional

from services.agentic_rag.advanced_prompts import build_aggregation_prompt, build_reasoning_prompt

log = logging.getLogger("SmartTeacher.ReasonerAgent")


class ReasonerAgent:
    """Generate a pedagogical answer from retrieved chunks."""

    def __init__(self, llm, short_term_memory=None, long_term_memory=None):
        self.llm = llm
        self.short_term_memory = short_term_memory
        self.long_term_memory = long_term_memory

    async def reason(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        history: Optional[List[Any]] = None,
        profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        profile = profile or {}
        history = history or []
        language = profile.get("language") or profile.get("lang") or "fr"
        level = profile.get("level") or profile.get("current_level") or "intermediate"

        context = self._build_context(chunks)
        conversation_history = self._format_history(history)
        short_term_context = self.short_term_memory.get_context() if self.short_term_memory else ""
        long_term_context = await self._load_long_term_context(profile)
        sub_queries = self._split_into_subqueries(query)

        if len(sub_queries) > 1:
            sub_answers = await asyncio.gather(
                *[
                    self._answer_subquery(
                        sub_query,
                        context=context,
                        language=language,
                        level=level,
                        conversation_history=conversation_history,
                        short_term_context=short_term_context,
                        long_term_context=long_term_context,
                    )
                    for sub_query in sub_queries
                ]
            )
            answer = await self._aggregate_answers(query, sub_answers, language, level)
        else:
            answer = await self._answer_subquery(
                query,
                context=context,
                language=language,
                level=level,
                conversation_history=conversation_history,
                short_term_context=short_term_context,
                long_term_context=long_term_context,
            )

        if self.short_term_memory is not None:
            try:
                self.short_term_memory.add_exchange(query, answer)
            except Exception as exc:
                log.debug("Short-term memory update skipped: %s", exc)

        return answer

    async def _answer_subquery(
        self,
        query: str,
        context: str,
        language: str,
        level: str,
        conversation_history: str,
        short_term_context: str,
        long_term_context: str,
    ) -> str:
        system_prompt = build_reasoning_prompt(
            query=query,
            context=context,
            language=language,
            level=level,
            memory=short_term_context,
            history=conversation_history,
            long_term_context=long_term_context,
            sub_queries=[query],
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "Provide a clear answer grounded in the supplied context.",
            },
        ]
        return await self._call_llm(messages, temperature=0.7, max_tokens=320)

    async def _aggregate_answers(self, query: str, answers: Iterable[str], language: str, level: str) -> str:
        answer_list = [answer.strip() for answer in answers if answer and answer.strip()]
        if not answer_list:
            return "I could not generate a reliable answer from the available context."

        if len(answer_list) == 1:
            return answer_list[0]

        system_prompt = build_aggregation_prompt(query=query, answers=answer_list, language=language, level=level)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Merge the sub-answers into one response."},
        ]
        aggregated = await self._call_llm(messages, temperature=0.5, max_tokens=360)
        return aggregated or "\n\n".join(answer_list)

    async def _call_llm(self, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> str:
        response = await self.llm.agenerate(messages, temperature=temperature, max_tokens=max_tokens)
        content = getattr(response, "content", response)
        return str(content).strip()

    def _build_context(self, chunks: List[Dict[str, Any]]) -> str:
        if not chunks:
            return ""

        parts = []
        for chunk in chunks[:5]:
            if isinstance(chunk, dict):
                content = chunk.get("content") or chunk.get("page_content") or str(chunk)
                source = chunk.get("source") or chunk.get("metadata", {}).get("source") or "unknown"
            else:
                content = getattr(chunk, "page_content", str(chunk))
                source = getattr(chunk, "metadata", {}).get("source", "unknown")
            parts.append(f"[Source: {source}]\n{content}")

        return "\n\n".join(parts)

    def _format_history(self, history: List[Any]) -> str:
        if not history:
            return ""

        formatted = []
        for item in history[-5:]:
            if isinstance(item, dict):
                question = item.get("query") or item.get("question") or item.get("student_query") or ""
                answer = item.get("answer") or item.get("response") or item.get("ai_answer") or ""
            else:
                question = getattr(item, "student_query", getattr(item, "query", ""))
                answer = getattr(item, "ai_answer", getattr(item, "answer", ""))
            if question or answer:
                formatted.append(f"Q: {question}\nA: {answer}")
        return "\n\n".join(formatted)

    async def _load_long_term_context(self, profile: Dict[str, Any]) -> str:
        if not self.long_term_memory:
            return ""

        student_id = profile.get("student_id") or profile.get("studentId")
        course_id = profile.get("course_id") or profile.get("courseId")
        if not student_id or not course_id:
            return ""

        try:
            context = self.long_term_memory.get_session_context(student_id, course_id)
            if inspect.isawaitable(context):
                context = await context
            if not context:
                return ""
            if isinstance(context, dict):
                confusion_topics = ", ".join(context.get("confusion_topics", []))
                recent_topics = ", ".join(context.get("recent_topics", []))
                learning_level = context.get("learning_level", "unknown")
                return (
                    f"learning_level={learning_level}; "
                    f"confusion_topics={confusion_topics or 'none'}; "
                    f"recent_topics={recent_topics or 'none'}"
                )
            return str(context)
        except Exception as exc:
            log.debug("Long-term context unavailable: %s", exc)
            return ""

    def _split_into_subqueries(self, query: str) -> List[str]:
        normalized = query.strip()
        if len(normalized.split()) < 12:
            return [normalized]

        parts = re.split(r"\s+(?:and then|and|then|plus|also|or)\s+", normalized, flags=re.IGNORECASE)
        sub_queries = [part.strip(" ?.,;:") for part in parts if len(part.split()) >= 3]
        unique_sub_queries = []
        for part in sub_queries:
            if part not in unique_sub_queries:
                unique_sub_queries.append(part)
        return unique_sub_queries[:3] if len(unique_sub_queries) > 1 else [normalized]
