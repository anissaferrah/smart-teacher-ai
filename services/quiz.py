from __future__ import annotations


def is_quiz_request(normalized_text: str) -> bool:
    text = (normalized_text or "").lower()
    quiz_keywords = ["quiz", "qcm", "question", "exercice", "test", "eval", "évaluation"]
    return any(keyword in text for keyword in quiz_keywords)
