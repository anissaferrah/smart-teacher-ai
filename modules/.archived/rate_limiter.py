"""
Rate Limiter Module
Limite le nombre de requêtes par étudiant (max 100 requêtes/heure)
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Tuple
import redis
from config import Config

REDIS_URL = f"redis://{Config.REDIS_HOST}:{Config.REDIS_PORT}/{Config.REDIS_DB}"


class RateLimiter:
    """Limitation de débit des requêtes par étudiant"""
    
    def __init__(
        self, 
        redis_url: str = REDIS_URL,
        requests_per_hour: int = None,
        window_seconds: int = 3600
    ):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.requests_per_hour = requests_per_hour or Config.RATE_LIMIT_REQUESTS_PER_HOUR
        self.window_seconds = window_seconds
        
        # Fallback en-mémoire si Redis est indisponible
        self.local_counter: Dict[str, list] = defaultdict(list)
    
    def is_allowed(self, student_id: str) -> Tuple[bool, Dict]:
        """
        Vérifie si la requête est autorisée pour l'étudiant
        
        Args:
            student_id: ID unique de l'étudiant
            
        Returns:
            Tuple: (allowed: bool, info: Dict avec limite et usage)
        """
        key = f"rate_limit:{student_id}"
        current_time = datetime.utcnow()
        
        try:
            # Utilise Redis si disponible
            request_count = self.redis_client.incr(key)
            
            if request_count == 1:
                # Première requête, défini l'expiration
                self.redis_client.expire(key, self.window_seconds)
            
            allowed = request_count <= self.requests_per_hour
            
            return allowed, {
                "requests_used": request_count,
                "requests_limit": self.requests_per_hour,
                "remaining": max(0, self.requests_per_hour - request_count),
                "reset_after_seconds": self.redis_client.ttl(key)
            }
            
        except Exception:
            # Fallback en-mémoire
            timestamps = self.local_counter[student_id]
            cutoff_time = current_time - timedelta(seconds=self.window_seconds)
            
            # Supprime les anciennes requêtes
            self.local_counter[student_id] = [
                ts for ts in timestamps if ts > cutoff_time
            ]
            
            # Ajoute la nouvelle requête
            self.local_counter[student_id].append(current_time)
            request_count = len(self.local_counter[student_id])
            
            allowed = request_count <= self.requests_per_hour
            
            return allowed, {
                "requests_used": request_count,
                "requests_limit": self.requests_per_hour,
                "remaining": max(0, self.requests_per_hour - request_count),
                "reset_after_seconds": self.window_seconds
            }
    
    def reset_student(self, student_id: str) -> bool:
        """
        Réinitialise le compteur pour un étudiant (admin uniquement)
        
        Args:
            student_id: ID unique de l'étudiant
            
        Returns:
            bool: Succès de la réinitialisation
        """
        try:
            key = f"rate_limit:{student_id}"
            self.redis_client.delete(key)
            
            if student_id in self.local_counter:
                del self.local_counter[student_id]
            
            return True
        except Exception:
            return False
