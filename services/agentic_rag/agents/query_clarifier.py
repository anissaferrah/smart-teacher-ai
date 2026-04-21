"""Query Clarifier Agent - Detects vague/ambiguous questions."""

import logging
from typing import Dict, Any, Optional
from infrastructure.logging import get_logger

log = get_logger(__name__)


async def query_clarifier_node(
    state: "AgenticRAGState",
    llm,
) -> Dict[str, Any]:
    """Detect if question needs clarification.
    
    Args:
        state: Current workflow state
        llm: Language model instance
        
    Returns:
        Dict with needs_clarification flag and clarification_question
    """
    query = state.rewritten_query or state.query
    
    # Check for duplicate of recent questions
    if state.history and len(state.history) > 0:
        recent_questions = [
            turn.get("content", "")
            for turn in state.history[-5:]
            if turn.get("role") == "user"
        ]
        
        # Simple similarity check
        from difflib import SequenceMatcher
        
        for recent_q in recent_questions:
            similarity = SequenceMatcher(None, query.lower(), recent_q.lower()).ratio()
            if similarity > 0.75:
                log.info(f"⚠️  Duplicate question detected (similarity: {similarity:.2f})")
                state.needs_clarification = True
                state.clarification_question = "You asked something very similar recently. Are you trying to clarify a previous concept?"
                return {
                    "needs_clarification": True,
                    "clarification_question": state.clarification_question,
                }
    
    # Check for extremely short or vague queries (even after rewrite)
    if len(query) < 5:
        log.info(f"⚠️  Query too short: '{query}'")
        state.needs_clarification = True
        state.clarification_question = "Could you provide more details about what you'd like to learn?"
        return {
            "needs_clarification": True,
            "clarification_question": state.clarification_question,
        }
    
    # Use LLM to detect ambiguity
    try:
        ambiguity_check_prompt = f"""Is this student question clear and unambiguous? Answer only "yes" or "no".

Question: "{query}"

Answer:"""
        
        response = await llm.generate(ambiguity_check_prompt, max_tokens=5, temperature=0.0)
        response_lower = response.lower().strip()
        
        if "no" in response_lower:
            log.info(f"🤔 Ambiguous question detected: '{query}'")
            state.needs_clarification = True
            
            # Generate clarification question
            clarify_prompt = f"""The student asked a somewhat ambiguous question. Generate a brief clarification question.

Original question: "{query}"

Clarification question (be brief, max 20 words):"""
            
            state.clarification_question = await llm.generate(clarify_prompt, max_tokens=30, temperature=0.6)
        else:
            state.needs_clarification = False
            log.debug(f"✓ Query is clear: '{query}'")
    
    except Exception as e:
        log.error(f"Clarity check failed: {e} - assuming query is clear")
        state.needs_clarification = False
    
    # Record metadata
    state.agent_metadata["query_clarifier"] = {
        "needs_clarification": state.needs_clarification,
        "clarification_question": state.clarification_question,
    }
    
    return {
        "needs_clarification": state.needs_clarification,
        "clarification_question": state.clarification_question,
        "agent_metadata": state.agent_metadata,
    }


__all__ = [
    "query_clarifier_node",
]
