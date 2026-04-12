"""
Cache LLM Module
Mémorise les réponses fréquentes en Redis pour réduire la latence
"""

import json
import hashlib
from typing import Optional, Dict, Any
import redis
from config import Config

REDIS_URL = f"redis://{Config.REDIS_HOST}:{Config.REDIS_PORT}/{Config.REDIS_DB}"


class LLMCache:
    """Cache Redis pour les réponses LLM"""
    
    def __init__(self, redis_url: str = REDIS_URL, ttl: int = None):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.ttl = ttl or Config.LLM_CACHE_TTL
        self.local_cache: Dict[str, tuple] = {}
    
    def _hash_query(self, question: str, context: str = "", student_level: str = "intermediate") -> str:
        """
        Crée une clé de cache unique basée sur la question et le contexte
        
        Args:
            question: Question de l'étudiant
            context: Contexte RAG (section du cours)
            student_level: Niveau de l'étudiant (beginner/intermediate/advanced)
            
        Returns:
            str: Clé de cache hashée
        """
        combined = f"{question}:{context}:{student_level}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    def get(self, question: str, context: str = "", student_level: str = "intermediate") -> Optional[Dict[str, Any]]:
        """
        Récupère une réponse en cache
        
        Args:
            question: Question de l'étudiant
            context: Contexte RAG
            student_level: Niveau de l'étudiant
            
        Returns:
            Dict: Réponse en cache ou None
        """
        key = self._hash_query(question, context, student_level)
        cache_key = f"llm_cache:{key}"
        
        try:
            # Essaie Redis d'abord
            cached = self.redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # Fallback en-mémoire
        if key in self.local_cache:
            data, timestamp = self.local_cache[key]
            return data
        
        return None
    
    def set(self, question: str, response: Dict[str, Any], context: str = "", student_level: str = "intermediate") -> bool:
        """
        Stocke une réponse en cache
        
        Args:
            question: Question de l'étudiant
            response: Réponse du LLM
            context: Contexte RAG
            student_level: Niveau de l'étudiant
            
        Returns:
            bool: Succès de la sauvegarde
        """
        key = self._hash_query(question, context, student_level)
        cache_key = f"llm_cache:{key}"
        
        try:
            # Stocke dans Redis avec TTL
            self.redis_client.setex(
                cache_key,
                self.ttl,
                json.dumps(response)
            )
        except Exception:
            pass
        
        # Fallback en-mémoire
        import time
        self.local_cache[key] = (response, time.time())
        
        return True
    
    def invalidate(self, question: str = None, context: str = None, student_id: str = None) -> int:
        """
        Invalide le cache (pour un étudiant ou globalement)
        
        Args:
            question: Question spécifique à invalider
            context: Contexte spécifique à invalider
            student_id: ID de l'étudiant dont tout le cache doit être vidé
            
        Returns:
            int: Nombre d'entrées supprimées
        """
        count = 0
        
        if question:
            key = self._hash_query(question, context or "", "")
            try:
                self.redis_client.delete(f"llm_cache:{key}")
                count += 1
            except Exception:
                pass
            
            if key in self.local_cache:
                del self.local_cache[key]
                count += 1
        
        elif student_id:
            # Supprime tout le cache pour cet étudiant
            try:
                student_cache_pattern = f"student_llm_cache:{student_id}:*"
                keys = self.redis_client.keys(student_cache_pattern)
                for k in keys:
                    self.redis_client.delete(k)
                    count += 1
            except Exception:
                pass
        
        else:
            # Vide tout le cache
            try:
                self.redis_client.flushdb()
            except Exception:
                pass
            self.local_cache.clear()
            count = len(self.local_cache) + 1
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du cache
        
        Returns:
            Dict: Statistiques de hit/miss
        """
        try:
            info = self.redis_client.info('stats')
            return {
                "keys_in_redis": self.redis_client.dbsize(),
                "memory_used_bytes": info.get('used_memory', 0),
                "local_cache_size": len(self.local_cache)
            }
        except Exception:
            return {
                "keys_in_redis": 0,
                "memory_used_bytes": 0,
                "local_cache_size": len(self.local_cache)
            }
