"""
Circuit Breaker Module
Gère la dégradation gracieuse si les services externes (OpenAI) échouent
"""

from enum import Enum
from typing import Callable, Any, Optional, Dict
from datetime import datetime, timedelta
import logging


class CircuitState(Enum):
    """États du circuit"""
    CLOSED = "closed"          # Fonctionnel
    OPEN = "open"              # Service défaillant
    HALF_OPEN = "half_open"    # Tentative de récupération


class CircuitBreaker:
    """Circuit breaker pour gérer les défaillances des services externes"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: int = 60,
        expected_exception: Exception = Exception
    ):
        """
        Initialise le circuit breaker
        
        Args:
            failure_threshold: Nombre d'erreurs avant ouverture
            recovery_timeout_seconds: Délai avant tentative de récupération
            expected_exception: Type d'exception à intercepter
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
        
        self.logger = logging.getLogger(__name__)
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Exécute une fonction protégée par le circuit breaker
        
        Args:
            func: Fonction à exécuter
            *args: Paramètres positionnels
            **kwargs: Paramètres nommés
            
        Returns:
            Résultat de la fonction ou None si le circuit est ouvert
        """
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                self.logger.info("Circuit passé en HALF_OPEN, tentative de récupération")
            else:
                self.logger.warning("Circuit OPEN, requête rejetée")
                return self._fallback_response()
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        
        except self.expected_exception as e:
            self._on_failure()
            self.logger.error(f"Erreur lors de l'appel: {str(e)}")
            return self._fallback_response()
    
    def _on_success(self) -> None:
        """Appelé quand l'appel réussit"""
        self.failure_count = 0
        
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= 2:
                self.state = CircuitState.CLOSED
                self.success_count = 0
                self.logger.info("Circuit CLOSED après récupération")
    
    def _on_failure(self) -> None:
        """Appelé quand l'appel échoue"""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.logger.error(f"Circuit OPEN après {self.failure_count} erreurs")
    
    def _should_attempt_reset(self) -> bool:
        """Vérifie si on doit tenter une récupération"""
        if self.last_failure_time is None:
            return False
        
        elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout_seconds
    
    def _fallback_response(self) -> Dict[str, Any]:
        """Réponse de secours quand le circuit est ouvert"""
        return {
            "status": "service_degraded",
            "message": "Le service est temporairement indisponible. Réponse générique fournie.",
            "code": "CIRCUIT_BREAKER_OPEN"
        }
    
    @property
    def current_state(self) -> str:
        """Retourne l'état actuel du circuit"""
        return self.state.value


class OpenAICircuitBreaker(CircuitBreaker):
    """Circuit breaker spécialisé pour OpenAI"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cache_responses = {}
    
    def _fallback_response(self) -> Dict[str, Any]:
        """Réponse de secours pour OpenAI"""
        return {
            "status": "openai_unavailable",
            "message": "OpenAI est actuellement indisponible. Veuillez réessayer dans quelques instants.",
            "fallback_answer": "Je suis temporairement indisponible. Veuillez réessayer plus tard.",
            "code": "OPENAI_CIRCUIT_OPEN"
        }


# Importation Dict for type hints
from typing import Dict
