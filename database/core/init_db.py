# database/init_db.py
"""
Smart Teacher — Initialisation de la base de données PostgreSQL
"""

import logging
import sys
from pathlib import Path

# Add parent directory to path to import config
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

from config import Config
from database.models import (
    Base, 
    Student, Course, Chapter, Section, Concept, 
    LearningSession, Interaction,
    LearningEvent,
    StudentProfile, StudentMistake,
    RAGChunk, SystemLog, PerformanceMetric, LLMCache
)

log = logging.getLogger("SmartTeacher.Database")

# Engine AsyncPG
engine = create_async_engine(
    Config.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def create_tables():
    """Crée toutes les tables si elles n'existent pas."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("✅ Tables PostgreSQL créées/vérifiées")


async def get_db():
    """Dépendance FastAPI pour obtenir une session DB."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_db_connection() -> bool:
    """Vérifie la connexion à PostgreSQL."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("✅ Connexion PostgreSQL établie")
        return True
    except Exception as e:
        log.warning(f"⚠️ Connexion PostgreSQL indisponible: {e}")
        return False