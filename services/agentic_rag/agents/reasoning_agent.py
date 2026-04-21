"""Reasoning Agent - Generate pedagogically sound answers."""

import logging
import asyncio
from typing import Dict, Any
from infrastructure.logging import get_logger

log = get_logger(__name__)


async def reasoning_agent_node(
    state: "AgenticRAGState",
    llm,
) -> Dict[str, Any]:
    """Generate pedagogically sound answer using retrieved context.
    
    Args:
        state: Current workflow state
        llm: Language model instance
        
    Returns:
        Dict with draft_answer and reasoning_confidence
    """
    query = state.rewritten_query or state.query
    
    log.info(f"🧠 Reasoning about: '{query}'")
    
    try:
        # Build context
        context_text = ""
        if state.retrieved_chunks:
            context_text = "\n\n".join([
                f"[Source: {chunk.get('source', 'Unknown')}]\n{chunk.get('content', '')}"
                for chunk in state.retrieved_chunks[:5]  # Use top 5
            ])
        
        # Build system prompt
        student_level = "lycée"
        if state.student_profile:
            student_level = state.student_profile.get("level", "lycée")
        
        language = state.student_profile.get("language", "fr") if state.student_profile else "fr"
        
        system_prompt = f"""You are an expert teacher for students at {student_level} level.
- Answer in {language}
- Be pedagogically sound and clear
- Use the provided context to ground your answer
- Explain concepts step-by-step
- Keep answer concise (max 200 words)"""
        
        user_prompt = f"""Student question: {query}

{f"Context from knowledge base:{context_text}" if context_text else "No context available"}

Provide a clear, pedagogical answer:"""
        
        # Call LLM
        draft_answer = await llm.generate(
            user_prompt,
            system_prompt=system_prompt,
            max_tokens=300,
            temperature=0.7,
        )
        
        state.draft_answer = draft_answer.strip()
        state.reasoning_confidence = 0.8 if state.retrieval_confidence > 0.5 else 0.5
        
        log.info(f"✅ Generated answer ({len(draft_answer)} chars)")
        
        # Record in metadata
        state.agent_metadata["reasoning"] = {
            "answer_length": len(draft_answer),
            "context_chunks_used": len(state.retrieved_chunks),
            "confidence": state.reasoning_confidence,
        }
    
    except Exception as e:
        log.error(f"Reasoning failed: {e}")
        state.draft_answer = "I apologize, but I was unable to generate a response. Please try again."
        state.reasoning_confidence = 0.0
    
    return {
        "draft_answer": state.draft_answer,
        "reasoning_confidence": state.reasoning_confidence,
        "agent_metadata": state.agent_metadata,
    }


__all__ = [
    "reasoning_agent_node",
]
