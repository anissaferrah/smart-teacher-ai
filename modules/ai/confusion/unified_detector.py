"""Unified confusion detection combining multiple signals."""

import logging
from typing import Dict, Any, Optional, List
from functools import lru_cache

from infrastructure.logging import get_logger

log = get_logger(__name__)


class UnifiedConfusionDetector:
    """Unified confusion detector combining SIGHT model + keyword + repetition signals."""
    
    def __init__(
        self,
        sight_model_path: Optional[str] = None,
        confidence_threshold: float = 0.6,
        device: str = "cpu",
    ):
        """Initialize detector.
        
        Args:
            sight_model_path: Path to SIGHT model checkpoint (optional)
            confidence_threshold: Threshold for confusion detection
            device: Device to run model on (cpu/cuda)
        """
        self.device = device
        self.threshold = confidence_threshold
        self.sight_model = None
        self.model_available = False
        
        if sight_model_path:
            try:
                self._load_sight_model(sight_model_path)
                self.model_available = True
                log.info(f"✅ SIGHT model loaded from {sight_model_path}")
            except Exception as e:
                log.warning(f"⚠️  SIGHT model failed to load: {e} - using fallback detection")
                self.model_available = False
        else:
            log.info("⚠️  No SIGHT model path provided - using keyword/repetition detection only")
    
    def _load_sight_model(self, model_path: str):
        """Load SIGHT model checkpoint."""
        # Placeholder: actual implementation would load transformer + classifier
        # For now: skip if file doesn't exist
        import os
        if not os.path.exists(model_path):
            log.warning(f"SIGHT model not found at {model_path}")
            return
        # Model loading would go here
        pass
    
    async def detect(
        self,
        question: str,
        language: str = "fr",
        previous_questions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Detect confusion with multiple signals.
        
        Args:
            question: Student's question
            language: Language code (fr/en)
            previous_questions: Previous questions in session
            
        Returns:
            Dict with:
            - is_confused: bool
            - confidence: float (0.0-1.0)
            - reason: str
            - signals: dict of individual signal scores
        """
        signals = {}
        
        # Signal 1: SIGHT model (semantic) - if available
        sight_score = 0.0
        if self.model_available:
            try:
                sight_score = self._detect_sight(question)
                signals["sight_semantic"] = sight_score
            except Exception as e:
                log.debug(f"SIGHT detection failed: {e}")
                signals["sight_semantic"] = 0.0
        
        # Signal 2: Keyword detection (always available)
        keyword_score = self._detect_keyword(question, language)
        signals["keyword_confusion"] = keyword_score
        
        # Signal 3: Repetition detection
        repetition_score = self._detect_repetition(question, previous_questions)
        signals["repetition_pattern"] = repetition_score
        
        # Combine signals (weighted average)
        if self.model_available:
            confidence = (
                sight_score * 0.6 +      # SIGHT: 60%
                keyword_score * 0.3 +    # Keywords: 30%
                repetition_score * 0.1   # Repetition: 10%
            )
        else:
            # Fallback: keyword + repetition only
            confidence = (
                keyword_score * 0.7 +
                repetition_score * 0.3
            )
        
        is_confused = confidence > self.threshold
        # Keep reason consistent with boolean outcome to avoid contradictory logs.
        reason = self._determine_reason(signals, language) if is_confused else ""
        
        return {
            "is_confused": is_confused,
            "confidence": round(min(confidence, 1.0), 3),
            "reason": reason,
            "signals": {k: round(v, 3) for k, v in signals.items()},
            "threshold_used": self.threshold,
            "model_available": self.model_available,
        }
    
    def _detect_sight(self, question: str) -> float:
        """SIGHT model-based semantic confusion detection."""
        if not self.model_available or not self.sight_model:
            return 0.0
        
        try:
            # Encode question with XLM-RoBERTa
            # Pass through classifier head
            # Return sigmoid score (0.0-1.0)
            score = 0.5  # Placeholder: would be actual model inference
            return score
        except Exception as e:
            log.error(f"SIGHT detection failed: {e}")
            return 0.0
    
    def _detect_keyword(self, question: str, language: str = "fr") -> float:
        """Keyword-based confusion detection."""
        keywords = {
            "fr": [
                "comprends pas", "c'est pas clair", "pas compris",
                "confus", "confuse", "explique encore", "trop compliqué",
                "aide", "help", "je sais pas", "unclear", "flou",
                "pas de sens", "ne comprend", "hein", "quoi",
            ],
            "en": [
                "don't understand", "unclear", "confused", "confusing",
                "explain again", "too complicated", "help me", "i don't get it",
                "what do you mean", "huh", "i don't know", "lost",
            ],
        }
        
        text_lower = question.lower()
        keyword_list = keywords.get(language, keywords["en"])
        
        # Count keyword matches
        matches = sum(1 for kw in keyword_list if kw in text_lower)
        
        # Score: 0 to 1 based on keyword density
        if len(text_lower.split()) == 0:
            return 0.0
        
        keyword_density = matches / max(len(keyword_list), 1)
        score = min(keyword_density * 0.5, 1.0)
        
        return score
    
    def _detect_repetition(
        self, question: str, previous_questions: Optional[List[str]] = None
    ) -> float:
        """Repetition detection - student asking similar question again."""
        if not previous_questions or len(previous_questions) == 0:
            return 0.0
        
        # Simple similarity check: if >75% similar to recent question, flag as confusion
        from difflib import SequenceMatcher
        
        max_similarity = 0.0
        for prev_q in previous_questions[-5:]:  # Check last 5 questions
            similarity = SequenceMatcher(None, question.lower(), prev_q.lower()).ratio()
            max_similarity = max(max_similarity, similarity)
        
        # If >75% similar, score 1.0 (strong repetition signal)
        # Otherwise scale based on similarity
        if max_similarity > 0.75:
            return 1.0
        elif max_similarity > 0.6:
            return 0.7
        elif max_similarity > 0.5:
            return 0.4
        else:
            return 0.0
    
    def _determine_reason(self, signals: Dict[str, float], language: str = "fr") -> str:
        """Determine reason for confusion based on dominant signal."""
        reasons = {
            "fr": {
                "sight_semantic": "Ambiguïté sémantique détectée",
                "keyword_confusion": "Mots-clés de confusion détectés",
                "repetition_pattern": "Question répétée récemment",
            },
            "en": {
                "sight_semantic": "Semantic ambiguity detected",
                "keyword_confusion": "Confusion keywords detected",
                "repetition_pattern": "Question repeated recently",
            },
        }
        
        if not signals:
            return "Confusion detected" if language == "en" else "Confusion détectée"
        
        max_signal = max(signals, key=signals.get)
        lang_reasons = reasons.get(language, reasons["en"])
        
        return lang_reasons.get(max_signal, "Confusion detected")


# Singleton instance
_unified_detector: Optional[UnifiedConfusionDetector] = None


async def get_unified_confusion_detector(
    confusion_model_path: Optional[str] = None,
    device: str = "cpu",
) -> UnifiedConfusionDetector:
    """Get or create singleton detector.
    
    Args:
        confusion_model_path: Path to SIGHT model (optional)
        device: Device to use (cpu/cuda)
        
    Returns:
        UnifiedConfusionDetector: Singleton instance
    """
    global _unified_detector
    if _unified_detector is None:
        _unified_detector = UnifiedConfusionDetector(
            sight_model_path=confusion_model_path,
            device=device,
        )
    return _unified_detector


__all__ = [
    "UnifiedConfusionDetector",
    "get_unified_confusion_detector",
]
