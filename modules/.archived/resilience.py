"""
Resilience Module
Retenues automatiques avec backoff exponentiel + fallbacks
"""

import time
import asyncio
from typing import Callable, Any, Optional, TypeVar, Coroutine
from functools import wraps
import logging


T = TypeVar('T')


class ExponentialBackoff:
    """Backoff exponentiel pour les retenues"""
    
    def __init__(
        self,
        initial_delay: float = 0.1,
        max_delay: float = 60,
        exponential_base: float = 2,
        jitter: bool = True
    ):
        """
        Initialise la stratégie de backoff
        
        Args:
            initial_delay: Délai initial en secondes
            max_delay: Délai maximal en secondes
            exponential_base: Base de l'exponentielle
            jitter: Ajoute du hasard pour éviter les pics
        """
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay(self, attempt: int) -> float:
        """
        Calcule le délai pour une tentative
        
        Args:
            attempt: Numéro de tentative (commence à 0)
            
        Returns:
            float: Délai en secondes
        """
        delay = self.initial_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            import random
            # Ajoute du jitter ±10%
            jitter_range = delay * 0.1
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0, delay)


class Resilience:
    """Gestion de la résilience avec retenues et fallbacks"""
    
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 0.1,
        max_delay: float = 60,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialise la résilience
        
        Args:
            max_retries: Nombre maximal de retenues
            initial_delay: Délai initial en secondes
            max_delay: Délai maximal en secondes
            logger: Logger personnalisé
        """
        self.max_retries = max_retries
        self.backoff = ExponentialBackoff(initial_delay, max_delay)
        self.logger = logger or logging.getLogger(__name__)
    
    def retry(
        self,
        func: Callable,
        *args,
        retryable_exceptions: tuple = (Exception,),
        **kwargs
    ) -> Any:
        """
        Exécute une fonction avec retenues
        
        Args:
            func: Fonction à exécuter
            *args: Paramètres positionnels
            retryable_exceptions: Types d'exception à reessayer
            **kwargs: Paramètres nommés
            
        Returns:
            Résultat de la fonction
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            
            except retryable_exceptions as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    delay = self.backoff.get_delay(attempt)
                    self.logger.warning(
                        f"Tentative {attempt + 1}/{self.max_retries + 1} échouée. "
                        f"Nouvelle tentative dans {delay:.2f}s. Erreur: {str(e)}"
                    )
                    time.sleep(delay)
                else:
                    self.logger.error(f"Toutes les tentatives échouées après {self.max_retries + 1} essais")
                    raise
        
        raise last_exception
    
    async def async_retry(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args,
        retryable_exceptions: tuple = (Exception,),
        **kwargs
    ) -> T:
        """
        Exécute une coroutine avec retenues
        
        Args:
            func: Coroutine à exécuter
            *args: Paramètres positionnels
            retryable_exceptions: Types d'exception à reessayer
            **kwargs: Paramètres nommés
            
        Returns:
            Résultat de la coroutine
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            
            except retryable_exceptions as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    delay = self.backoff.get_delay(attempt)
                    self.logger.warning(
                        f"Tentative async {attempt + 1}/{self.max_retries + 1} échouée. "
                        f"Nouvelle tentative dans {delay:.2f}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(f"Toutes les tentatives async échouées")
                    raise
        
        raise last_exception
    
    def retry_decorator(
        self,
        retryable_exceptions: tuple = (Exception,),
        fallback_value: Optional[Any] = None
    ):
        """
        Décorateur pour ajouter des retenues à une fonction
        
        Args:
            retryable_exceptions: Types d'exception à reessayer
            fallback_value: Valeur par défaut en cas d'échec complet
            
        Returns:
            Décorateur
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                try:
                    return self.retry(
                        func,
                        *args,
                        retryable_exceptions=retryable_exceptions,
                        **kwargs
                    )
                except Exception as e:
                    self.logger.error(f"Fonction {func.__name__} échouée après retenues: {str(e)}")
                    if fallback_value is not None:
                        return fallback_value
                    raise
            
            return wrapper
        return decorator
    
    def async_retry_decorator(
        self,
        retryable_exceptions: tuple = (Exception,),
        fallback_value: Optional[Any] = None
    ):
        """
        Décorateur pour ajouter des retenues à une coroutine
        
        Args:
            retryable_exceptions: Types d'exception à reessayer
            fallback_value: Valeur par défaut en cas d'échec complet
            
        Returns:
            Décorateur async
        """
        def decorator(func: Callable[..., Coroutine]) -> Callable[..., Coroutine]:
            @wraps(func)
            async def wrapper(*args, **kwargs) -> Any:
                try:
                    return await self.async_retry(
                        func,
                        *args,
                        retryable_exceptions=retryable_exceptions,
                        **kwargs
                    )
                except Exception as e:
                    self.logger.error(f"Coroutine {func.__name__} échouée après retenues: {str(e)}")
                    if fallback_value is not None:
                        return fallback_value
                    raise
            
            return wrapper
        return decorator


# Instances globales pour faciliter l'utilisation
default_resilience = Resilience(max_retries=3)
