"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Profil Étudiant & Personnalisation          ║
║                                                                      ║
║  Gère le profil de chaque étudiant et adapte l'enseignement :       ║
║    - Niveau de compréhension                                         ║
║    - Style d'apprentissage (visuel, auditif, kinesthésique)         ║
║    - Vitesse de parole préférée                                      ║
║    - Historique des difficultés                                      ║
║    - Adaptation automatique du contenu                               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
import os
import redis.asyncio as aioredis

log = logging.getLogger("SmartTeacher.Profile")

_redis: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", 6379))
        _redis = aioredis.Redis(host=host, port=port, decode_responses=True)
    return _redis


@dataclass
class StudentProfile:
    student_id:       str
    name:             str   = "Étudiant"
    language:         str   = "fr"
    level:            str   = "lycée"       # collège | lycée | université

    # Style d'apprentissage
    learning_style:   str   = "mixed"       # visual | auditory | mixed
    speech_rate:      float = 1.0           # 0.7=lent, 1.0=normal, 1.3=rapide
    detail_level:     str   = "normal"      # simple | normal | detailed

    # Statistiques
    total_sessions:   int   = 0
    total_questions:  int   = 0
    confusion_count:  int   = 0
    avg_response_time: float = 0.0

    # Sujets difficiles
    difficult_topics: list  = field(default_factory=list)
    mastered_topics:  list  = field(default_factory=list)

    # Préférences détectées automatiquement
    asks_examples:    int   = 0   # combien de fois a demandé des exemples
    asks_repeat:      int   = 0   # combien de fois a demandé de répéter
    interruptions:    int   = 0   # nombre d'interruptions

    created_at:       float = field(default_factory=time.time)
    updated_at:       float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "StudentProfile":
        return cls(**json.loads(data))

    def record_confusion(self, topic: str = ""):
        """Enregistre une incompréhension."""
        self.confusion_count += 1
        if topic and topic not in self.difficult_topics:
            self.difficult_topics.append(topic)
        self.updated_at = time.time()

    def record_mastery(self, topic: str):
        """Enregistre une maîtrise."""
        if topic not in self.mastered_topics:
            self.mastered_topics.append(topic)
        if topic in self.difficult_topics:
            self.difficult_topics.remove(topic)
        self.updated_at = time.time()

    def record_question(self):
        self.total_questions += 1
        self.updated_at = time.time()

    def adapt_speech_rate(self) -> float:
        """
        Adapte la vitesse de parole selon le profil.
        Plus de confusions → parle plus lentement.
        """
        if self.confusion_count > 5:
            return max(0.75, self.speech_rate - 0.1)
        elif self.asks_repeat > 3:
            return max(0.8, self.speech_rate - 0.05)
        return self.speech_rate

    def get_system_prompt_additions(self) -> str:
        """
        Retourne des instructions supplémentaires pour le LLM
        basées sur le profil de l'étudiant.
        """
        parts = []

        if self.level == "collège":
            parts.append("Utilise un vocabulaire simple, évite le jargon technique.")
        elif self.level == "université":
            parts.append("Tu peux utiliser un vocabulaire technique et approfondi.")

        if self.detail_level == "simple":
            parts.append("Sois concis et va à l'essentiel.")
        elif self.detail_level == "detailed":
            parts.append("Donne des explications détaillées avec étapes.")

        if self.difficult_topics:
            tops = ", ".join(self.difficult_topics[-3:])
            parts.append(f"L'étudiant a des difficultés avec : {tops}. Sois particulièrement clair sur ces sujets.")

        if self.asks_examples > 2:
            parts.append("Cet étudiant apprécie les exemples concrets. Inclus-en systématiquement.")

        return " ".join(parts)


class ProfileManager:
    """Gère les profils étudiants dans Redis."""

    PROFILE_TTL = 86400 * 30  # 30 jours

    async def get_or_create(self, student_id: str, language: str = "fr", level: str = "lycée") -> StudentProfile:
        r = await get_redis()
        key = f"profile:{student_id}"
        try:
            data = await r.get(key)
            if data:
                return StudentProfile.from_json(data)
        except Exception:
            pass
        profile = StudentProfile(student_id=student_id, language=language, level=level)
        await self.save(profile)
        return profile

    async def save(self, profile: StudentProfile) -> None:
        try:
            r = await get_redis()
            await r.setex(f"profile:{profile.student_id}", self.PROFILE_TTL, profile.to_json())
        except Exception as e:
            log.warning(f"Profile save failed: {e}")

    async def update_from_session(self, student_id: str, nav_command: str, topic: str = "") -> None:
        """Met à jour le profil selon les interactions de la session."""
        profile = await self.get_or_create(student_id)
        if nav_command == "repeat":
            profile.asks_repeat += 1
        elif nav_command == "give_example":
            profile.asks_examples += 1
        elif nav_command == "explain_again":
            profile.record_confusion(topic)
        elif nav_command == "interrupt":
            profile.interruptions += 1
        profile.total_questions += 1
        await self.save(profile)
