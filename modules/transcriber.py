"""Smart Teacher — Speech-to-Text (faster-whisper)"""

import time
import logging
import unicodedata

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

    def validate_audio_quality(self, audio: np.ndarray) -> tuple[bool, str]:
        """Check if audio is completely empty/corrupt.
        ⚠️  VERY RELAXED: Only reject if audio is 100% zeros (not even soft speech)
        Let Whisper handle detection - even whispers should pass through.
        Returns: (is_valid_audio, reason_if_invalid)
        """
        if len(audio) == 0:
            log.warning("❌ Audio validation: empty array")
            return False, "Audio vide"
        
        # Check if audio is ALL zeros (corrupted decode, not soft speech)
        # Use max absolute value instead of RMS to catch completely silent audio
        max_val = np.max(np.abs(audio))
        min_val = np.min(audio)
        mean_val = np.mean(np.abs(audio))
        
        log.info(f"   Audio quality: len={len(audio)} samples, max_abs={max_val:.8f}, min={min_val:.8f}, mean={mean_val:.8f}")
        log.debug(f"   First 30 samples: {audio[:30].tolist()}")
        log.debug(f"   Last 30 samples: {audio[-30:].tolist()}")
        
        # Only reject if max_abs is near-zero = truly no audio
        if max_val < 0.00001:
            log.warning(f"❌ Audio rejected: max_abs={max_val:.8f} (all zeros) - likely WebM container corruption")
            return False, "Audio all zeros"
        
        return True, ""

    def trim_silence(self, audio: np.ndarray, threshold: float = 0.001) -> np.ndarray:
        """Remove silence from beginning/end of audio
        
        ✅ Threshold TRÈS réduit de 0.02 → 0.001 (1000x moins agressif!)
        pour laisser passer même la parole très faible
        """
        above = np.abs(audio) > threshold
        
        # Diagnostic
        above_count = np.sum(above)
        above_pct = (above_count / len(audio)) * 100 if len(audio) > 0 else 0
        log.info(f"   trim_silence: threshold={threshold}, {above_count}/{len(audio)} samples above threshold ({above_pct:.1f}%)")
        
        if not np.any(above):
            log.warning(f"   ⚠️  trim_silence: NO samples above threshold={threshold}! Returning original audio")
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
            log.debug(f"✂️  Silence trimmed: {orig_dur:.1f}s → {trimmed_dur:.1f}s (threshold={threshold})")

        return trimmed

    def extract_prosody(self, text: str, audio_duration: float) -> dict:
        """
        ✅ NOUVEAU (Couche #2): Extraire marqueurs prosodiques de détection de confusion.
        
        Basé sur:
        1. Speech rate (mots par minute vs baseline)
        2. Hesitation words ("euh", "um", "uh", "hein", "bah")
        3. Silence ratio (beaucoup de silence = réflexion lente)
        
        Retourne: dict avec marques de confusion potentielle
        """
        if not text or audio_duration <= 0:
            return {"confidence": 0, "markers": []}
        
        word_count = len(text.split())
        speech_rate = (word_count / audio_duration) * 60 if audio_duration > 0 else 0  # mots/min
        
        # Mots d'hésitation en plusieurs langues
        hesitation_words = {
            "fr": ["euh", "uh", "um", "hum", "heu", "bah", "ben", "disons"],
            "ar": ["ايه", "نعني", "يعني", "حاضر"],  # Common hesitations
            "en": ["um", "uh", "like", "you know", "i mean"],
        }
        
        text_lower = text.lower()
        hesitation_count = 0
        for lang_hes in hesitation_words.values():
            for hes in lang_hes:
                hesitation_count += text_lower.count(hes)
        
        # Silence ratio: Si beaucoup de silence = confusion (arrêts fréquents)
        silence_ratio = 1.0 - (word_count / (audio_duration * 100)) if audio_duration > 0 else 0
        silence_ratio = max(0, min(1.0, silence_ratio))
        
        # Scoring prosody (0-1, higher = more confusion signals)
        markers = []
        confidence_score = 0.0
        
        # Signal 1: Speech rate anormalement lent (< 60 mots/min = réfléchit fort)
        if speech_rate < 60:
            markers.append("slow_speech_rate")
            confidence_score += 0.3
        
        # Signal 2: Hésitations fréquentes
        if hesitation_count > 2:
            markers.append("frequent_hesitations")
            confidence_score += 0.2 * min(1.0, hesitation_count / 5)  # Capped at +0.2
        
        # Signal 3: Beaucoup de silence (réflexion/confusion)
        if silence_ratio > 0.5:
            markers.append("high_silence_ratio")
            confidence_score += 0.2
        
        return {
            "speech_rate": round(speech_rate, 1),
            "hesitation_count": hesitation_count,
            "silence_ratio": round(silence_ratio, 2),
            "markers": markers,
            "confidence": round(min(1.0, confidence_score), 2),  # 0-1 score
        }

    def transcribe(self, audio: np.ndarray, force_language: str = None) -> tuple[str, float, str, float, float]:
        """Transcribe audio array to text. Returns: (text, stt_time, language, lang_prob, audio_duration)
        
        Args:
            audio: Audio samples
            force_language: If set (e.g. 'en', 'fr'), use this instead of auto-detection
        """
        start = time.time()
        log.info(f"🎤 STT START: len={len(audio)} samples, force_lang={force_language}")

        try:
            # 1. VALIDATION: Basic sanity check on audio (very relaxed)
            is_valid, reason = self.validate_audio_quality(audio)
            if not is_valid:
                log.warning(f"❌ Audio validation failed: {reason}")
                return "", 0.0, "silence", 0.0, len(audio) / Config.SAMPLE_RATE

            # 2. Suppression silences
            orig_len = len(audio)
            audio = self.trim_silence(audio)
            audio_duration = len(audio) / Config.SAMPLE_RATE
            log.info(f"   After trim_silence: {orig_len} → {len(audio)} samples ({audio_duration:.3f}s)")
            
            # Extra diagnostic: After trim_silence, verify we still have audio
            if len(audio) > 0:
                max_val_after = np.max(np.abs(audio))
                log.info(f"   After trim: max_abs={max_val_after:.8f}, min={np.min(audio):.8f}, mean={np.mean(np.abs(audio)):.8f}")

            # 3. Audio trop court → ignorer
            if audio_duration < Config.STT_MIN_AUDIO_SEC:
                log.warning(f"❌ Audio too short: {audio_duration:.3f}s < {Config.STT_MIN_AUDIO_SEC}s min")
                return "", 0.0, "unknown", 0.0, audio_duration
            
            log.info(f"   ✅ Audio OK: {len(audio)} samples ({audio_duration:.3f}s) ready for Whisper")
            log.debug(f"   Audio samples: min={audio.min():.8f}, max={audio.max():.8f}, mean={audio.mean():.8f}")

            # 4. Transcription Whisper
            log.info(f"   → Calling Whisper.transcribe(vad_filter=False, language={force_language})")
            segments, info = self.model.transcribe(
                audio,
                language=force_language,          # ← Peut être force 'en', 'fr' si besoin
                beam_size=Config.STT_BEAM_SIZE,
                best_of=1,
                temperature=0.0,                  # déterministe
                vad_filter=False,                 # ✅ DÉSACTIVER VAD agressif (filtre toute la parole!)
                # ✅ ALTERNATIVEMENT: VAD avec paramètres moins agressifs:
                # vad_filter=True,
                # vad_parameters=dict(
                #     min_speech_duration_ms=100,   # Au minimum 100ms de parole
                #     min_silence_duration_ms=1500, # Besoin de 1.5s de silence (par défaut 2s, très strict)
                #     speech_pad_ms=300,            # Padding 300ms (par défaut 400ms)
                # ),
                condition_on_previous_text=False, # pas de mémoire → évite hallucinations
                without_timestamps=True,
                word_timestamps=False,
            )

            # ⚠️  CRITICAL: segments is a GENERATOR, convert to list immediately!
            segments = list(segments)
            log.info(f"   Whisper returned {len(segments)} segments")
            
            # 5. Fusion des segments
            text = " ".join(s.text.strip() for s in segments).strip()
            log.info(f"   Whisper raw output: '{text[:100]}'... ({len(segments)} segments)")

            lang      = getattr(info, "language",             "unknown")
            lang_prob = getattr(info, "language_probability", 0.0)
            stt_time  = time.time() - start

            # 6. REJECTION: Only detect clear Unicode corruption (language-aware)
            # ✅ Skip corruption check for RTL languages where ALL chars are > 0x180
            # This prevents rejecting valid Arabic, Farsi, Hebrew, etc.
            
            # Check if detected language is RTL (Arabic, Farsi, Hebrew, etc.)
            rtl_languages = ['ar', 'fa', 'ps', 'ur', 'he', 'yi']  # Arabic, Farsi, Pashto, Urdu, Hebrew, Yiddish
            is_rtl_language = lang.lower()[:2] in rtl_languages if lang and lang != "unknown" else False
            
            if not is_rtl_language and len(text) > 5:
                # For non-RTL languages, check for Unicode control/format characters (actual corruption)
                # These are actual invalid characters, not just non-ASCII
                invalid_categories = {'Cc', 'Cf', 'Cn', 'Co'}  # Control, Format, Not assigned, Private use
                invalid_char_count = sum(
                    1 for c in text
                    if unicodedata.category(c) in invalid_categories
                )
                
                # Only reject if > 30% of text is actual control/format characters
                if len(text) > 0 and invalid_char_count / len(text) > 0.3:
                    log.warning(f"🚨 STT Corruption: {invalid_char_count}/{len(text)} invalid Unicode chars, rejecting")
                    return "", stt_time, lang, lang_prob, audio_duration
            elif is_rtl_language:
                log.info(f"✅ RTL language detected ({lang}) — skipping corruption check")
            
            rtf = stt_time / audio_duration if audio_duration > 0 else 0
            log.info(
                f"STT | '{text[:60]}…' | lang={lang}({lang_prob:.0%}) "
                f"| dur={audio_duration:.2f}s | stt={stt_time:.2f}s | RTF={rtf:.2f}x"
            )
            return text, stt_time, lang, lang_prob, audio_duration

        except Exception as exc:
            log.error(f"❌ Transcription error: {exc}")
            return "", time.time() - start, "error", 0.0, 0.0