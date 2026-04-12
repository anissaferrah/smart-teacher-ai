"""
Gamification Module
Points XP, badges, classements pour motiver les étudiants
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import Enum
import json
import redis
from config import Config

REDIS_URL = f"redis://{Config.REDIS_HOST}:{Config.REDIS_PORT}/{Config.REDIS_DB}"


class BadgeType(Enum):
    """Types de badges"""
    FIRST_STEP = "first_step"           # Première leçon terminée
    STREAK_7 = "streak_7"               # 7 jours consécutifs
    STREAK_30 = "streak_30"             # 30 jours consécutifs
    PERFECT_SCORE = "perfect_score"     # Score parfait
    SPEED_DEMON = "speed_demon"         # Réponses rapides
    MASTER = "master"                   # Maîtrise d'un sujet


class Gamification:
    """Système de gamification avec points et badges"""
    
    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Points par action
        self.points_config = {
            "correct_answer": 10,
            "bonus_speed": 5,              # +5 si réponse en < 10s
            "daily_streak": 50,            # Bonus quotidien
            "level_up": 100,               # Passage de niveau
            "perfect_session": 200        # Session parfaite
        }
        
        # Badges et critères
        self.badges = {
            "first_step": {"icon": "🎯", "description": "Première leçon terminée"},
            "streak_7": {"icon": "🔥", "description": "7 jours consécutifs"},
            "streak_30": {"icon": "🌟", "description": "30 jours consécutifs"},
            "perfect_score": {"icon": "💯", "description": "Score parfait"},
            "speed_demon": {"icon": "⚡", "description": "5 réponses rapides"},
            "master": {"icon": "👑", "description": "Maître d'un sujet"}
        }
    
    def add_points(self, student_id: str, points: int, reason: str) -> bool:
        """
        Ajoute des points à l'étudiant
        
        Args:
            student_id: ID de l'étudiant
            points: Nombre de points à ajouter
            reason: Raison de l'ajout (pour l'historique)
            
        Returns:
            bool: Succès
        """
        try:
            key = f"student_gamification:{student_id}"
            
            profile_data = self.redis_client.get(key)
            if profile_data:
                profile = json.loads(profile_data)
            else:
                profile = {
                    "student_id": student_id,
                    "total_points": 0,
                    "level": 1,
                    "badges": [],
                    "daily_streak": 0,
                    "last_activity": None,
                    "points_history": []
                }
            
            profile["total_points"] += points
            profile["points_history"].append({
                "date": datetime.utcnow().isoformat(),
                "points": points,
                "reason": reason
            })
            
            # Vérifie l'augmentation de niveau (100 points/niveau)
            new_level = (profile["total_points"] // 100) + 1
            if new_level > profile["level"]:
                profile["level"] = new_level
            
            # Limite l'historique à 100 dernières entrées
            profile["points_history"] = profile["points_history"][-100:]
            
            # Sauvegarde
            self.redis_client.setex(
                key,
                86400 * 365,
                json.dumps(profile)
            )
            
            return True
        except Exception:
            return False
    
    def unlock_badge(self, student_id: str, badge_type: str) -> bool:
        """
        Déverrouille un badge pour l'étudiant
        
        Args:
            student_id: ID de l'étudiant
            badge_type: Type de badge
            
        Returns:
            bool: Succès
        """
        try:
            key = f"student_gamification:{student_id}"
            
            profile_data = self.redis_client.get(key)
            if not profile_data:
                return False
            
            profile = json.loads(profile_data)
            
            if badge_type not in [b["type"] for b in profile.get("badges", [])]:
                badge_info = self.badges.get(badge_type, {})
                profile.setdefault("badges", []).append({
                    "type": badge_type,
                    "icon": badge_info.get("icon", "🏆"),
                    "description": badge_info.get("description", ""),
                    "unlocked_at": datetime.utcnow().isoformat()
                })
                
                # Ajoute des points bonus pour le badge
                self.add_points(student_id, 250, f"Badge déverrouillé: {badge_type}")
            
            # Sauvegarde
            self.redis_client.setex(
                key,
                86400 * 365,
                json.dumps(profile)
            )
            
            return True
        except Exception:
            return False
    
    def update_daily_streak(self, student_id: str) -> Dict:
        """
        Met à jour la série quotidienne de l'étudiant
        
        Args:
            student_id: ID de l'étudiant
            
        Returns:
            Dict: Informations de série
        """
        try:
            key = f"student_gamification:{student_id}"
            
            profile_data = self.redis_client.get(key)
            if not profile_data:
                return {"streak": 0}
            
            profile = json.loads(profile_data)
            
            last_activity = profile.get("last_activity")
            now = datetime.utcnow()
            
            if last_activity:
                last_date = datetime.fromisoformat(last_activity)
                days_since = (now - last_date).days
                
                if days_since == 0:
                    # Même jour, pas de changement
                    return {"streak": profile.get("daily_streak", 0)}
                elif days_since == 1:
                    # Jour suivant, augmente la série
                    profile["daily_streak"] = profile.get("daily_streak", 0) + 1
                else:
                    # Plus d'un jour, réinitialise
                    profile["daily_streak"] = 1
            else:
                # Premier jour
                profile["daily_streak"] = 1
            
            # Bonus pour les séries
            streak = profile["daily_streak"]
            if streak == 7:
                self.unlock_badge(student_id, "streak_7")
            elif streak == 30:
                self.unlock_badge(student_id, "streak_30")
            
            profile["last_activity"] = now.isoformat()
            
            self.redis_client.setex(
                key,
                86400 * 365,
                json.dumps(profile)
            )
            
            return {"streak": streak}
        except Exception:
            return {}
    
    def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        """
        Retourne le classement des top étudiants
        
        Args:
            limit: Nombre de résultats
            
        Returns:
            List[Dict]: Classement
        """
        try:
            # Balance (scan Redis ne renvoie pas les valeurs)
            # En production, utiliser une base de données
            leaderboard = []
            
            # Simule un classement (à remplacer par une vraie requête)
            # Dans un cas réel, on userait une sorted set Redis
            
            return leaderboard[:limit]
        except Exception:
            return []
    
    def get_student_profile(self, student_id: str) -> Optional[Dict]:
        """
        Retourne le profil de gamification de l'étudiant
        
        Args:
            student_id: ID de l'étudiant
            
        Returns:
            Dict: Profil de gamification
        """
        try:
            key = f"student_gamification:{student_id}"
            profile_data = self.redis_client.get(key)
            
            if profile_data:
                return json.loads(profile_data)
            return None
        except Exception:
            return None
