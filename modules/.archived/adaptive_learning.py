"""
Adaptive Learning Module
Ajuste la difficulté des questions selon le niveau de l'étudiant
"""

from enum import Enum
from typing import Dict, Optional, Tuple
import json
import redis
from config import Config

REDIS_URL = f"redis://{Config.REDIS_HOST}:{Config.REDIS_PORT}/{Config.REDIS_DB}"


class LearningLevel(Enum):
    """Niveaux d'apprentissage"""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class AdaptiveLearning:
    """Gestion de l'apprentissage adaptatif"""
    
    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Seuils de progression
        self.level_thresholds = {
            "beginner_to_intermediate": 0.70,      # 70% de réussite
            "intermediate_to_advanced": 0.85       # 85% de réussite
        }
    
    def get_student_level(self, student_id: str) -> LearningLevel:
        """
        Détermine le niveau d'apprentissage de l'étudiant
        
        Args:
            student_id: ID de l'étudiant
            
        Returns:
            LearningLevel: Niveau d'apprentissage
        """
        try:
            profile_key = f"student_profile:{student_id}"
            profile = self.redis_client.get(profile_key)
            
            if profile:
                data = json.loads(profile)
                level = data.get("learning_level", "beginner")
                return LearningLevel(level)
        except Exception:
            pass
        
        return LearningLevel.BEGINNER
    
    def get_difficulty_parameters(self, student_id: str) -> Dict[str, any]:
        """
        Retourne les paramètres de difficulté pour l'étudiant
        
        Args:
            student_id: ID de l'étudiant
            
        Returns:
            Dict: Paramètres (nombre de questions, durée, types)
        """
        level = self.get_student_level(student_id)
        
        params = {
            "beginner": {
                "questions_per_session": 5,
                "time_per_question_seconds": 60,
                "question_types": ["definition", "simple_concept"],
                "hint_frequency": "always",
                "difficulty_score": 1.0
            },
            "intermediate": {
                "questions_per_session": 8,
                "time_per_question_seconds": 45,
                "question_types": ["concept", "application", "analysis"],
                "hint_frequency": "on_request",
                "difficulty_score": 2.0
            },
            "advanced": {
                "questions_per_session": 10,
                "time_per_question_seconds": 30,
                "question_types": ["synthesis", "evaluation", "case_study"],
                "hint_frequency": "rarely",
                "difficulty_score": 3.0
            }
        }
        
        return params.get(level.value, params["beginner"])
    
    def evaluate_response(self, student_id: str, correct: bool, difficulty_score: float) -> None:
        """
        Évalue la réponse et ajuste le profil
        
        Args:
            student_id: ID de l'étudiant
            correct: Si la réponse est correcte
            difficulty_score: Score de difficulté de la question
        """
        profile_key = f"student_profile:{student_id}"
        
        try:
            profile_data = self.redis_client.get(profile_key)
            
            if profile_data:
                profile = json.loads(profile_data)
            else:
                profile = {
                    "student_id": student_id,
                    "learning_level": "beginner",
                    "correct_answers": 0,
                    "total_answers": 0,
                    "accuracy": 0.0
                }
            
            profile["total_answers"] += 1
            if correct:
                profile["correct_answers"] += 1
            
            profile["accuracy"] = profile["correct_answers"] / profile["total_answers"]
            
            # Progression automatique
            self._check_level_progression(profile)
            
            # Sauvegarde le profil mis à jour
            self.redis_client.setex(
                profile_key,
                86400 * 30,  # 30 jours TTL
                json.dumps(profile)
            )
        except Exception as e:
            print(f"Erreur lors de l'évaluation: {str(e)}")
    
    def _check_level_progression(self, profile: Dict) -> None:
        """
        Vérifie et met à jour le niveau basé sur la précision
        
        Args:
            profile: Profil de l'étudiant
        """
        current_level = profile.get("learning_level", "beginner")
        accuracy = profile.get("accuracy", 0.0)
        
        if current_level == "beginner" and accuracy >= self.level_thresholds["beginner_to_intermediate"]:
            profile["learning_level"] = "intermediate"
        
        elif current_level == "intermediate" and accuracy >= self.level_thresholds["intermediate_to_advanced"]:
            profile["learning_level"] = "advanced"
    
    def get_recommended_topics(self, student_id: str) -> list:
        """
        Recommande les sujets à réviser basé sur les erreurs
        
        Args:
            student_id: ID de l'étudiant
            
        Returns:
            list: Sujets recommandés triés par priorité
        """
        try:
            mistakes_key = f"student_mistakes:{student_id}"
            mistakes_data = self.redis_client.get(mistakes_key)
            
            if mistakes_data:
                mistakes = json.loads(mistakes_data)
                # Trie par fréquence d'erreur
                sorted_topics = sorted(mistakes.items(), key=lambda x: x[1], reverse=True)
                return [topic for topic, count in sorted_topics]
        except Exception:
            pass
        
        return []
