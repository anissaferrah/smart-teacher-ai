"""
Local LLM Fallback Module
Si OpenAI plante, utilise Ollama (Mistral) en local
Installation: ollama run mistral (ou otra modelo)
URL: http://localhost:11434
"""

import logging
import requests
from typing import Optional

log = logging.getLogger("SmartTeacher.LocalLLM")


class LocalLLMFallback:
    """Fallback vers Ollama local si OpenAI indisponible"""
    
    def __init__(self, model: str = "mistral", base_url: str = "http://localhost:11434"):
        """
        Initialise le fallback LLM local
        
        Args:
            model: Modèle Ollama ("mistral", "neural-chat", "orca-mini", etc.)
            base_url: URL du serveur Ollama
        """
        self.model = model
        self.base_url = base_url
        self.endpoint = f"{base_url}/api/generate"
        self.available = self._check_availability()
    
    def _check_availability(self) -> bool:
        """Vérifier si Ollama est accessible"""
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=None  # Pas de timeout pour laisser Ollama démarrer à son rythme
            )
            if response.status_code == 200:
                models = response.json().get('models', [])
                model_names = [m.get('name', '').split(':')[0] for m in models]
                is_available = any(self.model in name for name in model_names)
                if is_available:
                    log.info(f"✅ Ollama actif - modèle '{self.model}' chargé")
                else:
                    log.warning(f"⚠️ Service Ollama actif, modèle '{self.model}' non présent")
                    log.info(f"   Modèles disponibles: {model_names}")
                return is_available
        except requests.exceptions.ConnectionError:
            log.warning(f"⚠️ Ollama non connecté sur {self.base_url}")
            log.warning(f"   👇 Lancez: docker-compose up -d ollama")
        except Exception as e:
            log.warning(f"⚠️ Ollama check (échec): {e}")
        
        return False
    
    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> Optional[str]:
        """
        Générer réponse avec Ollama en local
        
        Args:
            prompt: Question/instruction
            temperature: Créativité (0.0-1.0)
            max_tokens: Longueur max réponse
            
        Returns:
            Texte généré ou None si erreur
        """
        
        if not self.available:
            return None
        
        try:
            log.info(f"🖥️ Generating with local LLM (Ollama/{self.model})...")
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "temperature": temperature,
                "num_predict": max_tokens,
                "stream": False,
            }
            
            response = requests.post(
                self.endpoint,
                json=payload,
                timeout=None  # Pas de timeout pour laisser Ollama répondre à son rythme
            )
            
            if response.status_code == 200:
                result = response.json()
                generated_text = result.get('response', '').strip()
                
                if generated_text:
                    log.info(f"✅ Local LLM generated {len(generated_text)} chars")
                    return generated_text
                else:
                    log.warning("⚠️ Local LLM returned empty response")
                    return None
            else:
                log.error(f"❌ Local LLM error: HTTP {response.status_code}")
                return None
        
        except requests.exceptions.Timeout:
            log.error(f"❌ Local LLM timeout (>60s)")
            return None
        except requests.exceptions.ConnectionError:
            log.error(f"❌ Local LLM connection error")
            self.available = False
            return None
        except Exception as e:
            log.error(f"❌ Local LLM error: {e}")
            return None
    
    async def generate_educational(
        self,
        question: str,
        subject: str = "general",
        level: str = "intermediate"
    ) -> Optional[str]:
        """
        Générer réponse pédagogique avec Ollama
        
        Args:
            question: Question de l'étudiant
            subject: Sujet (math, sciences, histoire, etc.)
            level: Niveau (beginner, intermediate, advanced)
            
        Returns:
            Explication pédagogique
        """
        
        # Prompt pédagogique spécialisé
        system_prompt = f"""Tu es un professeur pédagogique en {subject}.
Réponds clairement et pédagogiquement au niveau {level}.
Utilise des exemples concrets.
Reste concis (max 300 mots)."""
        
        full_prompt = f"{system_prompt}\n\nÉtudiant: {question}\n\nProfesseur:"
        
        return await self.generate(
            prompt=full_prompt,
            temperature=0.6,  # Plus déterministe pour éducation
            max_tokens=300
        )
    
    async def health_check(self) -> dict:
        """Vérifier santé du serveur Ollama"""
        return {
            "available": self.available,
            "model": self.model,
            "endpoint": self.endpoint,
            "status": "✅ Ready" if self.available else "❌ Unavailable"
        }
