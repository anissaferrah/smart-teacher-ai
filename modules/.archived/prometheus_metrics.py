"""
Prometheus Metrics Module
Métriques en temps réel pour Grafana (tableaux de bord)
"""

from datetime import datetime
from typing import Dict, Tuple
import logging


class PrometheusMetrics:
    """Collecteur de métriques Prometheus"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Compteurs
        self.metrics = {
            # Compteurs
            "stt_requests_total": 0,
            "stt_errors_total": 0,
            "llm_requests_total": 0,
            "llm_errors_total": 0,
            "tts_requests_total": 0,
            "tts_errors_total": 0,
            
            # Histogrammes (latence)
            "stt_latency_buckets": [0] * 10,  # 10 buckets
            "llm_latency_buckets": [0] * 10,
            "tts_latency_buckets": [0] * 10,
            "total_latency_buckets": [0] * 10,
            
            # Jauge (valeurs instantanées)
            "active_sessions": 0,
            "students_online": 0,
            "cpu_usage_percent": 0.0,
            "memory_usage_percent": 0.0,
            "redis_connected": 1,
            "postgres_connected": 1,
            
            # Ratios
            "cache_hit_rate": 0.0,
            "average_accuracy": 0.0,
            "api_error_rate": 0.0
        }
        
        # Latence buckets en ms
        self.latency_boundaries = [10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, float('inf')]
    
    # ===== COMPTEURS =====
    
    def increment_stt_request(self):
        """Incrémente le compteur de requêtes STT"""
        self.metrics["stt_requests_total"] += 1
    
    def increment_stt_error(self):
        """Incrémente le compteur d'erreurs STT"""
        self.metrics["stt_errors_total"] += 1
    
    def increment_llm_request(self):
        """Incrémente le compteur de requêtes LLM"""
        self.metrics["llm_requests_total"] += 1
    
    def increment_llm_error(self):
        """Incrémente le compteur d'erreurs LLM"""
        self.metrics["llm_errors_total"] += 1
    
    def increment_tts_request(self):
        """Incrémente le compteur de requêtes TTS"""
        self.metrics["tts_requests_total"] += 1
    
    def increment_tts_error(self):
        """Incrémente le compteur d'erreurs TTS"""
        self.metrics["tts_errors_total"] += 1
    
    # ===== LATENCE =====
    
    def record_stt_latency(self, latency_ms: float):
        """Enregistre la latence STT en ms"""
        self._record_latency(latency_ms, "stt_latency_buckets")
    
    def record_llm_latency(self, latency_ms: float):
        """Enregistre la latence LLM en ms"""
        self._record_latency(latency_ms, "llm_latency_buckets")
    
    def record_tts_latency(self, latency_ms: float):
        """Enregistre la latence TTS en ms"""
        self._record_latency(latency_ms, "tts_latency_buckets")
    
    def record_total_latency(self, latency_ms: float):
        """Enregistre la latence totale (bout en bout) en ms"""
        self._record_latency(latency_ms, "total_latency_buckets")
    
    def _record_latency(self, latency_ms: float, bucket_name: str):
        """Enregistre une latence dans le bucket approprié"""
        buckets = self.metrics[bucket_name]
        
        for i, boundary in enumerate(self.latency_boundaries):
            if latency_ms <= boundary:
                buckets[i] += 1
    
    # ===== JAUGES =====
    
    def set_active_sessions(self, count: int):
        """Définit le nombre de sessions actives"""
        self.metrics["active_sessions"] = count
    
    def set_students_online(self, count: int):
        """Définit le nombre d'étudiants en ligne"""
        self.metrics["students_online"] = count
    
    def set_cpu_usage(self, percentage: float):
        """Définit l'utilisation CPU en %"""
        self.metrics["cpu_usage_percent"] = min(100, max(0, percentage))
    
    def set_memory_usage(self, percentage: float):
        """Définit l'utilisation mémoire en %"""
        self.metrics["memory_usage_percent"] = min(100, max(0, percentage))
    
    def set_redis_status(self, connected: bool):
        """Définit le statut de Redis (1=connecté, 0=déconnecté)"""
        self.metrics["redis_connected"] = 1 if connected else 0
    
    def set_postgres_status(self, connected: bool):
        """Définit le statut de PostgreSQL (1=connecté, 0=déconnecté)"""
        self.metrics["postgres_connected"] = 1 if connected else 0
    
    # ===== RATIOS =====
    
    def set_cache_hit_rate(self, hit_rate: float):
        """Définit le taux de hit cache (0-1)"""
        self.metrics["cache_hit_rate"] = min(1.0, max(0.0, hit_rate))
    
    def set_average_accuracy(self, accuracy: float):
        """Définit la précision moyenne en %"""
        self.metrics["average_accuracy"] = min(100, max(0, accuracy))
    
    def set_api_error_rate(self, rate: float):
        """Définit le taux d'erreur API (0-1)"""
        self.metrics["api_error_rate"] = min(1.0, max(0.0, rate))
    
    # ===== EXPORT =====
    
    def export_prometheus_format(self) -> str:
        """
        Exporte les métriques au format Prometheus
        
        Returns:
            str: Métriques en format texte Prometheus
        """
        lines = []
        timestamp = int(datetime.utcnow().timestamp() * 1000)
        
        # Compteurs
        lines.append(f"# HELP stt_requests_total Nombre total de requêtes STT")
        lines.append(f"# TYPE stt_requests_total counter")
        lines.append(f"stt_requests_total {self.metrics['stt_requests_total']} {timestamp}")
        
        lines.append(f"stt_errors_total {self.metrics['stt_errors_total']} {timestamp}")
        lines.append(f"llm_requests_total {self.metrics['llm_requests_total']} {timestamp}")
        lines.append(f"llm_errors_total {self.metrics['llm_errors_total']} {timestamp}")
        lines.append(f"tts_requests_total {self.metrics['tts_requests_total']} {timestamp}")
        lines.append(f"tts_errors_total {self.metrics['tts_errors_total']} {timestamp}")
        
        # Jauges
        lines.append(f"\n# HELP active_sessions Nombre de sessions actives")
        lines.append(f"# TYPE active_sessions gauge")
        lines.append(f"active_sessions {self.metrics['active_sessions']} {timestamp}")
        
        lines.append(f"students_online {self.metrics['students_online']} {timestamp}")
        lines.append(f"cpu_usage_percent {self.metrics['cpu_usage_percent']} {timestamp}")
        lines.append(f"memory_usage_percent {self.metrics['memory_usage_percent']} {timestamp}")
        lines.append(f"redis_connected {self.metrics['redis_connected']} {timestamp}")
        lines.append(f"postgres_connected {self.metrics['postgres_connected']} {timestamp}")
        
        # Ratios
        lines.append(f"cache_hit_rate {self.metrics['cache_hit_rate']} {timestamp}")
        lines.append(f"average_accuracy {self.metrics['average_accuracy']} {timestamp}")
        lines.append(f"api_error_rate {self.metrics['api_error_rate']} {timestamp}")
        
        return "\n".join(lines)
    
    def get_summary(self) -> Dict:
        """
        Retourne un résumé des métriques clés
        
        Returns:
            Dict: Résumé des performances
        """
        stt_errors = self.metrics["stt_errors_total"]
        llm_errors = self.metrics["llm_errors_total"]
        tts_errors = self.metrics["tts_errors_total"]
        
        total_requests = (
            self.metrics["stt_requests_total"] + 
            self.metrics["llm_requests_total"] + 
            self.metrics["tts_requests_total"]
        )
        
        total_errors = stt_errors + llm_errors + tts_errors
        error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "active_sessions": self.metrics["active_sessions"],
            "students_online": self.metrics["students_online"],
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate_percent": round(error_rate, 2),
            "cpu_usage_percent": self.metrics["cpu_usage_percent"],
            "memory_usage_percent": self.metrics["memory_usage_percent"],
            "cache_hit_rate": round(self.metrics["cache_hit_rate"], 2),
            "average_accuracy": round(self.metrics["average_accuracy"], 2),
            "health": "healthy" if error_rate < 5 else "degraded" if error_rate < 20 else "critical"
        }
