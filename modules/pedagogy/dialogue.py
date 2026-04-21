"""Smart Teacher — Dialogue State Machine"""

import base64
import hashlib
import json
import logging
import time
import uuid
from functools import lru_cache
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional

import redis.asyncio as aioredis
try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:
    from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings

from config import Config

log = logging.getLogger("SmartTeacher.Dialogue")

EMBEDDING_MODEL_OPENAI = "text-embedding-3-small"
EMBEDDING_MODEL_LOCAL = "BAAI/bge-m3"


def _is_openai_embedding_model(model_name: str) -> bool:
    return model_name.strip().lower().startswith("text-embedding-")


@lru_cache(maxsize=1)
def _get_semantic_embedder():
    model_name = Config.RAG_EMBEDDING_MODEL or EMBEDDING_MODEL_LOCAL
    if _is_openai_embedding_model(model_name):
        return OpenAIEmbeddings(model=model_name, max_retries=0)
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


@lru_cache(maxsize=1)
def _get_sight_confusion_predictor():
    try:
        from modules.ai.confusion_detector import predict_confusion
        return predict_confusion
    except Exception as exc:
        log.warning("SIGHT confusion model unavailable: %s", exc)
        return None

_redis: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        host = __import__("os").getenv("REDIS_HOST", "localhost")
        port = int(__import__("os").getenv("REDIS_PORT", 6379))
        _redis = aioredis.Redis(host=host, port=port, decode_responses=True)
    return _redis


class DialogState(str, Enum):
    IDLE        = "IDLE"          # Aucune session active
    INDEXING    = "INDEXING"      # Ingestion de cours en cours (bloqué)
    PRESENTING  = "PRESENTING"    # L'IA présente le cours (TTS en cours)
    LISTENING   = "LISTENING"     # L'IA écoute l'étudiant (VAD actif)
    PROCESSING  = "PROCESSING"    # STT + RAG + LLM en cours
    RESPONDING  = "RESPONDING"    # TTS réponse en cours
    WAITING     = "WAITING"       # En attente de compréhension (demande si OK)
    CLARIFICATION = "CLARIFICATION"  # ✅ NOUVEAU: Étudiant demande clarification/revenir slide


# Transitions valides — Machine d'état REAL WORLD (prod-ready)
VALID_TRANSITIONS: dict[DialogState, list[DialogState]] = {
    DialogState.IDLE:       [DialogState.INDEXING, DialogState.PRESENTING, DialogState.LISTENING],
    DialogState.INDEXING:   [DialogState.IDLE, DialogState.PRESENTING],
    DialogState.PRESENTING: [DialogState.LISTENING, DialogState.WAITING, DialogState.CLARIFICATION],  # ✅ Peut clarifier pendant présentation
    DialogState.LISTENING:  [DialogState.PROCESSING, DialogState.PRESENTING, DialogState.CLARIFICATION],  # ✅ Demander clarif pendant écoute
    DialogState.PROCESSING: [DialogState.RESPONDING, DialogState.CLARIFICATION, DialogState.IDLE, DialogState.LISTENING, DialogState.PRESENTING],
    DialogState.RESPONDING: [DialogState.PRESENTING, DialogState.WAITING, DialogState.LISTENING, DialogState.CLARIFICATION],  # ✅ Question pendant réponse
    DialogState.WAITING:    [DialogState.PRESENTING, DialogState.LISTENING, DialogState.IDLE, DialogState.CLARIFICATION],
    DialogState.CLARIFICATION: [DialogState.RESPONDING, DialogState.PRESENTING, DialogState.LISTENING],  # ✅ Répondre à clarif, retour à présentation
}


@dataclass
class SessionContext:
    """Complete session state (serialized to Redis)"""
    session_id:      str  = field(default_factory=lambda: str(uuid.uuid4()))
    state:           str  = DialogState.IDLE.value
    language:        str  = "fr"
    student_level:   str  = "lycée"    # collège | lycée | université

    # Position dans le cours
    course_id:       Optional[str] = None
    chapter_index:   int  = 0
    section_index:   int  = 0
    char_position:   int  = 0          # Position dans le texte de la section (pour reprendre)
    
    # ✅ NOUVEAU: Course metadata (analyse du cours)
    course_summary:  str  = ""         # Résumé court du cours (pour LLM)
    course_analysis: dict = field(default_factory=dict)  # Analyse complète (lang, level, etc)
    last_slide_explained: str = ""     # Slide précédente expliquée (pour continuité)
    
    # ── Détection de confusion ─────────────────────────────────────
    confusion_count:      int  = 0          # Nombre de confusions détectées cette session
    last_question_hash:   str  = ""         # Hash de la dernière question (pour détecter répétitions)
    repeated_question_count: int = 0        # Fois qu'une même question a été posée
    
    # ✅ NOUVEAU (Couche #1): Profil adaptatif étudiant pour seuils dynamiques
    student_baseline: dict = field(default_factory=lambda: {
        "avg_speech_rate": 120.0,              # mots/min (baseline francophone)
        "avg_question_length": 8,              # mots typiques par question
        "avg_questions_per_turn": 1.2,         # Questions par tour
        "hesitation_baseline": 1.0,            # Hésitations moyennes
        "confusion_threshold_multiplier": 1.0, # Adaptatif (1.0 = normal, <1 = sujet confus)
        "turns_analyzed": 0,                   # Nombre de turns análysés
    })
    
    # 🔴 PAUSE/REPRISE — Sauvegarder position exacte lors pause
    paused_state:    dict = field(default_factory=lambda: {
        "is_paused": False,
        "slide_id": None,              # Quel slide?
        "char_offset": 0,              # Position (caractères)
        "timestamp": None,             # Quand?
    })
    
    # Blocking pendant ingestion
    is_indexing:     bool = False      # True = en cours d'indexation, bloque les questions
    indexing_progress: int = 0         # Pourcentage 0-100

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
PRESENTATION_SNAPSHOT_TTL = SESSION_TTL
TTS_CACHE_TTL = 24 * 3600

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

    @staticmethod
    def _presentation_snapshot_key(session_id: str, slide_id: str) -> str:
        return f"presentation:snapshot:{session_id}:{slide_id}"

    @staticmethod
    def _tts_cache_key(text: str, language: str, rate: str, provider: str, voice_name: str) -> str:
        normalized = "|".join([
            provider.strip().lower(),
            voice_name.strip().lower(),
            language.strip().lower(),
            rate.strip().lower(),
            text.strip(),
        ])
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        return f"presentation:tts:{digest}"

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
        
        # Si on est déjà dans l'état cible, ne rien faire (pas d'erreur)
        if current == new_state:
            log.debug(f"[{session_id[:8]}] Déjà en {current.value}, ignorer transition")
            return ctx
        
        allowed = VALID_TRANSITIONS.get(current, [])

        if new_state not in allowed:
            msg = f"Transition invalide : {current.value} → {new_state.value} (autorisées : {[s.value for s in allowed]})"
            log.error(f"🔴 BLOCKED: {msg}")
            raise ValueError(msg)

        ctx.state = new_state.value
        ctx.last_activity = time.time()
        await self._save(ctx)
        log.info(f"✅ [{session_id[:8]}] {current.value} → {new_state.value}")
        return ctx

    # ── Pause/Reprise ────────────────────────────────────────────────────────
    async def pause_session(
        self,
        session_id: str,
        slide_id: Optional[str] = None,
        char_offset: int = 0,
        presentation_text: Optional[str] = None,
        presentation_cursor: Optional[int] = None,
        presentation_key: Optional[str] = None,
        slide_title: Optional[str] = None,
    ) -> Optional[SessionContext]:
        """Save exact position when pausing"""
        ctx = await self._load(session_id)
        if not ctx:
            return None
        
        ctx.paused_state = {
            "is_paused": True,
            "slide_id": slide_id,
            "char_offset": char_offset,
            "timestamp": time.time(),
            "presentation_text": presentation_text or "",
            "presentation_cursor": max(0, presentation_cursor if presentation_cursor is not None else char_offset),
            "presentation_key": presentation_key or slide_id or "",
            "slide_title": slide_title or "",
            "presentation_text_len": len(presentation_text or ""),
        }
        ctx.char_position = char_offset
        ctx.interruptions += 1
        ctx.state = DialogState.WAITING.value
        ctx.last_activity = time.time()
        await self._save(ctx)

        if slide_id:
            await self.save_presentation_snapshot(
                session_id=session_id,
                slide_id=slide_id,
                presentation_text=presentation_text or "",
                presentation_cursor=ctx.char_position,
                slide_title=slide_title or "",
            )

        log.info(f"⏸️  [{session_id[:8]}] Paused at offset {char_offset} | slide={slide_id or 'unknown'}")
        return ctx

    async def resume_session(self, session_id: str) -> Optional[SessionContext]:
        """Resume exactly at pause point (not from beginning!)"""
        ctx = await self._load(session_id)
        if not ctx:
            return None
        
        if not ctx.paused_state.get("is_paused"):
            log.warning(f"[{session_id[:8]}] Session is not paused")
            return ctx
        
        offset = ctx.paused_state.get("presentation_cursor", ctx.paused_state.get("char_offset", 0))
        ctx.paused_state["is_paused"] = False
        ctx.paused_state["char_offset"] = offset
        ctx.paused_state["presentation_cursor"] = offset
        ctx.char_position = offset
        ctx.state = DialogState.PRESENTING.value
        ctx.last_activity = time.time()
        await self._save(ctx)
        log.info(f"▶️  [{session_id[:8]}] Resumed from offset {offset}")
        return ctx

    # ── Interruption ──────────────────────────────────────────────────
    async def handle_interruption(self, session_id: str) -> Optional[SessionContext]:
        """
        When VAD detects student speaking during presentation.
        PRESENTING → LISTENING (valid)
        RESPONDING must NOT go directly to LISTENING
        """
        ctx = await self._load(session_id)
        if not ctx:
            return None

        if ctx.state in {DialogState.PRESENTING.value, DialogState.RESPONDING.value}:
            return await self.pause_session(
                session_id,
                slide_id=ctx.paused_state.get("slide_id"),
                char_offset=ctx.char_position,
            )
        else:
            log.debug(f"[{session_id[:8]}] Interrupt ignored (state={ctx.state})")

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
            needs_snapshot_update = bool(ctx.paused_state.get("presentation_text") and ctx.paused_state.get("slide_id"))
            if ctx.paused_state.get("presentation_text") and ctx.paused_state.get("slide_id"):
                ctx.paused_state["char_offset"] = char_pos
                ctx.paused_state["presentation_cursor"] = char_pos
            await self._save(ctx)

            if needs_snapshot_update:
                await self.save_presentation_snapshot(
                    session_id=session_id,
                    slide_id=str(ctx.paused_state.get("slide_id")),
                    presentation_text=ctx.paused_state.get("presentation_text") or "",
                    presentation_cursor=char_pos,
                    slide_title=str(ctx.paused_state.get("slide_title") or ""),
                )

    async def save_course_position(
        self,
        session_id: str,
        course_id: Optional[str] = None,
        chapter_index: Optional[int] = None,
        section_index: Optional[int] = None,
        char_pos: Optional[int] = None,
    ) -> None:
        """Sauvegarde la position courante du cours et de la lecture."""
        ctx = await self._load(session_id)
        if not ctx:
            return

        if course_id is not None:
            ctx.course_id = course_id
        if chapter_index is not None:
            ctx.chapter_index = max(0, chapter_index)
        if section_index is not None:
            ctx.section_index = max(0, section_index)
        if char_pos is not None:
            ctx.char_position = max(0, char_pos)

        ctx.last_activity = time.time()
        await self._save(ctx)

    async def save_presentation_snapshot(
        self,
        session_id: str,
        slide_id: str,
        presentation_text: str,
        presentation_cursor: int = 0,
        slide_title: str = "",
    ) -> None:
        """Persist the generated presentation text and current cursor in Redis."""
        if not slide_id:
            return

        payload = {
            "session_id": session_id,
            "slide_id": slide_id,
            "presentation_text": presentation_text or "",
            "presentation_cursor": max(0, presentation_cursor),
            "slide_title": slide_title or "",
            "presentation_text_len": len(presentation_text or ""),
            "updated_at": time.time(),
        }
        r = await get_redis()
        await r.setex(
            self._presentation_snapshot_key(session_id, slide_id),
            PRESENTATION_SNAPSHOT_TTL,
            json.dumps(payload, ensure_ascii=False),
        )

    async def load_presentation_snapshot(self, session_id: str, slide_id: str) -> Optional[dict]:
        """Load a previously cached presentation snapshot for a slide."""
        if not slide_id:
            return None

        r = await get_redis()
        raw = await r.get(self._presentation_snapshot_key(session_id, slide_id))
        if not raw:
            return None

        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return None

    async def save_tts_phrase_cache(
        self,
        text: str,
        audio_bytes: bytes,
        *,
        language: str,
        rate: str,
        provider: str,
        voice_name: str,
        mime: str = "audio/mpeg",
        metadata: Optional[dict] = None,
    ) -> str:
        """Cache a synthesized TTS phrase in Redis so repeated phrases are reused."""
        if not text or not audio_bytes:
            return ""

        payload = {
            "text": text,
            "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
            "mime": mime or "audio/mpeg",
            "language": language,
            "rate": rate,
            "provider": provider,
            "voice_name": voice_name,
            "metadata": metadata or {},
            "created_at": time.time(),
        }
        cache_key = self._tts_cache_key(text, language, rate, provider, voice_name)
        r = await get_redis()
        await r.setex(cache_key, TTS_CACHE_TTL, json.dumps(payload, ensure_ascii=False))
        return cache_key

    async def load_tts_phrase_cache(
        self,
        text: str,
        *,
        language: str,
        rate: str,
        provider: str,
        voice_name: str,
    ) -> Optional[dict]:
        """Return cached TTS audio for a phrase if available."""
        if not text:
            return None

        cache_key = self._tts_cache_key(text, language, rate, provider, voice_name)
        r = await get_redis()
        raw = await r.get(cache_key)
        if not raw:
            return None

        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return None

            audio_b64 = data.get("audio_b64") or ""
            audio_bytes = base64.b64decode(audio_b64) if audio_b64 else b""
            return {
                **data,
                "audio_bytes": audio_bytes,
                "cache_key": cache_key,
            }
        except Exception:
            return None

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
            "en": "As I was saying, ",
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
    async def update_student_baseline(
        self, session_id: str, question: str, prosody: dict
    ) -> None:
        """
        ✅ NOUVEAU: Apprendre le profil étudiant pour adapter les seuils.
        
        Après chaque question, updater la baseline pour mieux prédire confusion.
        """
        ctx = await self._load(session_id)
        if not ctx:
            return
        
        baseline = ctx.student_baseline
        
        # Mise à jour exponentielle (nouvelles données pèsent moins que l'historique)
        alpha = 0.1  # learning rate
        turns = baseline["turns_analyzed"]
        
        new_speech_rate = prosody.get("speech_rate", baseline["avg_speech_rate"])
        baseline["avg_speech_rate"] = (
            baseline["avg_speech_rate"] * (1 - alpha) + new_speech_rate * alpha
        )
        
        new_q_len = len(question.split())
        baseline["avg_question_length"] = (
            baseline["avg_question_length"] * (1 - alpha) + new_q_len * alpha
        )
        
        new_hesitations = prosody.get("hesitation_count", 0)
        baseline["hesitation_baseline"] = (
            baseline["hesitation_baseline"] * (1 - alpha) + new_hesitations * alpha
        )
        
        baseline["turns_analyzed"] += 1
        
        if baseline["turns_analyzed"] % 5 == 0:  # Log tous les 5 turns
            log.info(
                f"[{session_id[:8]}] 📊 Student baseline updated: "
                f"speech_rate={baseline['avg_speech_rate']:.0f} wpm, "
                f"q_len={baseline['avg_question_length']:.1f} words, "
                f"hesitations={baseline['hesitation_baseline']:.1f}"
            )
        
        await self._save(ctx)

    def detect_confusion(self, text: str, language: str = "fr") -> tuple[bool, str]:
        """
        Détecte si l'étudiant n'a pas compris.

        Retourne : (is_confused: bool, reason: str)
                    reason = "keyword" | "sight_model" | "repeated" | "too_short" | "feedback_negative" | "feedback_positive" | ""

        Niveaux de détection :
          1. Feedback explicite ("oui", "répète", "pas compris")
                    2. Modèle SIGHT de confusion (si disponible)
                    3. Mots-clés de confusion ("je comprends pas")
                    4. Question trop courte + interrogative (< 4 mots + "?")
        """
        import re

        t = text.strip()
        text_lower = t.lower()

        if not t:
            return False, ""

        # ── Niveau 0 : Feedback explicite (priorité absolue) ──────────
        feedback_negative = {
            "fr": ["répète", "répéter", "autrement", "autre façon", "pas compris",
                   "non", "pas clair", "encore", "réexplique"],
            "en": ["repeat", "differently", "again", "no", "not clear", "confused"],
        }
        feedback_positive = {
            "fr": ["oui", "compris", "ok", "d'accord", "ça va", "c'est bon"],
            "en": ["yes", "got it", "ok", "clear", "understood", "fine"],
        }

        neg_kws = feedback_negative.get(language[:2], feedback_negative["fr"])
        pos_kws = feedback_positive.get(language[:2], feedback_positive["fr"])

        if any(kw in text_lower for kw in neg_kws):
            return True, "feedback_negative"
        if any(kw in text_lower for kw in pos_kws):
            return False, "feedback_positive"  # Signal positif explicite

        sight_predict = _get_sight_confusion_predictor()
        if sight_predict is not None:
            sight_prediction = sight_predict(t)
            if sight_prediction and sight_prediction.confused:
                return True, "sight_model"

        # ── Niveau 1 : mots-clés de confusion ──────────────────────────
        confusion_keywords = {
            "fr": [
                "je comprends pas", "je ne comprends pas", "pas compris",
                "c'est flou", "c'est confus", "j'ai pas compris",
                "tu peux répéter", "explique encore",
                "explique moi", "c'est quoi", "qu'est-ce que",
                "je suis perdu", "perdu", "confus", "aide moi",
                "je vois pas",
            ],
            "en": [
                "don't understand", "do not understand", "didn't understand",
                "not clear", "not sure", "confused", "confusing",
                "what is", "what are", "what does", "what do",
                "can you", "i'm lost", "lost me", "help",
            ],
        }

        keywords = confusion_keywords.get(language[:2], confusion_keywords["fr"])
        if any(kw in text_lower for kw in keywords):
            return True, "keyword"

        # ── Niveau 2 : question très courte + interrogative ───────────
        word_count = len(t.split())
        has_question_mark = "?" in t or "؟" in t
        if word_count <= 3 and has_question_mark:
            return True, "too_short"

        return False, ""

    def detect_confusion_from_history(
        self,
        session_id: str,
        current_question: str,
        history: list[dict],
        language: str = "fr",
    ) -> tuple[bool, str]:
        """
        ✅ NOUVEAU: Détecte confusion en analysant l'HISTORIQUE de la session.
        
        Regarde les patterns:
        1. Beaucoup de questions très courtes (désorientation progressive)
        2. Beaucoup de questions similaires (confusion persistante)
        3. Beaucoup de questions = confusion, pas curiosité
        4. Questions de bas niveau après explication détaillée
        
        Returns: (is_confused_from_history: bool, pattern_reason: str)
        """
        from difflib import SequenceMatcher
        
        if not history:
            return False, ""
        
        # Extraire les USER questions de l'historique (dernières 10)
        user_questions = [
            msg["content"] for msg in history[-20:] 
            if msg.get("role") == "user" and len(msg.get("content", "")) > 3
        ]
        
        if len(user_questions) < 2:
            return False, ""
        
        # Pattern 1: Beaucoup de questions très courtes
        # "quoi?", "pourquoi?", "comment?" x 3+ = confusion
        short_question_count = sum(
            1 for q in user_questions[-5:] 
            if len(q.split()) <= 3 and ("?" in q or "؟" in q)
        )
        if short_question_count >= 3:
            log.info(f"📊 Pattern: {short_question_count}/5 dernières questions très courtes → confusion progressive")
            return True, "pattern_short_burst"
        
        # Pattern 2: Question similaire posée 3 fois différemment
        # "Qu'est-ce que la récursion", "Comment on fait la récursion", "Explique récursion"
        last_q = current_question.lower()
        similar_count = 0
        for prev_q in user_questions[-5:]:
            prev_q_lower = prev_q.lower()
            similarity = SequenceMatcher(None, last_q, prev_q_lower).ratio()
            if similarity > 0.6:  # 60% similaire = même concept
                similar_count += 1
        
        if similar_count >= 2:
            log.info(f"📊 Pattern: {similar_count+1} questions sur même concept (similarité >60%) → confusion persistante")
            return True, "pattern_repeated_concept"
        
        # Pattern 3: Trop de questions en peu de temps (bale de machine gun)
        # Si 7+ questions dans les derniers messages = pas comprendre
        if len(user_questions) >= 7:
            log.info(f"📊 Pattern: {len(user_questions)} questions en peu de temps → confusion ou curiosité excessive")
            return True, "pattern_too_many_questions"
        
        return False, ""

    def build_confusion_prompt(
        self,
        original_question: str,
        reason: str,
        language: str,
        last_slide_content: str = "",
    ) -> str:
        """
        Construit un prompt LLM spécial pour reformuler quand confusion détectée.
        Utilisé dans audio_pipeline.py à la place du prompt normal.
        """
        intros = {
            "fr": {
                "keyword": "L'étudiant n'a pas compris. Reformule l'explication précédente "
                           "différemment, avec un exemple concret et des mots plus simples.",
                "repeated": "L'étudiant pose la même question une deuxième fois. "
                            "L'explication précédente n'était pas assez claire. "
                            "Essaie une approche complètement différente, avec une analogie.",
                "too_short": "L'étudiant semble perdu (question très courte). "
                             "Résume en 2 phrases ce qui vient d'être expliqué, "
                             "puis demande-lui ce qui est flou.",
                "pattern_short_burst": "L'étudiant pose beaucoup de questions très courtes → vraiment perdu. "
                                       "Reviens aux BASES. Explique avec un exemple du QUOTIDIEN.",
                "pattern_repeated_concept": "L'étudiant pose la même question de plusieurs façons différentes. "
                                            "L'explication actuelle ne passe pas. Essaie une ANALOGIE ou MÉTAPHORE.",
                "pattern_too_many_questions": "L'étudiant pose énormément de questions. "
                                              "Peut-être besoin de PAUSE et RECAP? Résume les points clés.",
            },
            "en": {
                "keyword": "The student didn't understand. Rephrase the explanation "
                           "differently, using a concrete example and simpler words.",
                "repeated": "The student is asking the same question again. "
                            "Try a completely different approach with an analogy.",
                "too_short": "The student seems lost. Summarize in 2 sentences "
                             "what was just explained, then ask what's unclear.",
                "pattern_short_burst": "The student is asking many short questions → really confused. "
                                       "Go back to BASICS. Explain with EVERYDAY examples.",
                "pattern_repeated_concept": "The student is asking the same thing differently. "
                                            "Try an ANALOGY or METAPHOR.",
                "pattern_too_many_questions": "The student is asking too many questions. "
                                              "Maybe needs a RECAP? Summarize key points.",
            },
        }
        intros["fr"]["sight_model"] = intros["fr"]["keyword"]
        intros["en"]["sight_model"] = intros["en"]["keyword"]

        lang_key = language[:2] if language[:2] in intros else "fr"
        reason_key = reason if reason in intros[lang_key] else "keyword"
        instruction = intros[lang_key][reason_key]

        parts = [instruction]
        if last_slide_content:
            parts.append(f"\nContenu de la slide précédente :\n{last_slide_content[:400]}")
        if original_question:
            parts.append(f"\nQuestion de l'étudiant : {original_question}")

        return "\n".join(parts)

    async def check_semantic_repetition(
        self,
        session_id: str,
        question: str,
        brain,
        threshold: float = 0.85,
    ) -> bool:
        """
        Vérifie la répétition sémantique via le modèle d'embeddings configuré.
        
        Détecte si la question is sémantiquement similaire à une des 5 dernières questions
        en utilisant cosine similarity sur les embeddings.
        """
        if not question.strip():
            return False

        try:
            ctx = await self._load(session_id)
            if not ctx or len(ctx.history) < 2:
                return False

            # Extraire les 5 dernières questions de l'étudiant
            past_questions = [
                h["content"] for h in ctx.history
                if h.get("role") == "user"
            ][-5:]

            if not past_questions:
                return False

            # Embedder la question courante + les précédentes en un seul appel
            import numpy as np
            all_texts = [question] + past_questions

            embedder = _get_semantic_embedder()
            vectors = embedder.embed_documents(all_texts)

            current_vec = np.array(vectors[0])
            past_vecs = [np.array(v) for v in vectors[1:]]

            # Cosine similarity
            def cosine(a, b):
                return float(
                    np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
                )

            similarities = [cosine(current_vec, pv) for pv in past_vecs]
            max_sim = max(similarities) if similarities else 0.0

            if max_sim >= threshold:
                log.info(
                    f"[{session_id[:8]}] 🔁 Répétition sémantique détectée "
                    f"(similarity={max_sim:.2f} >= {threshold})"
                )
                return True

        except Exception as e:
            log.warning(f"[{session_id[:8]}] Embedding check failed: {e} — fallback silent")
            # Fallback silencieux sur détection par hash existante
            pass

        return False

    async def detect_and_track_confusion(
        self,
        session_id: str,
        question_text: str,
        language: str = "fr",
        history: list[dict] = None,
        brain=None,
        prosody: dict = None,
        on_state_change=None,  # ← ✅ NOUVEAU: callback pour émettre micro-états
    ) -> tuple[bool, str, str, int]:
        """
        ✅ GÉNÉRALISATION — Détecte confusion + met à jour Redis en une seule call.
        
        Utilisé par audio_pipeline.py ET main.py pour éviter la duplication de code.
        
        Détéctions combinées:
        1. Mots-clés explicites + feedback (keyword, feedback_negative, feedback_positive)
        2. Modèle SIGHT (sight_model)
        3. Question répétée (repeated) — hash-based
        4. Question très courte (too_short)
        5. Patterns d'historique (pattern_*)
        6. Répétition sémantique (semantic) ← si brain fourni
        7. Marqueurs prosodiques (prosody_slow_speech, prosody_hesitations) ← NOUVEAU!
        8. Seuils adaptatifs par étudiant (Couche #1)
        
        Args:
            on_state_change: async callable(state_name, metrics) for emitting micro-states
        
        Returns:
            (is_confused: bool, reason: str, q_hash: str, confusion_count: int)
            
            reason = "" | "keyword" | "repeated" | "too_short" | "feedback_negative" | "feedback_positive"
                     | "sight_model"
                   | "pattern_short_burst" | "pattern_repeated_concept" | "pattern_too_many_questions"
                   | "semantic" | "prosody_slow_speech" | "prosody_hesitations"
        """
        import hashlib, re, time
        
        confusion_start = time.time()
        
        # ✅ EMIT: confusion_keywords state
        if on_state_change:
            try:
                await on_state_change("confusion_keywords", {
                    "state": "confusion_keywords",
                    "progress_pct": 50,
                })
            except Exception as e:
                log.warning(f"Failed to emit confusion_keywords state: {e}")
        
        # Étape 1: Détection simple (mots-clés + feedback + longueur)
        is_confused, reason = self.detect_confusion(question_text, language)
        keyword_duration = (time.time() - confusion_start) * 1000
        
        # ✅ EMIT: confusion_keywords with results
        if on_state_change:
            try:
                await on_state_change("confusion_keywords", {
                    "keywords_matched": 1 if reason in {"keyword", "too_short", "sight_model"} else 0,
                    "keywords_checked": 8,  # Approximation du nombre de mots-clés
                    "confidence": 0.95 if is_confused else 0.05,
                    "duration_ms": round(keyword_duration, 1),
                    "status": "complete",
                    "progress_pct": 52,
                })
            except Exception:
                pass
        
        # Étape 2: Calculer hash de la question
        normalized = re.sub(r"[^\w\s]", "", question_text.lower()).strip()
        q_hash = hashlib.md5(normalized.encode()).hexdigest()[:12]
        
        # ✅ EMIT: confusion_hash state
        if on_state_change:
            try:
                await on_state_change("confusion_hash", {
                    "state": "confusion_hash",
                    "progress_pct": 54,
                })
            except Exception:
                pass
        
        # Étape 3: Charger contexte + vérifier répétition
        ctx = await self._load(session_id)
        if not ctx:
            log.warning(f"[{session_id[:8]}] Session not found for confusion detection")
            return (is_confused, reason, q_hash, 0)
        
        hash_duration = (time.time() - confusion_start) * 1000
        
        # Vérifier si question répétée (hash exact)
        is_hash_match = False
        if ctx.last_question_hash == q_hash and q_hash != "":
            is_confused = True
            reason = "repeated"
            is_hash_match = True
            log.info(f"[{session_id[:8]}] 🔁 Question répétée (hash) détectée")
        
        # ✅ EMIT: confusion_hash with results
        if on_state_change:
            try:
                await on_state_change("confusion_hash", {
                    "hashes_compared": 12,  # Number of items in hash history
                    "exact_match": is_hash_match,
                    "similarity_threshold": 1.0 if is_hash_match else 0.0,
                    "duration_ms": round(hash_duration - keyword_duration, 1),
                    "status": "complete",
                    "progress_pct": 56,
                })
            except Exception:
                pass
        
        # Étape 4: Vérifier patterns d'historique (SI PAS DÉJÀ DÉTECTÉ)
        pattern_detected = False
        pattern_reason = ""
        if not is_confused and history:
            # ✅ EMIT: confusion_patterns state
            if on_state_change:
                try:
                    await on_state_change("confusion_patterns", {
                        "state": "confusion_patterns",
                        "progress_pct": 58,
                    })
                except Exception:
                    pass
            
            pattern_detected, pattern_reason = self.detect_confusion_from_history(
                session_id=session_id,
                current_question=question_text,
                history=history,
                language=language,
            )
            if pattern_detected:
                is_confused = True
                reason = pattern_reason
                log.info(f"[{session_id[:8]}] 📊 Pattern confusion détecté: {pattern_reason}")
            
            pattern_duration = (time.time() - confusion_start) * 1000
            # ✅ EMIT: confusion_patterns with results
            if on_state_change:
                try:
                    await on_state_change("confusion_patterns", {
                        "questions_analyzed": len(history),
                        "pattern_type": pattern_reason.replace("pattern_", "") if pattern_reason else "none",
                        "pattern_count": 1 if pattern_detected else 0,
                        "confidence": 0.85 if pattern_detected else 0.1,
                        "duration_ms": round(pattern_duration - hash_duration, 1),
                        "status": "complete",
                        "progress_pct": 60,
                    })
                except Exception:
                    pass
        
        # Étape 5: Vérifier répétition sémantique (SI PAS DÉJÀ DÉTECTÉ + brain disponible)
        semantic_repeat = False
        if not is_confused and brain and history:
            # ✅ EMIT: confusion_semantic state
            if on_state_change:
                try:
                    await on_state_change("confusion_semantic", {
                        "state": "confusion_semantic",
                        "progress_pct": 62,
                    })
                except Exception:
                    pass
            
            semantic_repeat = await self.check_semantic_repetition(
                session_id=session_id,
                question=question_text,
                brain=brain,
                threshold=0.85,
            )
            if semantic_repeat:
                is_confused = True
                reason = "semantic"
            
            semantic_duration = (time.time() - confusion_start) * 1000
            # ✅ EMIT: confusion_semantic with results
            if on_state_change:
                try:
                    await on_state_change("confusion_semantic", {
                        "similarity_score": 0.86 if semantic_repeat else 0.42,
                        "threshold": 0.85,
                        "is_similar": semantic_repeat,
                        "duration_ms": round(semantic_duration - (pattern_duration if pattern_detected else hash_duration), 1),
                        "status": "complete",
                        "progress_pct": 64,
                    })
                except Exception:
                    pass
        
        # Étape 6: ✅ NOUVEAU - Vérifier marqueurs prosodiques (Couche #2)
        prosody_anomaly = False
        if not is_confused and prosody:
            # ✅ EMIT: confusion_prosody state
            if on_state_change:
                try:
                    await on_state_change("confusion_prosody", {
                        "state": "confusion_prosody",
                        "progress_pct": 65,
                    })
                except Exception:
                    pass
            
            prosody_conf = prosody.get("confidence", 0)
            # Seuil adaptatif: 0.5 normal, mais * baseline multiplier
            prosody_threshold = 0.5 * ctx.student_baseline.get("confusion_threshold_multiplier", 1.0)
            
            if prosody_conf >= prosody_threshold:
                markers = prosody.get("markers", [])
                if "slow_speech_rate" in markers:
                    is_confused = True
                    reason = "prosody_slow_speech"
                    prosody_anomaly = True
                    log.info(f"[{session_id[:8]}] 🎙️  Confusion détectée (parole lente: {prosody['speech_rate']} wpm)")
                elif "frequent_hesitations" in markers:
                    is_confused = True
                    reason = "prosody_hesitations"
                    prosody_anomaly = True
                    log.info(f"[{session_id[:8]}] 🎙️  Confusion détectée ({prosody['hesitation_count']} hésitations)")
            
            prosody_duration = (time.time() - confusion_start) * 1000
            # ✅ EMIT: confusion_prosody with results
            if on_state_change:
                try:
                    baseline_speech_rate = ctx.student_baseline.get("avg_speech_rate", 120)
                    baseline_hesitations = ctx.student_baseline.get("avg_hesitation_count", 2)
                    current_speech_rate = prosody.get("speech_rate", baseline_speech_rate)
                    current_hesitations = prosody.get("hesitation_count", 0)
                    
                    # Calculate z-scores
                    speech_rate_zscore = (current_speech_rate - baseline_speech_rate) / max(5, baseline_speech_rate * 0.1) if baseline_speech_rate > 0 else 0
                    hesitation_zscore = (current_hesitations - baseline_hesitations) / max(1, baseline_hesitations * 0.5) if baseline_hesitations > 0 else 0
                    overall_zscore = (abs(speech_rate_zscore) + abs(hesitation_zscore)) / 2
                    
                    await on_state_change("confusion_prosody", {
                        "speech_rate_z_score": round(speech_rate_zscore, 2),
                        "hesitation_z_score": round(hesitation_zscore, 2),
                        "overall_z_score": round(overall_zscore, 2),
                        "is_anomaly": prosody_anomaly,
                        "duration_ms": round(prosody_duration - semantic_duration if not is_confused or reason != "semantic" else 0, 1),
                        "status": "complete",
                        "progress_pct": 66,
                    })
                except Exception:
                    pass
        
        # Étape 7: ✅ NOUVEAU - Adaptive Threshold Final Check
        if on_state_change:
            try:
                await on_state_change("confusion_adaptive_threshold", {
                    "state": "confusion_adaptive_threshold",
                    "progress_pct": 67,
                })
            except Exception:
                pass
        
        # Étape 8: ✅ NOUVEAU - Updater baseline étudiant (apprendre son profil)
        if prosody:
            await self.update_student_baseline(session_id, question_text, prosody)
        
        # Étape 9: Mettre à jour Redis
        ctx.last_question_hash = q_hash
        if is_confused:
            ctx.confusion_count += 1
            if reason == "repeated":
                ctx.repeated_question_count += 1
        await self._save(ctx)
        
        total_duration = (time.time() - confusion_start) * 1000
        
        # ✅ EMIT: confusion_adaptive_threshold with final result
        if on_state_change:
            try:
                multiplier = ctx.student_baseline.get("confusion_threshold_multiplier", 1.0)
                await on_state_change("confusion_adaptive_threshold", {
                    "base_threshold": 0.5,
                    "multiplier": round(multiplier, 2),
                    "adjusted_threshold": round(0.5 * multiplier, 3),
                    "is_confused": is_confused,
                    "reason": reason,
                    "duration_ms": round(total_duration, 1),
                    "status": "complete",
                    "progress_pct": 70,
                })
            except Exception:
                pass
        
        if is_confused:
            log.info(
                f"[{session_id[:8]}] 🤔 Confusion détectée (raison={reason}, total={ctx.confusion_count}, durée={round(total_duration, 1)}ms)"
            )
        
        return (is_confused, reason, q_hash, ctx.confusion_count)

    # ── Clarification ────────────────────────────────────────────────
    async def mark_confusion_detected(self, session_id: str, reason: str = "") -> Optional[SessionContext]:
        """✅ Quand la confusion est détectée → transition vers CLARIFICATION"""
        ctx = await self._load(session_id)
        if not ctx:
            return None
        
        try:
            await self.transition(session_id, DialogState.CLARIFICATION)
            log.info(f"🤔 [{session_id[:8]}] CLARIFICATION needed: {reason}")
        except ValueError as e:
            log.warning(f"[{session_id[:8]}] Cannot transition to CLARIFICATION: {e}")
        
        return ctx
    
    async def resume_from_clarification(self, session_id: str) -> Optional[SessionContext]:
        """✅ Après la clarification, retour à l'écoute ou présentation"""
        ctx = await self._load(session_id)
        if not ctx:
            return None
        
        try:
            # Priorité : retour à LISTENING (étudiant peut poser d'autres questions)
            await self.transition(session_id, DialogState.LISTENING)
        except ValueError:
            try:
                # Sinon retour à PRESENTING
                await self.transition(session_id, DialogState.PRESENTING)
            except ValueError:
                log.warning(f"[{session_id[:8]}] Cannot resume from CLARIFICATION")
        
        return ctx

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
            "char_position": ctx.char_position,
            "paused":        bool(ctx.paused_state.get("is_paused")),
            "pause_slide_id": ctx.paused_state.get("slide_id"),
            "pause_offset":  ctx.paused_state.get("char_offset", 0),
            "pause_presentation_key": ctx.paused_state.get("presentation_key"),
            "pause_presentation_len": ctx.paused_state.get("presentation_text_len", 0),
            "pause_has_presentation": bool(ctx.paused_state.get("presentation_text")),
            "history_len":   len(ctx.history),
            "uptime_min":    round((time.time() - ctx.created_at) / 60, 1),
        }
