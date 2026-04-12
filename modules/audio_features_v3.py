"""
╔══════════════════════════════════════════════════════════════════════╗
║  AUDIO FEATURES — VERSION 3 OPTIMALE (Hybrid V1 + V2)              ║
║                                                                      ║
║  Union des meilleures features de V1 et V2:                         ║
║  • Dataclass flat (V2) + features riches (V1)                       ║
║  • Historique roulant + tendances (V2)                              ║
║  • Vibrato, delta MFCC, speech_rate riche (V1)                      ║
║  • PCM + WAV support (V2)                                           ║
║                                                                      ║
║  Production-ready pour Phase 4 (Confusion Detector)                 ║
║                                                                      ║
║  Usage:                                                              ║
║    pipeline = AudioFeaturePipeline(redis_client)                    ║
║    features = await pipeline.process(session_id, audio_bytes)       ║
║    aggregated = await pipeline.store.get_aggregated(session_id)     ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import io
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Optional

import librosa
import numpy as np
import redis.asyncio as aioredis
from scipy import signal

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  DATACLASS — FLAT BUT RICH (V2 structure + V1 features)
# ══════════════════════════════════════════════════════════════════════

@dataclass
class AudioFeatures:
    """
    Vecteur complet de features prosodiques.

    Optimisé pour:
    • Sérialisation Redis (flat structure)
    • Phase 4 Confusion Detection (features riches)
    • Tendance temporelle (historique)
    """

    # ─────────────────────────────────────────────────────────────────
    # MFCC — Timbre & Qualité Vocale (V1 enrichi)
    # ─────────────────────────────────────────────────────────────────
    mfcc_mean: list[float]          # [13] — moyenne coefficients
    mfcc_std: list[float]           # [13] — variabilité
    mfcc_delta_mean: list[float]    # [13] — vitesse change (V1 addition)
    mfcc_delta2_mean: list[float]   # [13] — accélération (V1 addition)

    # ─────────────────────────────────────────────────────────────────
    # PITCH — Intonation & Émotion (V1 enrichi)
    # ─────────────────────────────────────────────────────────────────
    pitch_mean: float               # Hz moyen (adulte: 85-255 Hz)
    pitch_std: float                # Variance → instabilité/hésitation
    pitch_min: float                # Fréquence min
    pitch_max: float                # Fréquence max
    vibrato_rate: Optional[float]   # Hz oscillation (V1 addition — émotion)
    vibrato_extent: Optional[float] # Semitones amplitude (V1 addition)

    # ─────────────────────────────────────────────────────────────────
    # SPEECH RATE — Débit Parole (V1 enrichi)
    # ─────────────────────────────────────────────────────────────────
    speech_rate_wpm: float          # Words per minute (V1 addition)
    speech_rate_phonemes_per_sec: float  # Phonemes/sec (V1 addition)
    articulation_rate: float        # Vitesse articulation pure (V1 addition)

    # ─────────────────────────────────────────────────────────────────
    # LOUDNESS — Énergie & Dynamique (V1 enrichi)
    # ─────────────────────────────────────────────────────────────────
    rms_mean: float                 # Volume moyen
    rms_std: float                  # Variabilité énergie
    rms_max: float                  # Peak loudness (V1 addition)
    dynamic_range: float            # Max-min energy (V1 addition)

    # ─────────────────────────────────────────────────────────────────
    # PAUSES — Structure Temporelle (V2 optimized)
    # ─────────────────────────────────────────────────────────────────
    pause_ratio: float              # Proportion silence (0-1)
    pause_count: int                # Nombre de pauses distinctes
    mean_pause_duration: float      # Durée moyenne pauses (sec)
    max_pause_duration: float       # Pause la plus longue (sec) (V1 addition)

    # ─────────────────────────────────────────────────────────────────
    # MÉTADONNÉES
    # ─────────────────────────────────────────────────────────────────
    duration_seconds: float
    timestamp: float                # Unix timestamp


# ══════════════════════════════════════════════════════════════════════
#  EXTRACTEUR (V1 methods + V2 structure)
# ══════════════════════════════════════════════════════════════════════

class AudioFeatureExtractor:
    """
    Extraction complète des features prosodiques depuis audio brut.

    Combine V1 richesse + V2 pragmatisme.
    """

    def __init__(
        self,
        n_mfcc: int = 13,
        frame_length: int = 2048,
        hop_length: int = 512,
        vad_threshold_percentile: float = 10.0,
        min_pause_duration: float = 0.15,
    ):
        self.n_mfcc = n_mfcc
        self.frame_length = frame_length
        self.hop_length = hop_length
        self.vad_threshold_percentile = vad_threshold_percentile
        self.min_pause_duration = min_pause_duration

    def extract_from_bytes(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
        encoding: str = "pcm_s16le",
    ) -> Optional[AudioFeatures]:
        """
        Extrait depuis bytes bruts (PCM ou WAV).

        Args:
            audio_bytes: buffer audio
            sample_rate: fréquence (défaut Whisper: 16000)
            encoding: 'pcm_s16le' ou 'wav'
        """
        try:
            if encoding == "pcm_s16le":
                # Int16 → float32 [-1, 1]
                audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
                audio_array /= 32768.0
                y = audio_array
                sr = sample_rate
            elif encoding == "wav":
                y, sr = librosa.load(io.BytesIO(audio_bytes), sr=sample_rate, mono=True)
            else:
                raise ValueError(f"Encoding non supporté: {encoding}")

            return self._extract(y, sr)

        except Exception as e:
            logger.error(f"extract_from_bytes: {e}", exc_info=True)
            return None

    def _extract(self, y: np.ndarray, sr: int) -> AudioFeatures:
        """Pipeline principal d'extraction."""

        duration = len(y) / sr

        # ─────────────────────────────────────────────────────────────
        # 1. MFCC + Delta (V1 complete)
        # ─────────────────────────────────────────────────────────────
        mfcc = librosa.feature.mfcc(
            y=y, sr=sr,
            n_mfcc=self.n_mfcc,
            n_fft=self.frame_length,
            hop_length=self.hop_length,
        )
        mfcc_mean = mfcc.mean(axis=1).tolist()
        mfcc_std = mfcc.std(axis=1).tolist()

        # Delta (vitesse change MFCC)
        mfcc_delta = librosa.feature.delta(mfcc)
        mfcc_delta_mean = mfcc_delta.mean(axis=1).tolist()

        # Delta2 (accélération)
        mfcc_delta2 = librosa.feature.delta(mfcc, order=2)
        mfcc_delta2_mean = mfcc_delta2.mean(axis=1).tolist()

        # ─────────────────────────────────────────────────────────────
        # 2. PITCH + Vibrato (V1 complete)
        # ─────────────────────────────────────────────────────────────
        f0, voiced_flag, voiced_probs = librosa.pyin(
            y,
            fmin=librosa.note_to_hz("C2"),
            fmax=librosa.note_to_hz("C7"),
            sr=sr,
            hop_length=self.hop_length,
        )

        voiced_f0 = f0[voiced_flag & (f0 > 0)]
        if len(voiced_f0) > 0:
            pitch_mean = float(np.mean(voiced_f0))
            pitch_std = float(np.std(voiced_f0))
            pitch_min = float(np.min(voiced_f0))
            pitch_max = float(np.max(voiced_f0))

            # Vibrato detection (V1 feature)
            vibrato_rate, vibrato_extent = self._detect_vibrato(f0_voiced=voiced_f0)
        else:
            pitch_mean = pitch_std = pitch_min = pitch_max = 0.0
            vibrato_rate = vibrato_extent = None

        # ─────────────────────────────────────────────────────────────
        # 3. RMS ENERGY + Dynamic Range (V1 complete)
        # ─────────────────────────────────────────────────────────────
        rms = librosa.feature.rms(
            y=y,
            frame_length=self.frame_length,
            hop_length=self.hop_length,
        )[0]
        rms_mean = float(np.mean(rms))
        rms_std = float(np.std(rms))
        rms_max = float(np.max(rms))
        rms_min = float(np.min(rms))
        dynamic_range = rms_max - rms_min

        # ─────────────────────────────────────────────────────────────
        # 4. PAUSES (V2 optimized + V1 max)
        # ─────────────────────────────────────────────────────────────
        threshold = np.percentile(rms, self.vad_threshold_percentile)
        is_pause = rms < threshold

        frame_duration = self.hop_length / sr
        pause_durations = []
        in_pause = False
        current_pause_frames = 0

        for frame_is_pause in is_pause:
            if frame_is_pause:
                in_pause = True
                current_pause_frames += 1
            else:
                if in_pause and current_pause_frames * frame_duration >= self.min_pause_duration:
                    pause_durations.append(current_pause_frames * frame_duration)
                in_pause = False
                current_pause_frames = 0

        if in_pause and current_pause_frames * frame_duration >= self.min_pause_duration:
            pause_durations.append(current_pause_frames * frame_duration)

        total_pause_duration = sum(pause_durations)
        pause_ratio = total_pause_duration / max(duration, 0.001)
        pause_count = len(pause_durations)
        mean_pause_duration = float(np.mean(pause_durations)) if pause_durations else 0.0
        max_pause_duration = float(np.max(pause_durations)) if pause_durations else 0.0

        # ─────────────────────────────────────────────────────────────
        # 5. SPEECH RATE (V1 complete — much richer than V2)
        # ─────────────────────────────────────────────────────────────
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onsets = librosa.onset.onset_detect(onset_env=onset_env, sr=sr)

        if len(onsets) > 0 and duration > 0:
            phonemes_per_sec = len(onsets) / duration
            # Approximation: 1 mot ≈ 1.5 syllables
            words_per_min = (len(onsets) / 1.5) * 60 / duration
            # Articulation rate (débit pur sans pauses)
            voiced_ratio = np.sum(voiced_flag) / max(len(voiced_flag), 1)
            articulation_rate = phonemes_per_sec / (voiced_ratio + 1e-5)
        else:
            phonemes_per_sec = 0.0
            words_per_min = 0.0
            articulation_rate = 0.0

        # ─────────────────────────────────────────────────────────────
        # RETURN
        # ─────────────────────────────────────────────────────────────
        return AudioFeatures(
            mfcc_mean=mfcc_mean,
            mfcc_std=mfcc_std,
            mfcc_delta_mean=mfcc_delta_mean,
            mfcc_delta2_mean=mfcc_delta2_mean,
            pitch_mean=pitch_mean,
            pitch_std=pitch_std,
            pitch_min=pitch_min,
            pitch_max=pitch_max,
            vibrato_rate=vibrato_rate,
            vibrato_extent=vibrato_extent,
            speech_rate_wpm=float(words_per_min),
            speech_rate_phonemes_per_sec=float(phonemes_per_sec),
            articulation_rate=float(articulation_rate),
            rms_mean=rms_mean,
            rms_std=rms_std,
            rms_max=rms_max,
            dynamic_range=float(dynamic_range),
            pause_ratio=pause_ratio,
            pause_count=pause_count,
            mean_pause_duration=mean_pause_duration,
            max_pause_duration=max_pause_duration,
            duration_seconds=duration,
            timestamp=time.time(),
        )

    @staticmethod
    def _detect_vibrato(f0_voiced: np.ndarray) -> tuple[Optional[float], Optional[float]]:
        """Détecte vibrato (oscillation 4-7 Hz) dans le contour F0."""
        try:
            if len(f0_voiced) < 50:
                return None, None

            # Normaliser et FFT
            f0_norm = f0_voiced - np.mean(f0_voiced)
            fft_f0 = np.fft.fft(f0_norm)
            freqs = np.fft.fftfreq(len(f0_norm), d=1.0)

            # Plage 4-7 Hz
            vibrato_band = (freqs > 4) & (freqs < 7)
            if np.sum(vibrato_band) == 0:
                return None, None

            idx = np.argmax(np.abs(fft_f0[vibrato_band]))
            vibrato_freq = freqs[vibrato_band][idx]

            # Amplitude en semitones
            vibrato_amp = np.std(f0_voiced) * 12 / (np.mean(f0_voiced) + 1e-5)

            return float(vibrato_freq), float(vibrato_amp)
        except:
            return None, None


# ══════════════════════════════════════════════════════════════════════
#  REDIS STORE (V2 design kept)
# ══════════════════════════════════════════════════════════════════════

class AudioFeaturesStore:
    """
    Stockage Redis avec historique roulant + tendances (V2 design).
    """

    KEY_TEMPLATE = "session:{session_id}:audio_features"
    HISTORY_KEY_TEMPLATE = "session:{session_id}:audio_features_history"
    TTL = 3600
    MAX_HISTORY = 20

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    async def save(self, session_id: str, features: AudioFeatures) -> bool:
        """Sauvegarde + historique roulant."""
        try:
            data = json.dumps(asdict(features))
            key = self.KEY_TEMPLATE.format(session_id=session_id)
            history_key = self.HISTORY_KEY_TEMPLATE.format(session_id=session_id)

            pipe = self.redis.pipeline()
            pipe.set(key, data, ex=self.TTL)
            pipe.lpush(history_key, data)
            pipe.ltrim(history_key, 0, self.MAX_HISTORY - 1)
            pipe.expire(history_key, self.TTL)
            await pipe.execute()
            return True
        except Exception as e:
            logger.error(f"AudioFeaturesStore.save: {e}")
            return False

    async def get_latest(self, session_id: str) -> Optional[AudioFeatures]:
        """Dernier segment."""
        try:
            key = self.KEY_TEMPLATE.format(session_id=session_id)
            data = await self.redis.get(key)
            if data:
                return AudioFeatures(**json.loads(data))
        except Exception as e:
            logger.error(f"AudioFeaturesStore.get_latest: {e}")
        return None

    async def get_history(self, session_id: str, n: int = 5) -> list[AudioFeatures]:
        """Historique des n derniers segments."""
        try:
            history_key = self.HISTORY_KEY_TEMPLATE.format(session_id=session_id)
            items = await self.redis.lrange(history_key, 0, n - 1)
            return [AudioFeatures(**json.loads(item)) for item in items]
        except Exception as e:
            logger.error(f"AudioFeaturesStore.get_history: {e}")
        return []

    async def get_aggregated(self, session_id: str, n: int = 5) -> Optional[dict]:
        """
        Agrège les n derniers segments → tendances.
        INDISPENSABLE pour Phase 4 Confusion Detector!
        """
        history = await self.get_history(session_id, n)
        if not history:
            return None

        return {
            # Pitch trends
            "pitch_mean": float(np.mean([f.pitch_mean for f in history])),
            "pitch_trend": _compute_trend([f.pitch_mean for f in history]),
            "pitch_stability": float(np.mean([f.pitch_std for f in history])),

            # Pause trends
            "pause_ratio_mean": float(np.mean([f.pause_ratio for f in history])),
            "pause_ratio_trend": _compute_trend([f.pause_ratio for f in history]),
            "pause_freq": float(np.mean([f.pause_count for f in history])),

            # Speech rate trends
            "speech_rate_mean": float(np.mean([f.speech_rate_wpm for f in history])),
            "speech_rate_trend": _compute_trend([f.speech_rate_wpm for f in history]),

            # Loudness trends
            "loudness_mean": float(np.mean([f.rms_mean for f in history])),
            "loudness_trend": _compute_trend([f.rms_mean for f in history]),
            "dynamic_range_mean": float(np.mean([f.dynamic_range for f in history])),

            # Vibrato (if present)
            "vibrato_mean": float(np.mean([f.vibrato_rate or 0 for f in history])),

            # Metadata
            "n_segments": len(history),
            "duration_total": float(sum(f.duration_seconds for f in history)),
        }


def _compute_trend(values: list[float]) -> float:
    """Pente de régression linéaire (slope)."""
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    slope = np.polyfit(x, y, 1)[0]
    return float(slope)


# ══════════════════════════════════════════════════════════════════════
#  PIPELINE (V2 design)
# ══════════════════════════════════════════════════════════════════════

class AudioFeaturePipeline:
    """
    Pipeline end-to-end: extraction + Redis storage.

    Usage:
        pipeline = AudioFeaturePipeline(redis_client)
        features = await pipeline.process(session_id, audio_bytes)
        agg = await pipeline.store.get_aggregated(session_id)
    """

    def __init__(self, redis_client: aioredis.Redis, **extractor_kwargs):
        self.extractor = AudioFeatureExtractor(**extractor_kwargs)
        self.store = AudioFeaturesStore(redis_client)

    async def process(
        self,
        session_id: str,
        audio_bytes: bytes,
        sample_rate: int = 16000,
        encoding: str = "pcm_s16le",
    ) -> Optional[AudioFeatures]:
        """Extraction + stockage Redis."""
        features = self.extractor.extract_from_bytes(audio_bytes, sample_rate, encoding)
        if features is None:
            logger.warning(f"[{session_id}] Extraction échouée")
            return None

        ok = await self.store.save(session_id, features)
        if not ok:
            logger.warning(f"[{session_id}] Sauvegarde Redis échouée")

        logger.info(
            f"[{session_id}] Features: pitch={features.pitch_mean:.0f}Hz "
            f"(vibrato={features.vibrato_rate}) | "
            f"pauses={features.pause_ratio:.0%} | "
            f"wpm={features.speech_rate_wpm:.0f} | "
            f"loudness={features.rms_mean:.3f}"
        )
        return features


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON HELPER
# ══════════════════════════════════════════════════════════════════════

_extractor_instance: Optional[AudioFeatureExtractor] = None

def get_extractor() -> AudioFeatureExtractor:
    """Get or create singleton."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = AudioFeatureExtractor()
    return _extractor_instance


if __name__ == "__main__":
    import asyncio

    print("=" * 70)
    print("🧪 AUDIO FEATURES V3 OPTIMALE — Test")
    print("=" * 70)

    # Test signal: 440Hz tonality avec 2 pauses
    sr = 16000
    duration = 3.0
    t = np.linspace(0, duration, int(sr * duration))
    y = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)

    # Ajouter pauses
    y[int(sr * 1.0) : int(sr * 1.3)] = 0
    y[int(sr * 2.0) : int(sr * 2.5)] = 0

    # Extract
    extractor = get_extractor()
    features = extractor._extract(y, sr)

    print(f"\n✅ FEATURES EXTRAITES:")
    print(f"\n🎵 PITCH:")
    print(f"   Mean: {features.pitch_mean:.1f} Hz")
    print(f"   Std:  {features.pitch_std:.1f} Hz")
    print(f"   Range: {features.pitch_min:.0f}-{features.pitch_max:.0f} Hz")
    print(f"   Vibrato: rate={features.vibrato_rate} extent={features.vibrato_extent}")

    print(f"\n⏱️  SPEECH RATE:")
    print(f"   WPM: {features.speech_rate_wpm:.0f}")
    print(f"   Phonemes/sec: {features.speech_rate_phonemes_per_sec:.1f}")
    print(f"   Articulation: {features.articulation_rate:.2f}")

    print(f"\n🔊 LOUDNESS:")
    print(f"   Mean: {features.rms_mean:.4f}")
    print(f"   Std: {features.rms_std:.4f}")
    print(f"   Max: {features.rms_max:.4f}")
    print(f"   Dynamic range: {features.dynamic_range:.4f}")

    print(f"\n⏸️  PAUSES:")
    print(f"   Ratio: {features.pause_ratio:.0%}")
    print(f"   Count: {features.pause_count}")
    print(f"   Mean duration: {features.mean_pause_duration:.2f}s")
    print(f"   Max duration: {features.max_pause_duration:.2f}s")

    print(f"\n🎼 MFCC (V1 enrichi):")
    print(f"   Mean[0]: {features.mfcc_mean[0]:.3f}")
    print(f"   Delta[0]: {features.mfcc_delta_mean[0]:.3f}")
    print(f"   Delta2[0]: {features.mfcc_delta2_mean[0]:.3f}")

    print("\n" + "=" * 70)
    print("✅ VERSION 3 OPTIMALE SUCCESS!")
    print("=" * 70)
