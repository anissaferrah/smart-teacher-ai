"""
╔══════════════════════════════════════════════════════════════════════╗
║  AUDIO FEATURES EXTRACTION — Prosodic Analysis (PHASE 1)            ║
║                                                                      ║
║  Extraction des features audio essentielles pour:                    ║
║  • Détection de confusion (Phase 4)                                  ║
║  • Adaptation débit TTS                                              ║
║  • Analyse engagement étudiant                                       ║
║                                                                      ║
║  Features extraites:                                                 ║
║  ├─ MFCC (Mel-frequency cepstral coefficients)                      ║
║  ├─ Pitch (F0, variabilité, contour)                                ║
║  ├─ Pauses (ratio silence/parole, durées)                           ║
║  ├─ Speech rate (débit parole)                                      ║
║  ├─ Loudness (RMS energy)                                           ║
║  └─ Prosody (intonation contour)                                     ║
║                                                                      ║
║  Utilisation:                                                        ║
║  >>> extractor = AudioFeatures()                                    ║
║  >>> features = await extractor.extract_all(audio_bytes)           ║
║  >>> await extractor.save_to_redis(session_id, features)           ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
import io
import json
from typing import Dict, Tuple, Optional, Any
from dataclasses import dataclass, asdict

import numpy as np
import librosa
import redis.asyncio as redis
from scipy import signal
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════════════

@dataclass
class MFCCFeatures:
    """Mel-Frequency Cepstral Coefficients — acoustic fingerprint"""
    mean: list  # moyenne des 13 coefficients MFCC
    std: list   # écart-type
    delta_mean: list  # variation temporelle (vitesse)
    delta2_mean: list  # accélération


@dataclass
class PitchFeatures:
    """F0 et contour d'intonation"""
    f0_mean: float  # fréquence fondamentale moyenne (Hz)
    f0_std: float   # variabilité pitch
    f0_min: float
    f0_max: float
    vibrato_rate: Optional[float]  # oscillations pitch (Hz)
    vibrato_extent: Optional[float]  # amplitude oscillations (semitones)


@dataclass
class PauseFeatures:
    """Silence patterns et structure temporelle"""
    speech_ratio: float  # % audio qui est parole (vs silence)
    pause_count: int  # nombre de pauses
    pause_duration_mean: float  # durée moyenne pauses (sec)
    pause_duration_std: float
    max_silence: float  # pause la plus longue (sec)


@dataclass
class SpeechRateFeatures:
    """Débit de parole"""
    speech_rate_words_per_min: float  # approximation
    speech_rate_phonemes_per_sec: float  # plus précis
    articulation_rate: float  # vitesse articulation pure


@dataclass
class LoudnessFeatures:
    """Énergie et dynamique"""
    rms_mean: float  # loudness moyenne
    rms_std: float   # variabilité dynamique
    rms_max: float
    dynamic_range: float  # différence max-min


@dataclass
class AllAudioFeatures:
    """All features combined"""
    mfcc: MFCCFeatures
    pitch: PitchFeatures
    pauses: PauseFeatures
    speech_rate: SpeechRateFeatures
    loudness: LoudnessFeatures
    duration: float  # durée totale (sec)
    timestamp: str  # ISO format


# ══════════════════════════════════════════════════════════════════════
#  AUDIO FEATURES EXTRACTION
# ══════════════════════════════════════════════════════════════════════

class AudioFeatures:
    """
    Extraction vectorisée des features prosodiques pour confusion detection.

    Phase 1 output: utilisé dans Phase 4 (détecteur confusion multimodal)
    """

    def __init__(
        self,
        sr: int = 16000,
        n_mfcc: int = 13,
        vad_threshold: float = 0.02
    ):
        """
        Args:
            sr: Sample rate (Hz)
            n_mfcc: Nombre de coefficients MFCC
            vad_threshold: Seuil pour Voice Activity Detection (RMS)
        """
        self.sr = sr
        self.n_mfcc = n_mfcc
        self.vad_threshold = vad_threshold
        self.redis_client: Optional[redis.Redis] = None

    async def connect_redis(self, host: str = "localhost", port: int = 6379):
        """Connecter à Redis pour stockage features"""
        try:
            self.redis_client = await redis.from_url(f"redis://{host}:{port}")
            log.info(f"✅ Redis connecté: {host}:{port}")
        except Exception as e:
            log.warning(f"⚠️ Redis non disponible: {e}")

    # ═══════════════════════════════════════════════════════════════════
    #  1. MFCC FEATURES
    # ═══════════════════════════════════════════════════════════════════

    def extract_mfcc(self, y: np.ndarray) -> MFCCFeatures:
        """
        Extraire Mel-Frequency Cepstral Coefficients.

        MFCC = acoustic fingerprint de la voix
        Utilisé pour: reconnaissance speaker, émotion, style

        Args:
            y: Audio signal (numpy array)

        Returns:
            MFCCFeatures avec statistiques
        """
        try:
            # Extraire 13 coefficients MFCC
            mfcc = librosa.feature.mfcc(
                y=y,
                sr=self.sr,
                n_mfcc=self.n_mfcc,
                n_fft=2048,
                hop_length=512
            )  # Shape: (13, time_steps)

            # Calculer statistiques
            mfcc_mean = np.mean(mfcc, axis=1).tolist()  # moyenne par coefficient
            mfcc_std = np.std(mfcc, axis=1).tolist()

            # Variation temporelle (delta) = vitesse change MFCC
            mfcc_delta = librosa.feature.delta(mfcc)
            delta_mean = np.mean(mfcc_delta, axis=1).tolist()

            # Accélération (delta-delta)
            mfcc_delta2 = librosa.feature.delta(mfcc, order=2)
            delta2_mean = np.mean(mfcc_delta2, axis=1).tolist()

            return MFCCFeatures(
                mean=mfcc_mean,
                std=mfcc_std,
                delta_mean=delta_mean,
                delta2_mean=delta2_mean
            )
        except Exception as e:
            log.error(f"❌ MFCC extraction failed: {e}")
            return MFCCFeatures([], [], [], [])

    # ═══════════════════════════════════════════════════════════════════
    #  2. PITCH FEATURES (Intonation)
    # ═══════════════════════════════════════════════════════════════════

    def extract_pitch(self, y: np.ndarray) -> PitchFeatures:
        """
        Extraire F0 (fréquence fondamentale) et contour intonation.

        Pitch = hauteur voix, indicateur d'émotion/confusion
        • Confusion → baisse pitch + variabilité
        • Confiance → pitch stable ou montée en fin phrase

        Args:
            y: Audio signal

        Returns:
            PitchFeatures avec F0 et vibrato
        """
        try:
            # Extraire F0 avec PYIN (Probabilistic YIN)
            f0, voiced_flag, voiced_probs = librosa.pyin(
                y,
                fmin=librosa.note_to_hz('C2'),  # 32 Hz min (voix adulte)
                fmax=librosa.note_to_hz('C7'),  # 2093 Hz max
                sr=self.sr
            )

            # Nettoyer F0 (garder seulement frames voicées)
            f0_voiced = f0[voiced_flag]

            if len(f0_voiced) < 10:
                log.warning("⚠️ Pas assez de frames voicées pour pitch")
                return PitchFeatures(
                    f0_mean=0.0, f0_std=0.0, f0_min=0.0, f0_max=0.0,
                    vibrato_rate=None, vibrato_extent=None
                )

            # Statistiques F0
            f0_mean = float(np.mean(f0_voiced))
            f0_std = float(np.std(f0_voiced))
            f0_min = float(np.min(f0_voiced))
            f0_max = float(np.max(f0_voiced))

            # Détecte vibrato (oscillation rapide ~5Hz)
            vibrato_rate, vibrato_extent = self._detect_vibrato(f0_voiced)

            return PitchFeatures(
                f0_mean=f0_mean,
                f0_std=f0_std,
                f0_min=f0_min,
                f0_max=f0_max,
                vibrato_rate=vibrato_rate,
                vibrato_extent=vibrato_extent
            )
        except Exception as e:
            log.error(f"❌ Pitch extraction failed: {e}")
            return PitchFeatures(
                f0_mean=0.0, f0_std=0.0, f0_min=0.0, f0_max=0.0,
                vibrato_rate=None, vibrato_extent=None
            )

    def _detect_vibrato(self, f0: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
        """
        Détecter vibrato dans le contour F0.

        Vibrato = oscillation du pitch (musical effect)
        Fréquence typique: 4-7 Hz
        """
        try:
            if len(f0) < 50:
                return None, None

            # FFT du contour F0
            fft_f0 = np.fft.fft(f0 - np.mean(f0))
            freqs = np.fft.fftfreq(len(f0), d=512/self.sr)  # Hz

            # Chercher pic dans 4-7 Hz
            vibrato_band = (freqs > 4) & (freqs < 7)
            if np.sum(vibrato_band) == 0:
                return None, None

            vibrato_idx = np.argmax(np.abs(fft_f0[vibrato_band]))
            vibrato_freq = freqs[vibrato_band][vibrato_idx]

            # Amplitude vibrato (en semitones)
            vibrato_amp = np.std(f0) * 12 / np.mean(f0)

            return float(vibrato_freq), float(vibrato_amp)
        except:
            return None, None

    # ═══════════════════════════════════════════════════════════════════
    #  3. PAUSE FEATURES (Structure temporelle)
    # ═══════════════════════════════════════════════════════════════════

    def extract_pauses(self, y: np.ndarray) -> PauseFeatures:
        """
        Détecter pauses et silences.

        Pauses = indicateur de bien-être ou confusion
        • Confusion → pauses longues, fréquentes
        • Fluidité → peu de pauses, courtes

        Args:
            y: Audio signal

        Returns:
            PauseFeatures avec statistiques silences
        """
        try:
            # Extraire RMS energy par frame
            frame_length = 512
            hop_length = 512
            rms = librosa.feature.rms(
                y=y,
                frame_length=frame_length,
                hop_length=hop_length,
                center=False
            )[0]  # Shape: (n_frames,)

            # Voice Activity Detection: frame silencieux si RMS < threshold
            is_silent = rms < self.vad_threshold

            # % parole vs silence
            speech_ratio = float(np.sum(~is_silent) / len(is_silent))

            # Détecter transitions silence→parole
            transitions = np.diff(is_silent.astype(int))
            pause_starts = np.where(transitions == 1)[0]  # Début pause
            pause_ends = np.where(transitions == -1)[0]  # Fin pause

            pause_count = min(len(pause_starts), len(pause_ends))

            if pause_count > 0:
                # Durée des pauses (en frames → secondes)
                pause_durations = (
                    (pause_ends[:pause_count] - pause_starts[:pause_count])
                    * hop_length / self.sr
                )
                pause_duration_mean = float(np.mean(pause_durations))
                pause_duration_std = float(np.std(pause_durations))
                max_silence = float(np.max(pause_durations))
            else:
                pause_duration_mean = 0.0
                pause_duration_std = 0.0
                max_silence = 0.0

            return PauseFeatures(
                speech_ratio=speech_ratio,
                pause_count=pause_count,
                pause_duration_mean=pause_duration_mean,
                pause_duration_std=pause_duration_std,
                max_silence=max_silence
            )
        except Exception as e:
            log.error(f"❌ Pause extraction failed: {e}")
            return PauseFeatures(
                speech_ratio=0.0, pause_count=0,
                pause_duration_mean=0.0, pause_duration_std=0.0,
                max_silence=0.0
            )

    # ═══════════════════════════════════════════════════════════════════
    #  4. SPEECH RATE (Débit parole)
    # ═══════════════════════════════════════════════════════════════════

    def extract_speech_rate(self, y: np.ndarray) -> SpeechRateFeatures:
        """
        Estimer débit de parole.

        Débit = vitesse élocution, indicateur d'état
        • Confusion → débit ralenti
        • Compréhension → débit normal
        • Passion → débit rapide

        Args:
            y: Audio signal

        Returns:
            SpeechRateFeatures avec débit en words/min et phonemes/sec
        """
        try:
            duration = len(y) / self.sr

            # Estimation nombre de "mots" par analyse spectrale
            # Parole = ~3-5 phonemes par seconde en moyenne
            # Approximation: utiliser onsets (pics d'énergie)
            onset_env = librosa.onset.onset_strength(y=y, sr=self.sr)
            onsets = librosa.onset.onset_detect(onset_env=onset_env, sr=self.sr)

            if len(onsets) > 0:
                # Nombre de "pics syllabiques" par seconde
                phonemes_per_sec = len(onsets) / duration
                # Approximation: 1 mot ≈ 1.5 syllables
                words_per_min = (len(onsets) / 1.5) * 60 / duration
            else:
                phonemes_per_sec = 0.0
                words_per_min = 0.0

            # Articulation rate = débit pur (sans pauses)
            # Estimation par ratio parole/total (de pause features)
            pause_feats = self.extract_pauses(y)
            articulation_rate = phonemes_per_sec / (pause_feats.speech_ratio + 1e-5)

            return SpeechRateFeatures(
                speech_rate_words_per_min=float(words_per_min),
                speech_rate_phonemes_per_sec=float(phonemes_per_sec),
                articulation_rate=float(articulation_rate)
            )
        except Exception as e:
            log.error(f"❌ Speech rate extraction failed: {e}")
            return SpeechRateFeatures(
                speech_rate_words_per_min=0.0,
                speech_rate_phonemes_per_sec=0.0,
                articulation_rate=0.0
            )

    # ═══════════════════════════════════════════════════════════════════
    #  5. LOUDNESS FEATURES (Énergie)
    # ═══════════════════════════════════════════════════════════════════

    def extract_loudness(self, y: np.ndarray) -> LoudnessFeatures:
        """
        Analyser loudness et dynamique.

        Loudness = indicateur engagement
        • Faible énergie → fatigue/désintérêt
        • Énergie variable → expressivité

        Args:
            y: Audio signal

        Returns:
            LoudnessFeatures avec RMS et dynamique
        """
        try:
            # RMS energy par frame
            rms = librosa.feature.rms(y=y, frame_length=512, hop_length=512)[0]

            # Convertir en dB pour meilleure perception
            rms_db = librosa.power_to_db(rms ** 2, ref=1.0)

            rms_mean = float(np.mean(rms))
            rms_std = float(np.std(rms))
            rms_max = float(np.max(rms))
            rms_min = float(np.min(rms))

            dynamic_range = rms_max - rms_min

            return LoudnessFeatures(
                rms_mean=rms_mean,
                rms_std=rms_std,
                rms_max=rms_max,
                dynamic_range=float(dynamic_range)
            )
        except Exception as e:
            log.error(f"❌ Loudness extraction failed: {e}")
            return LoudnessFeatures(
                rms_mean=0.0, rms_std=0.0, rms_max=0.0, dynamic_range=0.0
            )

    # ═══════════════════════════════════════════════════════════════════
    #  MAIN: EXTRACT ALL
    # ═══════════════════════════════════════════════════════════════════

    async def extract_all(self, audio_bytes: bytes) -> AllAudioFeatures:
        """
        Extraire TOUTES les features prosodiques en une seule pass.

        Usage:
        >>> extractor = AudioFeatures()
        >>> features = await extractor.extract_all(audio_bytes)
        >>> print(features.pitch.f0_mean)  # 160.5 Hz

        Args:
            audio_bytes: Audio WAV/MP3/etc en bytes

        Returns:
            AllAudioFeatures complet
        """
        try:
            # Charger audio depuis bytes
            y, sr = librosa.load(io.BytesIO(audio_bytes), sr=self.sr)
            duration = len(y) / self.sr

            log.info(f"🎙️ Extracting features from {duration:.2f}s audio")

            # Extraire tous les features en parallèle
            mfcc = self.extract_mfcc(y)
            pitch = self.extract_pitch(y)
            pauses = self.extract_pauses(y)
            speech_rate = self.extract_speech_rate(y)
            loudness = self.extract_loudness(y)

            from datetime import datetime
            timestamp = datetime.utcnow().isoformat()

            features = AllAudioFeatures(
                mfcc=mfcc,
                pitch=pitch,
                pauses=pauses,
                speech_rate=speech_rate,
                loudness=loudness,
                duration=duration,
                timestamp=timestamp
            )

            log.info(f"✅ Features extracted: {features.pitch.f0_mean:.1f}Hz | {features.speech_rate.speech_rate_words_per_min:.0f}wpm")
            return features

        except Exception as e:
            log.error(f"❌ Feature extraction failed: {e}")
            raise

    # ═══════════════════════════════════════════════════════════════════
    #  REDIS STORAGE
    # ═══════════════════════════════════════════════════════════════════

    async def save_to_redis(
        self,
        session_id: str,
        features: AllAudioFeatures,
        ttl: int = 3600
    ) -> bool:
        """
        Sauvegarder features dans Redis pour utilisation Phase 4.

        Redis key: `session:{session_id}:audio_features:{timestamp}`
        TTL: 1 heure (configurable)

        Args:
            session_id: ID de session
            features: AllAudioFeatures à sauvegarder
            ttl: Time-to-live secondes

        Returns:
            True si succès, False sinon
        """
        if not self.redis_client:
            log.warning("⚠️ Redis not connected, skipping save")
            return False

        try:
            # Convertir features en dict
            features_dict = self._features_to_dict(features)

            # Redis key
            key = f"session:{session_id}:audio_features:{features.timestamp}"

            # Sauvegarder JSON
            await self.redis_client.setex(
                key,
                ttl,
                json.dumps(features_dict, default=str)
            )

            # Aussi indexer dans une liste session
            list_key = f"session:{session_id}:features_list"
            await self.redis_client.lpush(list_key, key)
            await self.redis_client.expire(list_key, ttl)

            log.info(f"💾 Features saved to Redis: {key}")
            return True

        except Exception as e:
            log.error(f"❌ Redis save failed: {e}")
            return False

    async def get_latest_features(self, session_id: str) -> Optional[AllAudioFeatures]:
        """
        Récupérer les features les plus récentes pour une session.

        Usage en Phase 4 (confusion detector):
        >>> extractor = AudioFeatures()
        >>> await extractor.connect_redis()
        >>> latest = await extractor.get_latest_features(session_id)
        >>> if latest:
        ...     confusion_score = detector.compute_confusion(latest)

        Args:
            session_id: ID session

        Returns:
            AllAudioFeatures ou None si pas trouvé
        """
        if not self.redis_client:
            return None

        try:
            list_key = f"session:{session_id}:features_list"
            keys = await self.redis_client.lrange(list_key, 0, 0)  # Latest

            if not keys:
                return None

            key = keys[0]
            data = await self.redis_client.get(key)

            if data:
                features_dict = json.loads(data)
                return self._dict_to_features(features_dict)

            return None
        except Exception as e:
            log.error(f"❌ Redis get failed: {e}")
            return None

    @staticmethod
    def _features_to_dict(features: AllAudioFeatures) -> Dict:
        """Convertir AllAudioFeatures en dict sérialisable"""
        return asdict(features)

    @staticmethod
    def _dict_to_features(d: Dict) -> AllAudioFeatures:
        """Reconstruire AllAudioFeatures depuis dict"""
        return AllAudioFeatures(
            mfcc=MFCCFeatures(**d['mfcc']),
            pitch=PitchFeatures(**d['pitch']),
            pauses=PauseFeatures(**d['pauses']),
            speech_rate=SpeechRateFeatures(**d['speech_rate']),
            loudness=LoudnessFeatures(**d['loudness']),
            duration=d['duration'],
            timestamp=d['timestamp']
        )


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON (usage facile)
# ══════════════════════════════════════════════════════════════════════

_audio_features_instance: Optional[AudioFeatures] = None

def get_audio_features() -> AudioFeatures:
    """Get or create singleton instance"""
    global _audio_features_instance
    if _audio_features_instance is None:
        _audio_features_instance = AudioFeatures()
    return _audio_features_instance


if __name__ == "__main__":
    print("Module audio_features.py chargé ✅")
    print("Usage: from modules.audio_features import AudioFeatures, get_audio_features")
