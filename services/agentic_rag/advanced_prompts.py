"""Advanced prompts for agentic RAG workflows."""

from __future__ import annotations

from textwrap import dedent
from typing import Iterable


COMPLEX_REASONING_PROMPT = dedent(
    """
    You are an expert tutor.

    Rules:
    - Answer in {language}.
    - Match the student's level: {level}.
    - Stay grounded in the provided course context.
    - Explain step by step.
    - If context is weak, say what is missing instead of guessing.

    Example:
    Q: Explain photosynthesis
    A: Photosynthesis has two main stages. The light reactions capture energy... 

    Course context:
    {context}

    Conversation memory:
    {memory}

    Recent history:
    {history}

    Long-term context:
    {long_term_context}

    Optional sub-questions:
    {sub_queries}

    Question:
    {query}
    """
).strip()


AGGREGATION_PROMPT = dedent(
    """
    You are an answer aggregator.

    Combine the sub-answers into one coherent response.
    - Remove repeated ideas.
    - Keep a logical flow.
    - Preserve the learning level: {level}.
    - Answer in {language}.

    Original question:
    {query}

    Sub-answers:
    {answers}
    """
).strip()


FALLBACK_PROMPTS = {
    "retrieval_failed": {
        "fr": "Je n'ai pas trouve d'information pertinente dans le cours. Pouvez-vous reformuler votre question ?",
        "en": "I could not find relevant information in the course material. Could you rephrase your question?",
    },
    "low_confidence": {
        "fr": "La reponse semble incertaine. Je prefere verifier avec plus de contexte.",
        "en": "The answer seems uncertain. I would rather verify it with more context.",
    },
    "toxic_content": {
        "fr": "Je ne peux pas aider sur ce sujet. Essayez un autre angle d'etude.",
        "en": "I cannot help with this topic. Please try a different study angle.",
    },
    "empty_context": {
        "fr": "Aucun contexte n'a ete indexe pour ce document.",
        "en": "No context has been indexed for this document.",
    },
}


ROLE_PROMPTS = {
    "tutor": {
        "fr": "You are a patient tutor who explains concepts clearly and concretely.",
        "en": "You are a patient tutor who explains concepts clearly and concretely.",
    },
    "reviewer": {
        "fr": "You are a strict reviewer who checks accuracy and completeness.",
        "en": "You are a strict reviewer who checks accuracy and completeness.",
    },
}


def build_reasoning_prompt(
    query: str,
    context: str = "",
    language: str = "fr",
    level: str = "intermediate",
    memory: str = "",
    history: str = "",
    long_term_context: str = "",
    sub_queries: Iterable[str] | None = None,
) -> str:
    sub_queries_text = "\n".join(f"- {item}" for item in (sub_queries or [])) or "None"
    return COMPLEX_REASONING_PROMPT.format(
        query=query,
        context=context or "No retrieved context available.",
        language=language,
        level=level,
        memory=memory or "None",
        history=history or "None",
        long_term_context=long_term_context or "None",
        sub_queries=sub_queries_text,
    )


def build_aggregation_prompt(
    query: str,
    answers: Iterable[str],
    language: str = "fr",
    level: str = "intermediate",
) -> str:
    answers_text = "\n".join(f"{index + 1}. {answer}" for index, answer in enumerate(answers))
    return AGGREGATION_PROMPT.format(
        query=query,
        answers=answers_text or "No answers available.",
        language=language,
        level=level,
    )


def get_fallback_prompt(kind: str, language: str = "fr") -> str:
    prompt_group = FALLBACK_PROMPTS.get(kind, FALLBACK_PROMPTS["retrieval_failed"])
    return prompt_group.get(language, prompt_group["en"])
