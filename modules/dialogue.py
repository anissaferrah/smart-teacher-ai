"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Machine d'État du Dialogue                  ║
║                                                                      ║
║  États :                                                             ║
║    IDLE → PRESENTING → LISTENING → PROCESSING → RESPONDING          ║
║                                                                      ║
║  Fonctionnalités :                                                   ║
║    ✅ Présentation automatique du cours section par section          ║
║    ✅ Interruption instantanée quand l'étudiant parle                ║
║    ✅ Retour au cours après réponse à une question                   ║
║    ✅ Stockage de l'état dans Redis (TTL 1h)                         ║
║    ✅ Détection d'incompréhension → reformulation automatique        ║
║    ✅ Navigation (suivant / précédent / répéter)                     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import json
import logging
import time
import uuid
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional

import redis.asyncio as aioredis

from config import Config

log = logging.getLogger("SmartTeacher.Dialogue")

# ── Redis ──────────────────────────────────────────────────────────────
_redis: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        host = __import__("os").getenv("REDIS_HOST", "localhost")
        port = int(__import__("os").getenv("REDIS_PORT", 6379))
        _redis = aioredis.Redis(host=host, port=port, decode_responses=True)
    return _redis


# ══════════════════════════════════════════════════════════════════════
#  ÉTATS DE LA MACHINE
# ══════════════════════════════════════════════════════════════════════

class DialogState(str, Enum):
    IDLE        = "IDLE"          # Aucune session active
    PRESENTING  = "PRESENTING"    # L'IA présente le cours (TTS en cours)
    LISTENING   = "LISTENING"     # L'IA écoute l'étudiant (VAD actif)
    PROCESSING  = "PROCESSING"    # STT + RAG + LLM en cours
    RESPONDING  = "RESPONDING"    # TTS réponse en cours


# Transitions valides
VALID_TRANSITIONS: dict[DialogState, list[DialogState]] = {
    DialogState.IDLE:       [DialogState.PRESENTING, DialogState.LISTENING],
    DialogState.PRESENTING: [DialogState.LISTENING,  DialogState.IDLE],
    DialogState.LISTENING:  [DialogState.PROCESSING, DialogState.PRESENTING],
    DialogState.PROCESSING: [DialogState.RESPONDING, DialogState.IDLE],
    DialogState.RESPONDING: [DialogState.PRESENTING, DialogState.LISTENING, DialogState.IDLE],
}


# ══════════════════════════════════════════════════════════════════════
#  CONTEXTE DE SESSION
# ══════════════════════════════════════════════════════════════════════

@dataclass
class SessionContext:
    """
    État complet d'une session d'apprentissage.
    Sérialisé en JSON et stocké dans Redis.
    """
    session_id:      str  = field(default_factory=lambda: str(uuid.uuid4()))
    state:           str  = DialogState.IDLE.value
    language:        str  = "fr"
    student_level:   str  = "lycée"    # collège | lycée | université

    # Position dans le cours
    course_id:       Optional[str] = None
    chapter_index:   int  = 0
    section_index:   int  = 0
    char_position:   int  = 0          # Position dans le texte de la section (pour reprendre)

    # Historique conversationnel (max 10 messages)
    history:         list = field(default_factory=list)

    # Métriques
    total_turns:     int   = 0
    interruptions:   int   = 0
    created_at:      float = field(default_factory=time.time)
    last_activity:   float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "SessionContext":
        d = json.loads(data)
        return cls(**d)

    def add_to_history(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        if len(self.history) > Config.MAX_HISTORY_TURNS * 2:
            self.history = self.history[2:]
        self.last_activity = time.time()


# ══════════════════════════════════════════════════════════════════════
#  GESTIONNAIRE DE DIALOGUE
# ══════════════════════════════════════════════════════════════════════

SESSION_TTL = 3600   # 1 heure

class DialogueManager:
    """
    Gère l'état de la conversation entre l'étudiant et l'IA.

    Utilisation typique (WebSocket) :
        manager = DialogueManager()

        # Créer une session
        ctx = await manager.create_session(language="fr")

        # Démarrer la présentation du cours
        await manager.transition(ctx.session_id, DialogState.PRESENTING)
        text = await manager.get_current_section_text(ctx.session_id, course_sections)

        # L'étudiant interrompt → transition LISTENING
        await manager.handle_interruption(ctx.session_id)

        # L'étudiant a fini de parler → PROCESSING
        await manager.transition(ctx.session_id, DialogState.PROCESSING)

        # Après la réponse → reprendre le cours (PRESENTING)
        await manager.transition(ctx.session_id, DialogState.PRESENTING)
    """

    # ── Gestion des sessions Redis ────────────────────────────────────
    async def _save(self, ctx: SessionContext) -> None:
        r = await get_redis()
        await r.setex(f"session:{ctx.session_id}", SESSION_TTL, ctx.to_json())

    async def _load(self, session_id: str) -> Optional[SessionContext]:
        r = await get_redis()
        data = await r.get(f"session:{session_id}")
        if not data:
            return None
        return SessionContext.from_json(data)

    async def _delete(self, session_id: str) -> None:
        r = await get_redis()
        await r.delete(f"session:{session_id}")

    # ── Cycle de vie de la session ────────────────────────────────────
    async def create_session(
        self,
        session_id:    Optional[str] = None,
        language:      str = "fr",
        student_level: str = "lycée",
        course_id:     Optional[str] = None,
    ) -> SessionContext:
        ctx = SessionContext(
            session_id=session_id or str(uuid.uuid4()),
            language=language,
            student_level=student_level,
            course_id=course_id,
        )
        await self._save(ctx)
        log.info(f"✅ Session créée : {ctx.session_id[:8]} | lang={language}")
        return ctx

    async def get_session(self, session_id: str) -> Optional[SessionContext]:
        return await self._load(session_id)

    async def end_session(self, session_id: str) -> None:
        await self._delete(session_id)
        log.info(f"🔚 Session terminée : {session_id[:8]}")

    # ── Transitions d'état ────────────────────────────────────────────
    async def transition(
        self, session_id: str, new_state: DialogState
    ) -> Optional[SessionContext]:
        ctx = await self._load(session_id)
        if not ctx:
            log.warning(f"Session {session_id[:8]} introuvable")
            return None

        current = DialogState(ctx.state)
        allowed = VALID_TRANSITIONS.get(current, [])

        if new_state not in allowed:
            log.warning(
                f"Transition invalide : {current.value} → {new_state.value} "
                f"(autorisées : {[s.value for s in allowed]})"
            )
            return ctx

        ctx.state = new_state.value
        ctx.last_activity = time.time()
        await self._save(ctx)
        log.debug(f"[{session_id[:8]}] {current.value} → {new_state.value}")
        return ctx

    # ── Interruption ──────────────────────────────────────────────────
    async def handle_interruption(self, session_id: str) -> Optional[SessionContext]:
        """
        Appelé quand le VAD détecte que l'étudiant commence à parler
        pendant que l'IA présente le cours.
        → PRESENTING ou RESPONDING → LISTENING
        """
        ctx = await self._load(session_id)
        if not ctx:
            return None

        if ctx.state in (DialogState.PRESENTING.value, DialogState.RESPONDING.value):
            ctx.state = DialogState.LISTENING.value
            ctx.interruptions += 1
            ctx.last_activity = time.time()
            await self._save(ctx)
            log.info(f"[{session_id[:8]}] ⚡ Interruption #{ctx.interruptions} — LISTENING")

        return ctx

    # ── Navigation dans le cours ──────────────────────────────────────
    async def next_section(self, session_id: str) -> Optional[SessionContext]:
        ctx = await self._load(session_id)
        if not ctx:
            return None
        ctx.section_index  += 1
        ctx.char_position   = 0
        await self._save(ctx)
        return ctx

    async def prev_section(self, session_id: str) -> Optional[SessionContext]:
        ctx = await self._load(session_id)
        if not ctx:
            return None
        ctx.section_index  = max(0, ctx.section_index - 1)
        ctx.char_position  = 0
        await self._save(ctx)
        return ctx

    async def save_position(self, session_id: str, char_pos: int) -> None:
        """Sauvegarde la position de lecture pour reprendre après interruption."""
        ctx = await self._load(session_id)
        if ctx:
            ctx.char_position = char_pos
            await self._save(ctx)

    async def get_resume_text(
        self, session_id: str, section_text: str
    ) -> str:
        """
        Retourne le texte restant à partir de la position de reprise.
        Ajoute une phrase de transition naturelle.
        """
        ctx = await self._load(session_id)
        if not ctx:
            return section_text

        pos = ctx.char_position
        if pos <= 0 or pos >= len(section_text):
            return section_text

        remaining = section_text[pos:].strip()
        transitions = {
            "fr": "Comme je le disais, ",
            "ar": "كما كنت أقول، ",
            "en": "As I was saying, ",
            "tr": "Söylediğim gibi, ",
        }
        prefix = transitions.get(ctx.language, "Continuing... ")
        return prefix + remaining

    # ── Mise à jour de l'historique ───────────────────────────────────
    async def add_to_history(
        self, session_id: str, role: str, content: str
    ) -> None:
        ctx = await self._load(session_id)
        if ctx:
            ctx.add_to_history(role, content)
            ctx.total_turns += 1 if role == "assistant" else 0
            await self._save(ctx)

    # ── Détection d'incompréhension ───────────────────────────────────
    def detect_confusion(self, text: str, language: str = "fr") -> bool:
        """
        Détecte si l'étudiant n'a pas compris la dernière explication.
        Retourne True si une reformulation est nécessaire.
        """
        text_lower = text.lower()

        confusion_keywords = {
            "fr": ["je comprends pas", "je ne comprends pas", "c'est quoi",
                   "qu'est-ce que", "répète", "explique", "pas compris",
                   "c'est flou", "confus", "aide"],
            "ar": ["ما فهمت", "لم أفهم", "ما هو", "اشرح", "أعد"],
            "en": ["don't understand", "what is", "explain", "confused",
                   "not clear", "repeat", "help"],
            "tr": ["anlamıyorum", "nedir", "açıkla", "tekrar"],
        }

        keywords = confusion_keywords.get(language, confusion_keywords["fr"])
        return any(kw in text_lower for kw in keywords)

    # ── Stats ──────────────────────────────────────────────────────────
    async def get_stats(self, session_id: str) -> dict:
        ctx = await self._load(session_id)
        if not ctx:
            return {}
        return {
            "session_id":    session_id,
            "state":         ctx.state,
            "language":      ctx.language,
            "total_turns":   ctx.total_turns,
            "interruptions": ctx.interruptions,
            "chapter":       ctx.chapter_index,
            "section":       ctx.section_index,
            "history_len":   len(ctx.history),
            "uptime_min":    round((time.time() - ctx.created_at) / 60, 1),
        }
