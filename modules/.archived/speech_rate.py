"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Adaptation Débit Vocal                      ║
║                                                                      ║
║  Adapte dynamiquement la vitesse et le style de parole :            ║
║    - Vitesse selon le niveau (collège=0.85x, lycée=1.0x, univ=1.1x)║
║    - Ralentissement automatique après confusion détectée            ║
║    - Accentuation des points importants (emphase TTS)               ║
║    - Pauses naturelles entre concepts                               ║
║    - Adaptation Edge-TTS : rate, pitch, volume                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("SmartTeacher.SpeechRate")


@dataclass
class SpeechConfig:
    """Configuration complète de la parole pour Edge-TTS."""
    rate:   str  = "+0%"      # Edge-TTS: -50% à +100%
    pitch:  str  = "+0Hz"     # Edge-TTS: -200Hz à +200Hz
    volume: str  = "+0%"      # Edge-TTS: -100% à +100%
    voice:  Optional[str] = None  # Forcer une voix spécifique

    def to_edge_tts_kwargs(self) -> dict:
        return {"rate": self.rate, "pitch": self.pitch, "volume": self.volume}


class SpeechRateAdapter:
    """
    Adapte la configuration vocale selon le profil étudiant.
    Compatible Edge-TTS et ElevenLabs.
    """

    # Configs de base par niveau
    LEVEL_CONFIGS = {
        "collège":     SpeechConfig(rate="-15%", pitch="+0Hz"),
        "lycée":       SpeechConfig(rate="+0%",  pitch="+0Hz"),
        "université":  SpeechConfig(rate="+10%", pitch="-10Hz"),
    }

    # Bonus si confusion détectée
    CONFUSION_SLOWDOWN = ["+0%", "-5%", "-10%", "-15%", "-20%", "-25%"]

    # Voix par langue et niveau
    VOICE_MAP = {
        "fr": {
            "lycée":      "fr-FR-DeniseNeural",
            "collège":    "fr-FR-DeniseNeural",
            "université": "fr-FR-HenriNeural",
        },
        "ar": {
            "lycée":      "ar-SA-ZariyahNeural",
            "collège":    "ar-SA-ZariyahNeural",
            "université": "ar-SA-HamedNeural",
        },
        "en": {
            "lycée":      "en-US-JennyNeural",
            "collège":    "en-US-JennyNeural",
            "université": "en-US-GuyNeural",
        },
    }

    def get_config(self, language: str = "fr", level: str = "lycée",
                   confusion_count: int = 0, asks_repeat: int = 0) -> SpeechConfig:
        """
        Retourne la config vocale adaptée.
        Plus de confusions → parle plus lentement.
        """
        base_cfg = self.LEVEL_CONFIGS.get(level, self.LEVEL_CONFIGS["lycée"])

        # Calcul du ralentissement
        slow_idx = min(confusion_count + asks_repeat // 2, len(self.CONFUSION_SLOWDOWN) - 1)
        base_rate_pct = self._parse_rate(base_cfg.rate)
        slow_pct      = self._parse_rate(self.CONFUSION_SLOWDOWN[slow_idx])
        final_rate_pct = base_rate_pct + slow_pct

        cfg = SpeechConfig(
            rate   = f"{final_rate_pct:+d}%",
            pitch  = base_cfg.pitch,
            volume = base_cfg.volume,
            voice  = self.VOICE_MAP.get(language[:2], {}).get(level),
        )

        if confusion_count > 0 or asks_repeat > 0:
            log.info("🐢 Débit adapté: %s (confusion=%d, repeat=%d)",
                     cfg.rate, confusion_count, asks_repeat)

        return cfg

    def _parse_rate(self, rate_str: str) -> int:
        """Parse '+15%' → 15, '-10%' → -10, '+0%' → 0"""
        m = re.match(r'([+-]?\d+)%', rate_str)
        return int(m.group(1)) if m else 0

    def apply_emphasis(self, text: str, language: str = "fr") -> str:
        """
        Ajoute des balises SSML pour accentuer les points importants.
        Détecte les termes entre guillemets, les définitions, etc.
        """
        # Termes entre guillemets → emphasis
        text = re.sub(
            r'[«»""]([^«»""]+)[«»""]',
            r'<emphasis level="moderate">\1</emphasis>',
            text
        )
        # Mots-clés pédagogiques → emphase forte
        keywords = {
            "fr": ["important", "retenir", "essentiel", "clé", "définition", "attention"],
            "en": ["important", "remember", "key", "definition", "note", "essential"],
            "ar": ["مهم", "تذكر", "أساسي", "تعريف"],
            "tr": ["önemli", "hatırla", "anahtar", "tanım"],
        }
        lang = language[:2].lower()
        for kw in keywords.get(lang, keywords["fr"]):
            text = re.sub(
                rf'\b({kw})\b',
                r'<emphasis level="strong">\1</emphasis>',
                text, flags=re.IGNORECASE
            )
        return text

    def add_pauses(self, text: str, pause_ms: int = 400) -> str:
        """
        Ajoute des pauses naturelles entre les phrases et après les virgules.
        Compatible SSML Edge-TTS.
        """
        # Pause après point
        text = re.sub(r'\. ', f'. <break time="{pause_ms}ms"/> ', text)
        # Pause après point d'interrogation/exclamation
        text = re.sub(r'([?!]) ', rf'\1 <break time="{pause_ms + 200}ms"/> ', text)
        # Petite pause après virgule
        text = re.sub(r', ', f', <break time="150ms"/> ', text)
        # Pause après "À retenir :", "Par exemple :"
        text = re.sub(
            r'(À retenir|Par exemple|En résumé|Pour rappel|Attention) :',
            r'\1 : <break time="600ms"/>',
            text
        )
        return text

    def wrap_ssml(self, text: str, config: SpeechConfig) -> str:
        """
        Encapsule le texte en SSML complet pour Edge-TTS.
        """
        body = self.add_pauses(text)
        return (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="fr-FR">'
            f'<prosody rate="{config.rate}" pitch="{config.pitch}" volume="{config.volume}">'
            f'{body}'
            f'</prosody></speak>'
        )

    def format_for_tts(self, text: str, language: str = "fr",
                       level: str = "lycée", confusion_count: int = 0,
                       asks_repeat: int = 0, use_ssml: bool = True) -> tuple[str, SpeechConfig]:
        """
        Prépare le texte pour TTS avec config adaptée.
        Retourne (texte_formaté, config).
        """
        cfg = self.get_config(language, level, confusion_count, asks_repeat)

        if use_ssml:
            text_with_emphasis = self.apply_emphasis(text, language)
            formatted = self.wrap_ssml(text_with_emphasis, cfg)
        else:
            formatted = text

        return formatted, cfg


# Singleton
_adapter: Optional[SpeechRateAdapter] = None

def get_speech_adapter() -> SpeechRateAdapter:
    global _adapter
    if _adapter is None:
        _adapter = SpeechRateAdapter()
    return _adapter
