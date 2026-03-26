"""
╔══════════════════════════════════════════════════════════════════════╗
║           SMART TEACHER — Module TTS (Text-to-Speech)              ║
║                                                                      ║
║  Fournit Edge-TTS (gratuit, Microsoft Neural) par défaut            ║
║  + ElevenLabs (optionnel, meilleure qualité)                        ║
║                                                                      ║
║  AMÉLIORATIONS vs version initiale :                                 ║
║    ✅ Sélection automatique du provider selon Config.TTS_PROVIDER   ║
║    ✅ Voix enrichies : 4 langues, 2 voix par langue (homme/femme)   ║
║    ✅ Fallback automatique Edge → si ElevenLabs échoue              ║
║    ✅ Interface unifiée : generate_audio_async() pour les deux       ║
║    ✅ Logs structurés avec timings                                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
import re
import time

import edge_tts

from config import Config

log = logging.getLogger("SmartTeacher.TTS")

# ── Table de voix Edge-TTS (2 genres par langue) ───────────────────────────────
EDGE_VOICES: dict[str, dict[str, str]] = {
    "fr": {
        "female": "fr-FR-DeniseNeural",
        "male":   "fr-FR-HenriNeural",
    },
    "ar": {
        "female": "ar-SA-ZariyahNeural",
        "male":   "ar-SA-HamedNeural",
    },
    "en": {
        "female": "en-US-JennyNeural",
        "male":   "en-US-GuyNeural",
    },
    "tr": {
        "female": "tr-TR-EmelNeural",
        "male":   "tr-TR-AhmetNeural",
    },
}
DEFAULT_VOICE = "en-US-JennyNeural"


class VoiceEngine:
    """
    Moteur TTS unifié (Edge-TTS ou ElevenLabs).

    Utilisation :
        voice = VoiceEngine()
        audio_bytes, tts_time, engine, voice_name, mime = \
            await voice.generate_audio_async("Bonjour !", language_code="fr")
    """

    def __init__(self):
        self.provider = Config.TTS_PROVIDER   # "edge" | "elevenlabs"
        self.gender   = "female"              # "female" | "male"
        self.voice_name = DEFAULT_VOICE

        # Compatibilité avec l'ancienne API (voice_id)
        self.voice_id = DEFAULT_VOICE

        # ElevenLabs (optionnel)
        self._el_client = None
        if self.provider == "elevenlabs":
            self._init_elevenlabs()

        log.info(f"✅ TTS provider: {self.provider}")

    # ── Initialisation ElevenLabs ─────────────────────────────────────
    def _init_elevenlabs(self):
        if not Config.ELEVENLABS_API_KEY:
            log.warning("⚠️  ELEVENLABS_API_KEY absent — fallback sur Edge-TTS")
            self.provider = "edge"
            return
        try:
            from elevenlabs.client import ElevenLabs
            self._el_client = ElevenLabs(api_key=Config.ELEVENLABS_API_KEY)
            log.info("✅ ElevenLabs connecté")
        except Exception as exc:
            log.warning(f"⚠️  ElevenLabs init failed ({exc}) — fallback sur Edge-TTS")
            self.provider = "edge"

    # ── Sélection de voix ─────────────────────────────────────────────
    def select_voice(self, index: int = 0, gender: str = "female"):
        """Sélectionne le genre de voix (female/male). Compatible ancienne API."""
        self.gender = gender
        log.info(f"TTS voice gender: {gender}")

    def set_voice(self, voice_id: str, voice_name: str | None = None):
        """Force une voix spécifique par ID (Edge ou ElevenLabs)."""
        self.voice_id   = voice_id
        self.voice_name = voice_name or voice_id
        log.info(f"TTS voice set: {self.voice_name}")

    def get_available_voices(self) -> list[dict]:
        voices = []
        for lang, genders in EDGE_VOICES.items():
            for g, name in genders.items():
                voices.append({"id": name, "name": name, "lang": lang, "gender": g})
        return voices

    # ── Interface principale ──────────────────────────────────────────
    async def generate_audio_async(
        self,
        text: str,
        language_code: str | None = None,
        rate: str = "+0%",
    ) -> tuple[bytes | None, float, str, str, str | None]:
        """
        Génère l'audio TTS pour le texte donné.

        Args:
            text:          Texte à synthétiser
            language_code: Code de langue ("fr", "ar", "en", "tr")
            rate:          Vitesse de parole Edge-TTS (ex: "-15%", "+10%")

        Returns:
            (audio_bytes, tts_time, engine_name, voice_name, mime_type)
        """
        if not text or len(text.strip()) < 2:
            return None, 0.0, "none", "none", None

        safe_rate = self._sanitize_rate(rate)

        if self.provider == "elevenlabs" and self._el_client:
            result = await self._elevenlabs(text, language_code, safe_rate)
            if result[0] is not None:
                return result
            log.warning("ElevenLabs failed — fallback Edge-TTS")

        return await self._edge(text, language_code, safe_rate)

    # ── Edge-TTS ──────────────────────────────────────────────────────
    async def _edge(
        self,
        text: str,
        language_code: str | None,
        rate: str,
    ) -> tuple[bytes | None, float, str, str, str]:
        voice = self._pick_edge_voice(language_code)
        start = time.time()
        try:
            communicate  = edge_tts.Communicate(text=text, voice=voice, rate=rate)
            audio_bytes  = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]

            tts_time = time.time() - start
            log.info(f"TTS Edge | {tts_time:.2f}s | {voice} | rate={rate} | {len(audio_bytes)} bytes")
            return audio_bytes, tts_time, "edge_tts", voice, "audio/mpeg"

        except Exception as exc:
            log.error(f"❌ Edge-TTS error: {exc}")
            return None, 0.0, "none", "none", None

    # ── ElevenLabs ────────────────────────────────────────────────────
    async def _elevenlabs(
        self,
        text: str,
        language_code: str | None,
        rate: str,
    ) -> tuple[bytes | None, float, str, str, str | None]:
        # Voix ElevenLabs par langue (IDs publics)
        EL_VOICES = {
            "fr": "pNInz6obpgDQGcFmaJgB",  # Adam
            "ar": "EXAVITQu4vr4xnSDxMaL",  # Sarah
            "en": "21m00Tcm4TlvDq8ikWAM",  # Rachel
        }
        lang    = (language_code or "en")[:2].lower()
        voice_id = EL_VOICES.get(lang, EL_VOICES["en"])

        start = time.time()
        try:
            import asyncio
            audio_bytes = await asyncio.to_thread(
                self._el_generate_sync, text, voice_id
            )
            tts_time = time.time() - start
            log.info(
                f"TTS ElevenLabs | {tts_time:.2f}s | {voice_id} | "
                f"rate_hint={rate} (not supported) | {len(audio_bytes)} bytes"
            )
            return audio_bytes, tts_time, "elevenlabs", voice_id, "audio/mpeg"

        except Exception as exc:
            log.error(f"❌ ElevenLabs error: {exc}")
            return None, 0.0, "none", "none", None

    def _el_generate_sync(self, text: str, voice_id: str) -> bytes:
        """Appel synchrone ElevenLabs (exécuté dans un thread)."""
        audio_iter = self._el_client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=Config.TTS_MODEL,
            output_format=Config.TTS_OUTPUT_FORMAT,
        )
        return b"".join(audio_iter)

    # ── Utilitaires ───────────────────────────────────────────────────
    def _pick_edge_voice(self, language_code: str | None) -> str:
        lang = (language_code or "en")[:2].lower()
        lang_voices = EDGE_VOICES.get(lang, EDGE_VOICES["en"])
        return lang_voices.get(self.gender, lang_voices["female"])

    def _sanitize_rate(self, rate: str | None) -> str:
        """
        Valide/sécurise le format de vitesse Edge-TTS.
        Edge attend une chaîne du type '-20%' ou '+15%'.
        """
        if not rate:
            return "+0%"
        value = str(rate).strip()
        if re.fullmatch(r"[+-]\d{1,3}%", value):
            return value
        return "+0%"

    def speak_local(self, text: str, language_code: str | None = None) -> float:
        """Version synchrone pour tests locaux (ne stream pas vers le navigateur)."""
        import asyncio
        _, tts_time, *_ = asyncio.run(self.generate_audio_async(text, language_code))
        return tts_time
