"""
JWT Authentication Module
Gère l'authentification sécurisée des étudiants via tokens JWT
"""

from datetime import datetime, timedelta
from typing import Optional
import jwt
from fastapi import HTTPException, status
from config import Config
from passlib.context import CryptContext

# Password hashing - using argon2 (more secure and reliable than bcrypt)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class JWTAuth:
    """Authentification JWT pour sécuriser l'accès à l'API"""
    
    def __init__(self, secret_key: str = None, algorithm: str = None):
        self.secret_key = secret_key or Config.JWT_SECRET_KEY
        self.algorithm = algorithm or Config.JWT_ALGORITHM
    
    def create_token(self, student_id: str, email: str = None, expires_in_hours: int = None) -> str:
        """
        Crée un token JWT pour un étudiant
        
        Args:
            student_id: ID unique de l'étudiant
            email: Email de l'étudiant (optionnel)
            expires_in_hours: Durée de validité en heures
            
        Returns:
            str: Token JWT
        """
        expires_in_hours = expires_in_hours or Config.JWT_EXPIRATION_HOURS
        payload = {
            "sub": student_id,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=expires_in_hours)
        }
        if email:
            payload["email"] = email
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token
    
    def verify_token(self, token: str) -> dict:
        """
        Vérifie et décode un token JWT
        
        Args:
            token: Token JWT à vérifier
            
        Returns:
            dict: Payload du token si valide
            
        Raises:
            HTTPException: Si le token est invalide ou expiré
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            student_id = payload.get("sub")
            if student_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token invalide ou expiré"
                )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expiré"
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide"
            )
    
    def refresh_token(self, token: str) -> str:
        """
        Renouvelle un token JWT valide
        
        Args:
            token: Token JWT à renouveler
            
        Returns:
            str: Nouveau token JWT
        """
        payload = self.verify_token(token)
        student_id = payload.get("sub")
        return self.create_token(student_id)
    
    def hash_password(self, password: str) -> str:
        """
        Hache un mot de passe en bcrypt
        
        Args:
            password: Mot de passe en clair
            
        Returns:
            str: Hash bcrypt du mot de passe
        """
        return pwd_context.hash(password)
    
    def verify_password(self, password: str, password_hash: str) -> bool:
        """
        Vérifie qu'un mot de passe correspond à son hash
        
        Args:
            password: Mot de passe en clair à vérifier
            password_hash: Hash bcrypt à comparer
            
        Returns:
            bool: True si le mot de passe est correct
        """
        return pwd_context.verify(password, password_hash)
