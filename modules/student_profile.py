"""
Smart Teacher — Student Profile Management Module.

Manages student learning profiles with adaptive personalization:
    - Learning style and preferences (visual, auditory, mixed)
    - Comprehension level (collège, lycée, université)
    - Speech rate adaptation based on confusion/difficulty
    - Topic mastery and confusion tracking
    - Automatic system prompt customization for LLM
    - Persistent storage in Redis with 30-day TTL

Usage:
    profile_mgr = ProfileManager()
    student = await profile_mgr.get_or_create("student_123", language="fr", level="lycée")
    
    # Record interaction
    student.record_confusion("k-means clustering")
    student.record_question()
    await profile_mgr.save(student)
    
    # Adapt LLM behavior
    system_prompt_extension = student.get_system_prompt_additions()
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import redis.asyncio as aioredis

log = logging.getLogger("SmartTeacher.Profile")

# ════════════════════════════════════════════════════════════════════════
# REDIS CONNECTION
# ════════════════════════════════════════════════════════════════════════

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """
    Get or create Redis connection (singleton pattern).
    
    Returns
    -------
    aioredis.Redis
        Connected Redis client
    """
    global _redis
    if _redis is None:
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", 6379))
        _redis = aioredis.Redis(host=host, port=port, decode_responses=True)
    return _redis


# ════════════════════════════════════════════════════════════════════════
# STUDENT PROFILE DATACLASS
# ════════════════════════════════════════════════════════════════════════


@dataclass
class StudentProfile:
    """
    Student learning profile with adaptive personalization metadata.
    
    Attributes
    ----------
    student_id : str
        Unique anonymous student identifier (hash or UUID)
    name : str
        Student name or alias (default: "Étudiant")
    language : str
        ISO 639-1 language code (default: "fr")
    level : str
        Education level: "collège" (middle), "lycée" (high), or "université" (university)
    learning_style : str
        Detected learning style: "visual", "auditory", or "mixed"
    speech_rate : float
        Speech rate multiplier (0.7=slow, 1.0=normal, 1.3=fast)
    detail_level : str
        Preferred explanation detail: "simple", "normal", or "detailed"
    total_sessions : int
        Number of complete learning sessions
    total_questions : int
        Total questions asked in all sessions
    confusion_count : int
        Number of times student expressed confusion
    avg_response_time : float
        Average response time in seconds
    difficult_topics : List[str]
        Topics where student struggles
    mastered_topics : List[str]
        Topics where student demonstrates mastery
    asks_examples : int
        Frequency of requesting examples
    asks_repeat : int
        Frequency of asking for repetition
    interruptions : int
        Number of times student interrupted
    created_at : float
        Profile creation timestamp (Unix time)
    updated_at : float
        Last update timestamp (Unix time)
    """

    student_id: str
    name: str = "Étudiant"
    language: str = "fr"
    level: str = "lycée"

    # Learning preferences
    learning_style: str = "mixed"
    speech_rate: float = 1.0
    detail_level: str = "normal"

    # Session statistics
    total_sessions: int = 0
    total_questions: int = 0
    confusion_count: int = 0
    avg_response_time: float = 0.0

    # Topic tracking
    difficult_topics: List[str] = field(default_factory=list)
    mastered_topics: List[str] = field(default_factory=list)
    concept_mastery: Dict[str, float] = field(default_factory=dict)
    recent_confusion_score: float = 0.0
    last_response_time: float = 0.0
    last_action: str = ""

    # Behavior tracking (auto-detected)
    asks_examples: int = 0
    asks_repeat: int = 0
    interruptions: int = 0

    # Audit
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_json(self) -> str:
        """
        Serialize profile to JSON string.
        
        Returns
        -------
        str
            JSON representation of profile
        """
        return json.dumps(asdict(self))

    def to_dict(self) -> dict:
        """Return the profile as a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_json(cls, data: str) -> "StudentProfile":
        """
        Deserialize profile from JSON string.
        
        Parameters
        ----------
        data : str
            JSON-formatted profile data
        
        Returns
        -------
        StudentProfile
            Deserialized profile object
        """
        return cls(**json.loads(data))

    def record_confusion(self, topic: str = "") -> None:
        """
        Record student confusion on a topic.
        
        Updates confusion count and adds topic to difficult_topics list.
        
        Parameters
        ----------
        topic : str, optional
            Topic name where confusion occurred
        """
        self.confusion_count += 1
        if topic and topic not in self.difficult_topics:
            self.difficult_topics.append(topic)
        if topic:
            current = self.concept_mastery.get(topic, 0.45)
            self.concept_mastery[topic] = round(max(0.0, current - 0.15), 3)
        self.recent_confusion_score = min(1.0, max(self.recent_confusion_score, 0.75))
        self.updated_at = time.time()

    def record_mastery(self, topic: str) -> None:
        """
        Record student mastery of a topic.
        
        Moves topic from difficult_topics to mastered_topics.
        
        Parameters
        ----------
        topic : str
            Topic name where student demonstrated mastery
        """
        if topic not in self.mastered_topics:
            self.mastered_topics.append(topic)
        if topic in self.difficult_topics:
            self.difficult_topics.remove(topic)
        current = self.concept_mastery.get(topic, 0.55)
        self.concept_mastery[topic] = round(min(1.0, current + 0.2), 3)
        self.recent_confusion_score = max(0.0, self.recent_confusion_score - 0.1)
        self.updated_at = time.time()

    def record_interaction(self) -> None:
        """
        Record completion of one student-teacher interaction.
        
        Updates question counter and timestamp.
        """
        self.total_questions += 1
        self.updated_at = time.time()

    def adapt_speech_rate(self) -> float:
        """
        Calculate adapted speech rate based on confusion history.
        
        Automatically slows speech if student shows signs of struggle.
        
        Returns
        -------
        float
            Recommended speech rate multiplier (0.7 to 1.3)
        """
        if self.recent_confusion_score >= 0.7 or self.confusion_count > 5:
            return max(0.75, self.speech_rate - 0.1)
        elif self.last_response_time > 10 or self.asks_repeat > 3:
            return max(0.8, self.speech_rate - 0.05)
        return self.speech_rate

    def get_system_prompt_additions(self) -> str:
        """
        Generate LLM system prompt customization based on profile.
        
        Creates additional instructions for the language model to
        personalize responses according to student characteristics.
        
        Returns
        -------
        str
            System prompt extension or empty string if not applicable
        
        Examples
        --------
        >>> profile = StudentProfile(student_id="s1", level="collège")
        >>> prompt = profile.get_system_prompt_additions()
        >>> # Returns: "Utilise un vocabulaire simple, évite le jargon technique."
        """
        parts: List[str] = []

        # Adapt to education level
        if self.level == "collège":
            parts.append("Utilise un vocabulaire simple, évite le jargon technique.")
        elif self.level == "université":
            parts.append("Tu peux utiliser un vocabulaire technique et approfondi.")

        # Adapt detail level
        if self.detail_level == "simple":
            parts.append("Sois concis et va à l'essentiel.")
        elif self.detail_level == "detailed":
            parts.append("Donne des explications détaillées avec étapes.")

        # Emphasize difficult topics
        if self.difficult_topics:
            topics_str = ", ".join(self.difficult_topics[-3:])
            parts.append(
                f"L'étudiant a des difficultés avec : {topics_str}. "
                f"Sois particulièrement clair sur ces sujets."
            )

        # Note learning preference
        if self.asks_examples > 2:
            parts.append(
                "Cet étudiant apprécie les exemples concrets. Inclus-en systématiquement."
            )

        return " ".join(parts)


# ════════════════════════════════════════════════════════════════════════
# PROFILE MANAGER
# ════════════════════════════════════════════════════════════════════════


class ProfileManager:
    """
    Manages persistent student profiles in Redis.
    
    Provides CRUD operations with automatic TTL management for temporary
    profile data storage during active learning sessions.
    
    Attributes
    ----------
    PROFILE_TTL : int
        Redis key expiration time in seconds (30 days)
    """

    PROFILE_TTL: int = 86400 * 30  # 30 days in seconds

    async def get_or_create(
        self,
        student_id: str,
        language: str = "fr",
        level: str = "lycée"
    ) -> StudentProfile:
        """
        Retrieve existing profile or create new one.
        
        Attempts to load from Redis; creates fresh profile if not found.
        
        Parameters
        ----------
        student_id : str
            Unique student identifier
        language : str, optional
            ISO 639-1 language code (default: "fr")
        level : str, optional
            Education level (default: "lycée")
        
        Returns
        -------
        StudentProfile
            Existing or newly created profile
        """
        r = await get_redis()
        key = f"profile:{student_id}"
        
        try:
            data = await r.get(key)
            if data:
                log.debug(f"Loaded profile from Redis: {student_id}")
                return StudentProfile.from_json(data)
        except Exception as exc:
            log.warning(f"Failed to load profile from Redis: {exc}")
        
        # Create new profile
        profile = StudentProfile(student_id=student_id, language=language, level=level)
        log.info(f"Created new profile: {student_id} (lang={language}, level={level})")
        await self.save(profile)
        return profile

    async def save(self, profile: StudentProfile) -> None:
        """
        Persist profile to Redis with TTL.
        
        Parameters
        ----------
        profile : StudentProfile
            Profile to save
        
        Raises
        ------
        Logs warning on failure (does not raise exception)
        """
        try:
            r = await get_redis()
            await r.setex(
                f"profile:{profile.student_id}",
                self.PROFILE_TTL,
                profile.to_json()
            )
            log.debug(f"Saved profile to Redis: {profile.student_id}")
        except Exception as exc:
            log.warning(f"Failed to save profile to Redis: {exc}")

    async def update_from_interaction(
        self,
        student_id: str,
        interaction_type: str,
        topic: str = "",
        confused: bool = False,
        response_time: float | None = None,
        confidence: float | None = None,
        reward: float | None = None,
        action_taken: str = "",
    ) -> Optional[StudentProfile]:
        """
        Update profile based on student interaction type.
        
        Automatically tracks student behavior patterns to adjust
        personalization and adaptive content.
        
        Parameters
        ----------
        student_id : str
            Student identifier
        interaction_type : str
            Type of interaction: "repeat", "give_example", "explain_again", 
            "interrupt", or normal "question"
        topic : str, optional
            Topic related to interaction
        
        Returns
        -------
        StudentProfile or None
            Updated profile, or None if save fails
        """
        profile = await self.get_or_create(student_id)
        profile.last_action = action_taken or interaction_type
        
        if interaction_type == "repeat":
            profile.asks_repeat += 1
        elif interaction_type == "give_example":
            profile.asks_examples += 1
        elif interaction_type == "explain_again":
            profile.record_confusion(topic)
        elif interaction_type == "interrupt":
            profile.interruptions += 1

        if response_time is not None:
            response_time = max(0.0, float(response_time))
            profile.last_response_time = response_time
            if profile.avg_response_time <= 0:
                profile.avg_response_time = response_time
            else:
                profile.avg_response_time = round(profile.avg_response_time * 0.85 + response_time * 0.15, 3)

        low_confidence = confidence is not None and float(confidence) < 0.5
        if confused or low_confidence:
            profile.record_confusion(topic)
        elif topic:
            current = profile.concept_mastery.get(topic, 0.5)
            boost = 0.15 if reward is None or float(reward) > 0 else 0.05
            profile.concept_mastery[topic] = round(min(1.0, current + boost), 3)
            if topic not in profile.mastered_topics and profile.concept_mastery[topic] >= 0.85:
                profile.mastered_topics.append(topic)
            profile.recent_confusion_score = max(0.0, profile.recent_confusion_score - 0.05)
        
        # Always record as interaction
        profile.record_interaction()

        if reward is not None and float(reward) >= 0.7 and topic:
            profile.record_mastery(topic)
        
        await self.save(profile)
        return profile

    async def update_from_session(
        self,
        student_id: str,
        interaction_type: str,
        topic: str = "",
        confused: bool = False,
        response_time: float | None = None,
        confidence: float | None = None,
        reward: float | None = None,
        action_taken: str = "",
    ) -> Optional[StudentProfile]:
        """Backward-compatible alias used by older call sites."""
        return await self.update_from_interaction(
            student_id=student_id,
            interaction_type=interaction_type,
            topic=topic,
            confused=confused,
            response_time=response_time,
            confidence=confidence,
            reward=reward,
            action_taken=action_taken,
        )
