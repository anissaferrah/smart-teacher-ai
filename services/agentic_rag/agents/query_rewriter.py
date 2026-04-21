"""Query Rewriter Agent - Improves vague student questions."""

import logging
from typing import Dict, Any, Optional
from infrastructure.logging import get_logger

log = get_logger(__name__)


async def query_rewriter_node(
    state: "AgenticRAGState",
    llm,
) -> Dict[str, Any]:
    """Rewrite vague or short queries for better RAG retrieval.
    
    Args:
        state: Current workflow state
        llm: Language model instance
        
    Returns:
        Dict with updated rewritten_query and query_intent
    """
    query = state.query
    
    # Check if query needs rewriting
    if len(query) < 10 or _is_generic_query(query):
        log.info(f"🔄 Generic query detected: '{query}' - attempting rewrite")
        
        # Build rewrite prompt
        context = ""
        if state.history and len(state.history) > 0:
            context = "\n".join([
                f"{turn.get('role', 'user')}: {turn.get('content', '')}"
                for turn in state.history[-3:]
            ])
        
        prompt = f"""You are a teacher assistant improving student questions for clarity.

Student asked: "{query}"

{f"Conversation context (last 3 turns):\n{context}" if context else ""}

Rewrite the student's question to be more specific and clear for a knowledge base search.
Keep the original intent, but make it more explicit.

Return ONLY the rewritten question (no preamble)."""
        
        try:
            rewritten = await llm.generate(prompt, max_tokens=100, temperature=0.3)
            rewritten = rewritten.strip()
            state.rewritten_query = rewritten
            state.query_intent = _extract_intent(rewritten)
            log.info(f"✅ Rewrote: '{query}' → '{rewritten}'")
        except Exception as e:
            log.error(f"Query rewriting failed: {e} - using original")
            state.rewritten_query = query
            state.query_intent = _extract_intent(query)
    else:
        # Query is sufficiently specific
        state.rewritten_query = query
        state.query_intent = _extract_intent(query)
        log.debug(f"✓ Query specific enough: '{query}'")
    
    # Record in metadata
    state.agent_metadata["query_rewriter"] = {
        "original_query": query,
        "rewritten_query": state.rewritten_query,
        "intent": state.query_intent,
    }
    
    return {
        "rewritten_query": state.rewritten_query,
        "query_intent": state.query_intent,
        "agent_metadata": state.agent_metadata,
    }


def _is_generic_query(query: str) -> bool:
    """Check if query is too generic."""
    generic_patterns = [
        "explain", "can you", "help me", "tell me",
        "what is", "how to", "expliquer", "aide",
        "comprends pas", "c'est quoi", "comment",
        "peux tu", "pourquoi", "why", "please",
    ]
    query_lower = query.lower()
    return any(pattern in query_lower for pattern in generic_patterns) and len(query) < 20


def _extract_intent(query: str) -> str:
    """Extract main intent from query."""
    query_lower = query.lower()
    
    if any(w in query_lower for w in ["explain", "expliquer", "definition", "c'est quoi", "what is"]):
        return "explanation"
    elif any(w in query_lower for w in ["how", "comment", "procedure", "steps", "étapes"]):
        return "procedure"
    elif any(w in query_lower for w in ["why", "pourquoi", "reason", "raison"]):
        return "reasoning"
    elif any(w in query_lower for w in ["example", "exemple", "instance"]):
        return "example"
    else:
        return "general_question"


__all__ = [
    "query_rewriter_node",
]
