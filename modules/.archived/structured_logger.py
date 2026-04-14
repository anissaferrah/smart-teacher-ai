"""
Structured Logger Module
Logs JSON structurés pour debugging et monitoring
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
from pythonjsonlogger import jsonlogger


class StructuredLogger:
    """Logger structuré avec format JSON"""
    
    def __init__(self, name: str = "smart_teacher", log_dir: str = "logs"):
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Évite la duplication des handlers
        if not self.logger.handlers:
            self._setup_handlers()
    
    def _setup_handlers(self):
        """Configure les handlers JSON"""
        # Handler fichier JSON
        json_handler = logging.FileHandler(
            self.log_dir / f"{self.name}.json",
            encoding='utf-8'
        )
        json_handler.setLevel(logging.DEBUG)
        json_formatter = jsonlogger.JsonFormatter()
        json_handler.setFormatter(json_formatter)
        self.logger.addHandler(json_handler)
        
        # Handler console (lisible)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
    
    def log_interaction(
        self,
        student_id: str,
        event_type: str,
        data: Dict[str, Any],
        level: str = "info"
    ):
        """
        Logs une interaction structurée
        
        Args:
            student_id: ID de l'étudiant
            event_type: Type d'événement (question, answer, error, etc.)
            data: Données additionnelles
            level: Niveau de log (debug, info, warning, error)
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "student_id": student_id,
            "event_type": event_type,
            "data": data
        }
        
        log_method = getattr(self.logger, level.lower(), self.logger.info)
        log_method(json.dumps(log_data))
    
    def log_stt_event(
        self,
        student_id: str,
        audio_duration: float,
        transcription: str,
        confidence: float,
        processing_time: float
    ):
        """
        Logs un événement STT
        
        Args:
            student_id: ID de l'étudiant
            audio_duration: Durée de l'audio en secondes
            transcription: Texte transcrit
            confidence: Score de confiance (0-1)
            processing_time: Temps de traitement en ms
        """
        self.log_interaction(
            student_id,
            "stt_event",
            {
                "audio_duration": audio_duration,
                "transcription": transcription,
                "confidence": confidence,
                "processing_time_ms": processing_time,
                "language": "fr"
            }
        )
    
    def log_llm_event(
        self,
        student_id: str,
        question: str,
        response: str,
        latency: float,
        tokens_used: int,
        cached: bool = False
    ):
        """
        Logs un événement LLM
        
        Args:
            student_id: ID de l'étudiant
            question: Question posée
            response: Réponse générée
            latency: Latence en ms
            tokens_used: Nombre de tokens
            cached: Si la réponse était en cache
        """
        self.log_interaction(
            student_id,
            "llm_event",
            {
                "question": question[:100],  # Tronce pour éviter logs énormes
                "response": response[:100],
                "latency_ms": latency,
                "tokens_used": tokens_used,
                "cached": cached
            }
        )
    
    def log_tts_event(
        self,
        student_id: str,
        text: str,
        duration: float,
        format: str,
        latency: float
    ):
        """
        Logs un événement TTS
        
        Args:
            student_id: ID de l'étudiant
            text: Texte synthétisé
            duration: Durée de l'audio en secondes
            format: Format audio (mp3, wav, etc.)
            latency: Latence en ms
        """
        self.log_interaction(
            student_id,
            "tts_event",
            {
                "text": text[:100],
                "duration": duration,
                "format": format,
                "latency_ms": latency
            }
        )
    
    def log_error(
        self,
        student_id: str,
        error_type: str,
        error_message: str,
        context: Dict[str, Any] = None
    ):
        """
        Logs une erreur avec contexte
        
        Args:
            student_id: ID de l'étudiant
            error_type: Type d'erreur (STT_ERROR, LLM_ERROR, etc.)
            error_message: Message d'erreur
            context: Contexte additionnel
        """
        self.log_interaction(
            student_id,
            "error_event",
            {
                "error_type": error_type,
                "error_message": error_message,
                "context": context or {}
            },
            level="error"
        )
    
    def log_performance(
        self,
        student_id: str,
        session_id: str,
        total_latency: float,
        stt_time: float,
        llm_time: float,
        tts_time: float,
        accuracy: float
    ):
        """
        Logs les métriques de performance
        
        Args:
            student_id: ID de l'étudiant
            session_id: ID de la session
            total_latency: Latence totale en ms
            stt_time: Temps STT en ms
            llm_time: Temps LLM en ms
            tts_time: Temps TTS en ms
            accuracy: Précision en %
        """
        self.log_interaction(
            student_id,
            "performance_metrics",
            {
                "session_id": session_id,
                "total_latency_ms": total_latency,
                "stt_time_ms": stt_time,
                "llm_time_ms": llm_time,
                "tts_time_ms": tts_time,
                "accuracy_percent": accuracy
            }
        )
    
    def get_logs_for_student(self, student_id: str, limit: int = 100) -> list:
        """
        Récupère les logs pour un étudiant spécifique
        
        Args:
            student_id: ID de l'étudiant
            limit: Nombre max de logs
            
        Returns:
            list: Logs filtrés
        """
        logs = []
        
        try:
            with open(self.log_dir / f"{self.name}.json", 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line)
                        if log_entry.get('student_id') == student_id:
                            logs.append(log_entry)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        
        return logs[-limit:]
