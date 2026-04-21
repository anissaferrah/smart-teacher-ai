"""Centralized logging configuration for SmartTeacher.

This module sets up a consistent logging configuration across all components.
All log setup should go through this module to ensure consistency.
"""

import logging
import sys
from typing import Optional
from infrastructure.config import settings


def setup_logging(
    level: Optional[str] = None,
    format_string: Optional[str] = None,
) -> None:
    """Configure logging for the entire application.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL). If None, uses settings.analytics.log_level
        format_string: Custom format string. If None, uses default ISO format.
    """
    if level is None:
        level = settings.analytics.log_level
    
    if format_string is None:
        format_string = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=format_string,
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    
    # Suppress verbose third-party logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("pydantic").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        logging.Logger: Configured logger
    """
    return logging.getLogger(name)


__all__ = [
    "setup_logging",
    "get_logger",
]
