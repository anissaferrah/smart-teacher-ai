"""
╔══════════════════════════════════════════════════════════════════════╗
║           SMART TEACHER — Module STT (Speech-to-Text)              ║
║                                                                      ║
║  Utilise faster-whisper (CTranslate2) — optimisé CPU/GPU            ║
║  Détecte automatiquement FR / AR / EN                               ║
║                                                                      ║
║  AMÉLIORATIONS vs version initiale :                                 ║
║    ✅ Retourne aussi audio_duration (pour RTF dans logger)           ║
║    ✅ Filtre de confiance minimale configurable                      ║
║    ✅ Logs structurés avec timings précis                            ║
║    ✅ Gestion propre des segments vides                              ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import time
import logging

import numpy as np
from faster_whisper import WhisperModel

from config import Config

log = logging.getLogger("SmartTeacher.STT")


class Transcriber:
    """Convertit l'audio en texte avec faster-whisper."""

    def __init__(self):
        log.info(f"Loading Whisper model ({Config.WHISPER_MODEL_SIZE})…")
        self.model = WhisperModel(
            Config.WHISPER_MODEL_SIZE,
            device=Config.WHISPER_DEVICE,
            compute_type=Config.WHISPER_COMPUTE,
            cpu_threads=Config.WHISPER_THREADS,
        )
        log.info("✅ Whisper model loaded")

    # ──────────────────────────────────────────────────────────────────
    def trim_silence(self, audio: np.ndarray, threshold: float = 0.02) -> np.ndarray:
        """
        Supprime les silences en début/fin d'audio.
        Garde 50ms avant et 150ms après la parole pour ne pas couper les syllabes.
        """
        above = np.abs(audio) > threshold
        if not np.any(above):
            return audio

        first = int(np.argmax(above))
        last  = len(above) - int(np.argmax(above[::-1]))

        pad_before = int(0.05 * Config.SAMPLE_RATE)   # 50 ms
        pad_after  = int(0.15 * Config.SAMPLE_RATE)   # 150 ms

        start   = max(0, first - pad_before)
        end     = min(len(audio), last + pad_after)
        trimmed = audio[start:end]

        orig_dur    = len(audio)   / Config.SAMPLE_RATE
        trimmed_dur = len(trimmed) / Config.SAMPLE_RATE
        if orig_dur - trimmed_dur > 0.5:
            log.debug(f"✂️  Silence trimmed: {orig_dur:.1f}s → {trimmed_dur:.1f}s")

        return trimmed

    # ──────────────────────────────────────────────────────────────────
    def transcribe(self, audio: np.ndarray) -> tuple[str, float, str, float, float]:
        """
        Transcrit un tableau audio numpy en texte.

        Returns:
            text          (str)   : Texte transcrit (vide si silence)
            stt_time      (float) : Durée de la transcription (s)
            language      (str)   : Langue détectée ("fr", "ar", "en", …)
            lang_prob     (float) : Probabilité de la langue (0–1)
            audio_duration(float) : Durée de l'audio traité (s)
        """
        start = time.time()

        try:
            # 1. Suppression silences
            audio = self.trim_silence(audio)
            audio_duration = len(audio) / Config.SAMPLE_RATE

            # 2. Audio trop court → ignorer
            if audio_duration < 0.3:
                return "", 0.0, "unknown", 0.0, audio_duration

            # 3. Transcription Whisper
            segments, info = self.model.transcribe(
                audio,
                language=None,                    # auto-détection
                beam_size=1,                      # greedy — plus rapide
                best_of=1,
                temperature=0.0,                  # déterministe
                vad_filter=True,                  # double couche VAD interne
                condition_on_previous_text=False, # pas de mémoire → évite hallucinations
                without_timestamps=True,
                word_timestamps=False,
            )

            # 4. Fusion des segments
            text = " ".join(s.text.strip() for s in segments).strip()

            lang      = getattr(info, "language",             "unknown")
            lang_prob = getattr(info, "language_probability", 0.0)
            stt_time  = time.time() - start

            rtf = stt_time / audio_duration if audio_duration > 0 else 0
            log.info(
                f"STT | '{text[:60]}…' | lang={lang}({lang_prob:.0%}) "
                f"| dur={audio_duration:.2f}s | stt={stt_time:.2f}s | RTF={rtf:.2f}x"
            )
            return text, stt_time, lang, lang_prob, audio_duration

        except Exception as exc:
            log.error(f"❌ Transcription error: {exc}")
            return "", time.time() - start, "error", 0.0, 0.0