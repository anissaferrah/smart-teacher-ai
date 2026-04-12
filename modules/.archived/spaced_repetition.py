"""
Spaced Repetition Module
Planifie les révisions intelligemment entre 1 et 14 jours
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import redis
from config import Config

REDIS_URL = f"redis://{Config.REDIS_HOST}:{Config.REDIS_PORT}/{Config.REDIS_DB}"


class SpacedRepetition:
    """Système de révision espacée (algorithme de Leitner)"""
    
    # Intervales de révision en jours
    REPETITION_INTERVALS = [1, 3, 7, 14]  # Jours
    
    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
    
    def add_concept(self, student_id: str, concept_id: str, course_id: str) -> bool:
        """
        Ajoute un concept à la révision espacée
        
        Args:
            student_id: ID de l'étudiant
            concept_id: ID du concept (terme, définition, formule)
            course_id: ID du cours
            
        Returns:
            bool: Succès de l'ajout
        """
        try:
            key = f"spaced_rep:{student_id}:{course_id}"
            
            concept_data = {
                "concept_id": concept_id,
                "added_at": datetime.utcnow().isoformat(),
                "repetition_count": 0,
                "next_review": datetime.utcnow().isoformat(),
                "easiness_factor": 2.5,  # Facteur de SM-2
                "interval": 0
            }
            
            concepts = self.redis_client.get(key)
            if concepts:
                concepts_list = json.loads(concepts)
            else:
                concepts_list = []
            
            concepts_list.append(concept_data)
            
            self.redis_client.setex(
                key,
                86400 * 60,  # 60 jours TTL
                json.dumps(concepts_list)
            )
            
            return True
        except Exception:
            return False
    
    def get_concepts_to_review(self, student_id: str, course_id: str) -> List[Dict]:
        """
        Retourne les concepts à réviser aujourd'hui
        
        Args:
            student_id: ID de l'étudiant
            course_id: ID du cours
            
        Returns:
            List[Dict]: Concepts à réviser
        """
        try:
            key = f"spaced_rep:{student_id}:{course_id}"
            concepts_data = self.redis_client.get(key)
            
            if not concepts_data:
                return []
            
            concepts = json.loads(concepts_data)
            now = datetime.utcnow()
            
            # Filtre les concepts dont la date de révision est passée
            to_review = [
                c for c in concepts
                if datetime.fromisoformat(c["next_review"]) <= now
            ]
            
            # Trie par date de révision (les plus anciennes en premier)
            to_review.sort(key=lambda x: x["next_review"])
            
            return to_review
        except Exception:
            return []
    
    def mark_concept_reviewed(
        self, 
        student_id: str, 
        course_id: str, 
        concept_id: str, 
        quality: int = 3
    ) -> bool:
        """
        Met à jour un concept après révision (algorithme SM-2)
        
        Args:
            student_id: ID de l'étudiant
            course_id: ID du cours
            concept_id: ID du concept
            quality: Qualité de la réponse (0-5)
                - 0: Black out (oubli complet)
                - 5: Réponse parfaite
            
        Returns:
            bool: Succès
        """
        try:
            key = f"spaced_rep:{student_id}:{course_id}"
            concepts_data = self.redis_client.get(key)
            
            if not concepts_data:
                return False
            
            concepts = json.loads(concepts_data)
            
            # Trouve le concept
            for concept in concepts:
                if concept["concept_id"] == concept_id:
                    # Algorithme SM-2
                    easiness = concept.get("easiness_factor", 2.5)
                    repetition_count = concept.get("repetition_count", 0)
                    
                    # Calcule le nouveau facteur d'aisance
                    new_easiness = easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
                    new_easiness = max(1.3, new_easiness)  # Minimum 1.3
                    
                    # Calcule le nouvel intervale
                    if quality < 3:
                        # Mauvaise réponse, redémarrage
                        new_interval = 1
                        new_repetition_count = 0
                    else:
                        # Bonne réponse
                        if repetition_count == 0:
                            new_interval = 1
                        elif repetition_count == 1:
                            new_interval = 3
                        else:
                            new_interval = int(concept.get("interval", 1) * new_easiness)
                        
                        new_repetition_count = repetition_count + 1
                    
                    # Calcule la date de la prochaine révision
                    next_review = datetime.utcnow() + timedelta(days=new_interval)
                    
                    # Met à jour le concept
                    concept["easiness_factor"] = new_easiness
                    concept["interval"] = new_interval
                    concept["repetition_count"] = new_repetition_count
                    concept["next_review"] = next_review.isoformat()
                    concept["last_reviewed"] = datetime.utcnow().isoformat()
                    
                    break
            
            # Sauvegarde les concepts mis à jour
            self.redis_client.setex(
                key,
                86400 * 60,
                json.dumps(concepts)
            )
            
            return True
        except Exception:
            return False
    
    def get_statistics(self, student_id: str, course_id: str) -> Dict:
        """
        Retourne les statistiques de révision
        
        Args:
            student_id: ID de l'étudiant
            course_id: ID du cours
            
        Returns:
            Dict: Statistiques
        """
        try:
            key = f"spaced_rep:{student_id}:{course_id}"
            concepts_data = self.redis_client.get(key)
            
            if not concepts_data:
                return {
                    "total_concepts": 0,
                    "concepts_to_review": 0,
                    "average_easiness": 2.5
                }
            
            concepts = json.loads(concepts_data)
            now = datetime.utcnow()
            
            to_review = [
                c for c in concepts
                if datetime.fromisoformat(c["next_review"]) <= now
            ]
            
            avg_easiness = sum(c.get("easiness_factor", 2.5) for c in concepts) / len(concepts)
            
            return {
                "total_concepts": len(concepts),
                "concepts_to_review": len(to_review),
                "average_easiness": round(avg_easiness, 2),
                "total_repetitions": sum(c.get("repetition_count", 0) for c in concepts)
            }
        except Exception:
            return {}
