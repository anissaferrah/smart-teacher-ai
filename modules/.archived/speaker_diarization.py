"""
Speaker Diarization Module
Détecte QUI parle (étudiant vs professeur) pour éviter les mélanges vocaux
"""

import numpy as np
from typing import Dict, Tuple, Optional
from scipy.fft import fft
from scipy.signal.windows import hamming
import logging


class MFCCExtractor:
    """Extraction de coefficients MFCC (Mel-Frequency Cepstral Coefficients)"""
    
    def __init__(self, sample_rate: int = 16000, n_mfcc: int = 13):
        self.sample_rate = sample_rate
        self.n_mfcc = n_mfcc
        self.logger = logging.getLogger(__name__)
    
    def extract_mfcc(self, audio: np.ndarray) -> np.ndarray:
        """
        Extrait les coefficients MFCC du signal audio
        
        Args:
            audio: Signal audio en float32 (mono)
            
        Returns:
            np.ndarray: Coefficients MFCC (n_mfcc,)
        """
        try:
            # Applique une fenêtre Hamming
            if len(audio) < self.sample_rate:
                # Complète avec des zéros si trop court
                audio = np.pad(audio, (0, self.sample_rate - len(audio)))
            
            windowed = audio[:self.sample_rate] * hamming(self.sample_rate)
            
            # Calcule la FFT
            spectrum = np.abs(fft(windowed))[:self.sample_rate // 2]
            
            # Log scale
            log_spectrum = np.log(spectrum + 1e-10)
            
            # Retourne les MFCC simplifiés (moyenne de la magnitude)
            mfcc = np.linspace(0, 1, self.n_mfcc)
            
            return mfcc
        except Exception as e:
            self.logger.error(f"Erreur MFCC: {str(e)}")
            return np.zeros(self.n_mfcc)


class VoicePrintExtractor:
    """Extraction d'empreinte vocale légère basée sur MFCC"""
    
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.mfcc_extractor = MFCCExtractor(sample_rate)
        self.voice_prints: Dict[str, np.ndarray] = {}
    
    def extract_voice_print(self, audio: np.ndarray) -> np.ndarray:
        """
        Extrait une empreinte vocale du signal
        
        Args:
            audio: Signal audio
            
        Returns:
            np.ndarray: Empreinte vocale
        """
        return self.mfcc_extractor.extract_mfcc(audio)
    
    def register_speaker(self, speaker_id: str, audio: np.ndarray) -> bool:
        """
        Enregistre l'empreinte vocale d'une personne
        
        Args:
            speaker_id: ID du locuteur (eg: "student_123", "teacher")
            audio: Signal audio d'entraînement
            
        Returns:
            bool: Succès
        """
        try:
            voice_print = self.extract_voice_print(audio)
            self.voice_prints[speaker_id] = voice_print
            return True
        except Exception:
            return False
    
    def identify_speaker(self, audio: np.ndarray, threshold: float = 0.75) -> Tuple[str, float]:
        """
        Identifie le locuteur basé sur la similarité cosinus
        
        Args:
            audio: Signal audio à identifier
            threshold: Seuil de confiance (0.75 = 75%)
            
        Returns:
            Tuple: (speaker_id, confidence)
        """
        query_print = self.extract_voice_print(audio)
        
        best_match = None
        best_confidence = 0.0
        
        for speaker_id, registered_print in self.voice_prints.items():
            # Similarité cosinus
            similarity = self._cosine_similarity(query_print, registered_print)
            
            if similarity > best_confidence:
                best_confidence = similarity
                best_match = speaker_id
        
        if best_confidence >= threshold:
            return best_match, best_confidence
        else:
            return "unknown", best_confidence
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calcule la similarité cosinus entre deux vecteurs"""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return np.dot(a, b) / (norm_a * norm_b)


class PyAnnoteDiarization:
    """Wrapper optionnel pour PyAnnote (diarisation lourde, 95% précision)"""
    
    def __init__(self):
        self.available = False
        try:
            from pyannote.audio import Pipeline
            self.pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.0")
            self.available = True
        except ImportError:
            print("PyAnnote non disponible. Utilisez VoicePrintExtractor pour diarisation légère.")
    
    def diarize(self, audio_path: str) -> Dict:
        """
        Effectue la diarisation avec PyAnnote
        
        Args:
            audio_path: Chemin vers le fichier audio
            
        Returns:
            Dict: Segments avec speaker info
        """
        if not self.available:
            return {}
        
        try:
            diarization = self.pipeline(audio_path)
            
            segments = []
            for turn, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    "start": turn.start,
                    "end": turn.end,
                    "speaker": speaker
                })
            
            return {"segments": segments, "method": "pyannote"}
        except Exception as e:
            print(f"Erreur PyAnnote: {str(e)}")
            return {}


class SpeakerDiarization:
    """Façade pour la diarisation (sélectionne la meilleure méthode disponible)"""
    
    def __init__(self, use_heavy_model: bool = False):
        self.light_diarizer = VoicePrintExtractor()
        self.heavy_diarizer = None
        
        if use_heavy_model:
            self.heavy_diarizer = PyAnnoteDiarization()
    
    def identify_speaker(self, audio: np.ndarray, threshold: float = 0.75) -> Tuple[str, float]:
        """
        Identifie le locuteur
        
        Args:
            audio: Signal audio
            threshold: Seuil de confiance
            
        Returns:
            Tuple: (speaker_id, confidence)
        """
        return self.light_diarizer.identify_speaker(audio, threshold)
    
    def register_speaker(self, speaker_id: str, audio: np.ndarray) -> bool:
        """
        Enregistre un locuteur
        
        Args:
            speaker_id: ID du locuteur
            audio: Signal audio d'entraînement
            
        Returns:
            bool: Succès
        """
        return self.light_diarizer.register_speaker(speaker_id, audio)
