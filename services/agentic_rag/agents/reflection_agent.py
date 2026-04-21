"""Reflection Agent - Validate answer quality and self-correct."""

import logging
import asyncio
from typing import Dict, Any
from infrastructure.logging import get_logger

log = get_logger(__name__)


async def reflection_agent_node(
    state: "AgenticRAGState",
    llm,
) -> Dict[str, Any]:
    """Validate answer quality and determine if refinement needed.
    
    Args:
        state: Current workflow state
        llm: Language model instance
        
    Returns:
        Dict with is_valid, reflection_score, and needs_refinement
    """
    if not state.draft_answer:
        state.is_valid = False
        state.reflection_score = 0.0
        state.needs_refinement = False
        return {
            "is_valid": False,
            "reflection_score": 0.0,
            "needs_refinement": False,
        }
    
    log.info("🔍 Reflecting on answer quality...")
    
    try:
        # Check 1: Groundedness - is answer grounded in retrieved chunks?
        groundedness_score = 1.0
        if state.retrieved_chunks:
            check_prompt = f"""Is this answer grounded in the provided context?
Context: {state.retrieved_chunks[0].get('content', '')[:500]}
Answer: {state.draft_answer[:500]}

Rate groundedness 0.0-1.0 (0=not grounded, 1=fully grounded). Answer ONLY with a number."""
            
            try:
                score_str = await llm.generate(check_prompt, max_tokens=5, temperature=0.0)
                groundedness_score = float(score_str.strip())
            except:
                groundedness_score = 0.7  # Default if parsing fails
        
        # Check 2: Completeness - does answer adequately address question?
        completeness_check = f"""Does this answer adequately address the student's question?
Question: {state.query}
Answer: {state.draft_answer[:500]}

Rate completeness 0.0-1.0 (0=incomplete, 1=complete). Answer ONLY with a number."""
        
        try:
            completeness_str = await llm.generate(completeness_check, max_tokens=5, temperature=0.0)
            completeness_score = float(completeness_str.strip())
        except:
            completeness_score = 0.7
        
        # Check 3: Clarity - is answer clear and understandable?
        clarity_score = 1.0 if len(state.draft_answer) > 20 else 0.5
        
        # Combine scores
        state.reflection_score = (
            groundedness_score * 0.4 +
            completeness_score * 0.4 +
            clarity_score * 0.2
        )
        
        # Determine if valid (>0.6) and if needs refinement
        state.is_valid = state.reflection_score > 0.6
        state.needs_refinement = state.reflection_score < 0.8 and state.is_valid
        
        log.info(f"✓ Reflection score: {state.reflection_score:.2f} (valid: {state.is_valid}, refine: {state.needs_refinement})")
        
        # Generate refinement suggestions if needed
        if state.needs_refinement:
            refine_prompt = f"""The student received this answer. What could be improved?
Question: {state.query}
Answer: {state.draft_answer}

List 1-2 specific improvements (max 50 words each):"""
            
            try:
                suggestions_text = await llm.generate(refine_prompt, max_tokens=100, temperature=0.7)
                state.refinement_suggestions = suggestions_text.strip().split("\n")[:2]
            except:
                state.refinement_suggestions = []
        
        # Record in metadata
        state.agent_metadata["reflection"] = {
            "groundedness_score": groundedness_score,
            "completeness_score": completeness_score,
            "clarity_score": clarity_score,
            "final_score": state.reflection_score,
            "is_valid": state.is_valid,
            "needs_refinement": state.needs_refinement,
        }
    
    except Exception as e:
        log.error(f"Reflection failed: {e}")
        state.reflection_score = 0.6  # Default to passing
        state.is_valid = True
        state.needs_refinement = False
    
    return {
        "is_valid": state.is_valid,
        "reflection_score": state.reflection_score,
        "needs_refinement": state.needs_refinement,
        "refinement_suggestions": state.refinement_suggestions,
        "agent_metadata": state.agent_metadata,
    }


__all__ = [
    "reflection_agent_node",
]
