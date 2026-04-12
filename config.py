"""Smart Teacher — Configuration"""

import os
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
except Exception:
    pass


class Config:
    """Smart Teacher Configuration"""

    # API Keys
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    ELEVENLABS_API_KEY: Optional[str] = os.getenv("ELEVENLABS_API_KEY")

    # Database
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "smart_teacher")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "admin")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "secret")

    DATABASE_URL: str = (
        f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )

    # Redis
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))

    # Audio
    SAMPLE_RATE: int = 16000
    CHUNK_SIZE: int = 512
    SPEECH_THRESHOLD: float = 0.3        # Lowered from 0.5 → better speech detection
    SILENCE_DURATION: float = 1.0        # Reduced from 1.5 → faster response
    MAX_AUDIO_DURATION: float = 30.0

    # STT (Whisper)
    WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "base")
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "cpu")
    WHISPER_COMPUTE: str = os.getenv("WHISPER_COMPUTE", "int8")
    WHISPER_THREADS: int = int(os.getenv("WHISPER_THREADS", "4"))
    STT_MIN_AUDIO_SEC: float = float(os.getenv("STT_MIN_AUDIO_SEC", "0.1"))  # Reduced from 0.45 - trim_silence was removing too much
    STT_BEAM_SIZE: int = int(os.getenv("STT_BEAM_SIZE", "3"))

    # LLM (GPT)
    GPT_MODEL: str = os.getenv("GPT_MODEL", "gpt-4o-mini")
    GPT_MAX_TOKENS: int = int(os.getenv("GPT_MAX_TOKENS", "400"))
    GPT_TEMPERATURE: float = float(os.getenv("GPT_TEMPERATURE", "0.7"))
    MAX_HISTORY_TURNS: int = int(os.getenv("MAX_HISTORY_TURNS", "10"))

    # RAG (Retrieval-Augmented Generation)
    RAG_ENABLED: bool = os.getenv("RAG_ENABLED", "false").lower() == "true"  # Disabled temporarily (OpenAI quota)
    RAG_NUM_RESULTS: int = int(os.getenv("RAG_NUM_RESULTS", "5"))
    RAG_EMBEDDING_MODEL: str = os.getenv("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    RAG_DB_DIR: str = os.getenv("RAG_DB_DIR", "data/multimodal_db")

    # Qdrant
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "smart_teacher_multimodal")

    # TTS
    TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "edge")
    TTS_VOICE: str = os.getenv("TTS_VOICE", "default")
    TTS_MODEL: str = os.getenv("TTS_MODEL", "eleven_multilingual_v2")
    TTS_OUTPUT_FORMAT: str = os.getenv("TTS_OUTPUT_FORMAT", "mp3_22050_32")

    EDGE_VOICES = {
        "fr": "fr-FR-DeniseNeural",
        "ar": "ar-SA-ZariyahNeural",
        "en": "en-US-JennyNeural",
    }

    # Paths
    COURSES_DIR: str = os.getenv("COURSES_DIR", "courses")
    MEDIA_DIR: str = os.getenv("MEDIA_DIR", "media")
    SLIDES_DIR: str = f"{MEDIA_DIR}/slides"
    LOGS_DIR: str = os.getenv("LOGS_DIR", "logs")
    DATABASE_DIR: str = "database"

    # Server
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))

    # Performance KPIs
    MAX_RESPONSE_TIME: float = 5.0
    # MAX_INTERRUPTION_LATENCY: float = 0.5  # [UNUSED v1.0]
    # TARGET_WER_FR: float = 0.10  # [UNUSED v1.0]
    # TARGET_WER_AR: float = 0.20  # [UNUSED v1.0]
    # TARGET_WER_EN: float = 0.10  # [UNUSED v1.0]
    TARGET_RTF: float = 0.50

    # Logs
    CSV_LOG_FILE: str = os.getenv("CSV_LOG_FILE", "logs/metrics.csv")
    STT_LOG_FILE: str = os.getenv("STT_LOG_FILE", "logs/stt_metrics.csv")

    # Presentation
    # AUTO_ADVANCE_SECTIONS: bool = os.getenv("AUTO_ADVANCE_SECTIONS", "false").lower() == "true"  # [UNUSED v1.0]

    # ============================================================================
    # v2.0 MODULES - Security, Performance, Resilience, Learning (ARCHIVED)
    # [NOT USED IN V1.0 - ENABLE WHEN READY FOR v2.0]
    # ============================================================================

    # # JWT Authentication (v2.0)
    # JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
    # JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    # JWT_EXPIRATION_HOURS: int = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

    # # Rate Limiting (v2.0)
    # RATE_LIMIT_REQUESTS_PER_HOUR: int = int(os.getenv("RATE_LIMIT_REQUESTS_PER_HOUR", "100"))
    # RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "3600"))

    # # LLM Cache (v2.0)
    # LLM_CACHE_TTL: int = int(os.getenv("LLM_CACHE_TTL", "86400"))  # 24 hours
    # LLM_CACHE_MAX_SIZE: int = int(os.getenv("LLM_CACHE_MAX_SIZE", "10000"))

    # # Circuit Breaker (OpenAI) (v2.0)
    # OPENAI_FAILURE_THRESHOLD: int = int(os.getenv("OPENAI_FAILURE_THRESHOLD", "5"))
    # OPENAI_RECOVERY_TIMEOUT: int = int(os.getenv("OPENAI_RECOVERY_TIMEOUT", "60"))

    # # Adaptive Learning (v2.0)
    # ADAPTIVE_LEVEL_EASY_THRESHOLD: float = float(os.getenv("ADAPTIVE_LEVEL_EASY_THRESHOLD", "0.70"))
    # ADAPTIVE_LEVEL_HARD_THRESHOLD: float = float(os.getenv("ADAPTIVE_LEVEL_HARD_THRESHOLD", "0.85"))
    # ADAPTIVE_QUESTIONS_PER_SESSION: dict = {
    #     "beginner": int(os.getenv("ADAPTIVE_BEGINNER_QUESTIONS", "5")),
    #     "intermediate": int(os.getenv("ADAPTIVE_INTERMEDIATE_QUESTIONS", "7")),
    #     "advanced": int(os.getenv("ADAPTIVE_ADVANCED_QUESTIONS", "10"))
    # }

    # # Spaced Repetition (SM-2) (v2.0)
    # SPACED_REP_INITIAL_INTERVAL: int = int(os.getenv("SPACED_REP_INITIAL_INTERVAL", "1"))
    # SPACED_REP_INITIAL_EASE: float = float(os.getenv("SPACED_REP_INITIAL_EASE", "2.5"))
    # SPACED_REP_MIN_EASE: float = float(os.getenv("SPACED_REP_MIN_EASE", "1.3"))

    # # Gamification (v2.0)
    # GAMIFICATION_POINTS_CORRECT: int = int(os.getenv("GAMIFICATION_POINTS_CORRECT", "10"))
    # GAMIFICATION_POINTS_SPEED: int = int(os.getenv("GAMIFICATION_POINTS_SPEED", "5"))
    # GAMIFICATION_POINTS_DAILY_STREAK: int = int(os.getenv("GAMIFICATION_POINTS_DAILY_STREAK", "50"))
    # GAMIFICATION_POINTS_LEVEL_UP: int = int(os.getenv("GAMIFICATION_POINTS_LEVEL_UP", "100"))
    # GAMIFICATION_POINTS_PERFECT_SESSION: int = int(os.getenv("GAMIFICATION_POINTS_PERFECT_SESSION", "200"))

    # # Speaker Diarization (v2.0)
    # SPEAKER_DIARIZATION_THRESHOLD: float = float(os.getenv("SPEAKER_DIARIZATION_THRESHOLD", "0.75"))

    # # Audio Compression (v2.0)
    # AUDIO_BITRATE_KBPS: int = int(os.getenv("AUDIO_BITRATE_KBPS", "16"))
    # AUDIO_FORMAT: str = os.getenv("AUDIO_FORMAT", "opus")  # opus or mp3

    # # Structured Logger (v2.0)
    # STRUCTURED_LOG_DIR: str = os.getenv("STRUCTURED_LOG_DIR", "logs")
    # STRUCTURED_LOG_LEVEL: str = os.getenv("STRUCTURED_LOG_LEVEL", "INFO")

    # # Prometheus Metrics (v2.0)
    # PROMETHEUS_PORT: int = int(os.getenv("PROMETHEUS_PORT", "8001"))
    # PROMETHEUS_ENABLED: bool = os.getenv("PROMETHEUS_ENABLED", "true").lower() == "true"

    # # Resilience & Retry (v2.0)
    # RESILIENCE_MAX_RETRIES: int = int(os.getenv("RESILIENCE_MAX_RETRIES", "3"))
    # RESILIENCE_INITIAL_DELAY: float = float(os.getenv("RESILIENCE_INITIAL_DELAY", "0.1"))
    # RESILIENCE_MAX_DELAY: float = float(os.getenv("RESILIENCE_MAX_DELAY", "60"))
    # RESILIENCE_BACKOFF_BASE: float = float(os.getenv("RESILIENCE_BACKOFF_BASE", "2.0"))

    @classmethod
    def validate(cls) -> None:
        """Check critical parameters at startup"""
        errors = []
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY missing in .env")
        if cls.TTS_PROVIDER == "elevenlabs" and not cls.ELEVENLABS_API_KEY:
            errors.append("ELEVENLABS_API_KEY missing (required if TTS_PROVIDER=elevenlabs)")

        if errors:
            print("\n" + "=" * 60)
            print("❌ CONFIGURATION ERRORS")
            print("=" * 60)
            for err in errors:
                print(f"   • {err}")
            print("\n💡 Create .env file:")
            print("   OPENAI_API_KEY=sk-...")
            print("   ELEVENLABS_API_KEY=... (optional)")
            print("=" * 60 + "\n")
            sys.exit(1)
        print("✅ Configuration validated")

    @classmethod
    def print_info(cls) -> None:
        """Display active configuration"""
        print("\n" + "=" * 60)
        print("⚙️  SMART TEACHER — CONFIGURATION")
        print("=" * 60)
        print(f"\n🎙️  AUDIO:  {cls.SAMPLE_RATE}Hz | chunk={cls.CHUNK_SIZE} | silence={cls.SILENCE_DURATION}s")
        print(f"🧠 STT:    Whisper {cls.WHISPER_MODEL_SIZE} | {cls.WHISPER_DEVICE} | {cls.WHISPER_COMPUTE}")
        print(f"💬 LLM:    {cls.GPT_MODEL} | max_tokens={cls.GPT_MAX_TOKENS} | history={cls.MAX_HISTORY_TURNS}")
        print(f"🔊 TTS:    {cls.TTS_PROVIDER}")
        print(f"📚 RAG:    {cls.RAG_DB_DIR} | top-k={cls.RAG_NUM_RESULTS}")
        print(f"🌐 Server: {cls.SERVER_HOST}:{cls.SERVER_PORT}")
        print(f"\n🎯 KPIs:   response<{cls.MAX_RESPONSE_TIME}s | RTF<{cls.TARGET_RTF}")
        print("=" * 60 + "\n")
