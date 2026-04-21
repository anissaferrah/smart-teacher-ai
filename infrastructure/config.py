"""Centralized runtime configuration for SmartTeacher.

This module provides a Pydantic-based configuration system that:
- Loads settings from environment variables with defaults
- Provides type-safe access to all configuration
- Supports feature flags (e.g., rate adaptation, confusion detection)
- Centralizes thresholds, timeouts, and hyperparameters

All hardcoded values should be moved here, not in business logic.
"""

from typing import Optional
from pydantic import BaseModel, Field
import os
from pathlib import Path


class AudioConfig(BaseModel):
    """Audio input/output configuration."""
    sample_rate: int = Field(default=16000, description="Audio sample rate in Hz")
    chunk_size: int = Field(default=512, description="Audio chunk size for streaming")
    speech_threshold: float = Field(default=0.3, description="Speech detection threshold")
    silence_duration: float = Field(default=1.0, description="Silence duration to end recording (seconds)")
    max_audio_duration: float = Field(default=30.0, description="Maximum audio length (seconds)")


class STTConfig(BaseModel):
    """Speech-to-text (Whisper) configuration."""
    backend: str = Field(default="faster-whisper", description="STT backend")
    model_size: str = Field(default="base", description="Whisper model size (tiny/base/small/medium/large)")
    device: str = Field(default="cpu", description="Compute device (cpu/cuda)")
    compute_type: str = Field(default="int8", description="Quantization type (int8/int16/float16/float32)")
    num_threads: int = Field(default=4, description="Number of threads for inference")
    min_audio_sec: float = Field(default=0.1, description="Minimum audio length to process (seconds)")
    beam_size: int = Field(default=3, description="Beam search size for decoding")


class LLMConfig(BaseModel):
    """Large Language Model (GPT) configuration."""
    model: str = Field(default="gpt-4o-mini", description="Model ID (gpt-4o-mini/gpt-4/gpt-3.5-turbo)")
    max_tokens: int = Field(default=400, description="Maximum response tokens")
    temperature: float = Field(default=0.7, description="Temperature for generation (0.0-2.0)")
    max_history_turns: int = Field(default=10, description="Maximum conversation history turns to send")


class RAGConfig(BaseModel):
    """Retrieval-Augmented Generation configuration."""
    enabled: bool = Field(default=False, description="Enable RAG")
    num_results: int = Field(default=5, description="Number of documents to retrieve")
    embedding_model: str = Field(default="BAAI/bge-m3", description="Embedding model name")
    db_dir: str = Field(default="data/multimodal_db", description="Qdrant database directory")


class ConfusionDetectionConfig(BaseModel):
    """Confusion detection (SIGHT model) configuration."""
    enabled: bool = Field(default=True, description="Enable confusion detection")
    model_path: Optional[str] = Field(default=None, description="Path to confusion model (auto-resolved if None)")
    confidence_threshold: float = Field(default=0.6, description="Confusion confidence threshold")


class TTSConfig(BaseModel):
    """Text-to-speech configuration."""
    provider: str = Field(default="edge", description="TTS provider (edge/elevenlabs)")
    model: str = Field(default="eleven_multilingual_v2", description="TTS model ID")
    output_format: str = Field(default="mp3_22050_32", description="Audio output format")
    default_voice_fr: str = Field(default="fr-FR-DeniseNeural", description="Default French voice")
    default_voice_en: str = Field(default="en-US-JennyNeural", description="Default English voice")


class RealtimeSessionConfig(BaseModel):
    """Realtime session WebSocket handler configuration."""
    enable_rate_adaptation: bool = Field(
        default=False,
        description="Enable speech rate adaptation based on student profile (disabled until benchmarked)"
    )
    response_timeout_sec: float = Field(default=2.5, description="LLM response timeout (seconds)")
    tts_cache_enabled: bool = Field(default=True, description="Enable TTS caching")
    prefetch_next_slide: bool = Field(default=True, description="Prefetch next slide narration")
    max_concurrent_streams: int = Field(default=3, description="Max concurrent audio streams per session")


class AnalyticsConfig(BaseModel):
    """Analytics and observability configuration."""
    clickhouse_enabled: bool = Field(default=True, description="Enable ClickHouse event sink")
    clickhouse_host: str = Field(default="localhost", description="ClickHouse host")
    clickhouse_port: int = Field(default=9000, description="ClickHouse port")
    clickhouse_db: str = Field(default="smart_teacher", description="ClickHouse database")
    csv_logging_enabled: bool = Field(default=False, description="Enable CSV logging (deprecated, use ClickHouse)")
    log_level: str = Field(default="INFO", description="Log level (DEBUG/INFO/WARNING/ERROR)")


class DatabaseConfig(BaseModel):
    """PostgreSQL database configuration."""
    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    db: str = Field(default="smart_teacher")
    user: str = Field(default="admin")
    password: str = Field(default="secret")
    
    @property
    def url(self) -> str:
        """Construct database URL for SQLAlchemy."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class RedisConfig(BaseModel):
    """Redis cache configuration."""
    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    db: int = Field(default=0)
    
    @property
    def url(self) -> str:
        """Construct Redis URL."""
        return f"redis://{self.host}:{self.port}/{self.db}"


class AppSettings(BaseModel):
    """Complete application settings."""
    
    # Feature enablement
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    confusion: ConfusionDetectionConfig = Field(default_factory=ConfusionDetectionConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    realtime_session: RealtimeSessionConfig = Field(default_factory=RealtimeSessionConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    
    # Infrastructure
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    
    # API Keys
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    elevenlabs_api_key: Optional[str] = Field(default=None, description="ElevenLabs API key")
    
    # Paths
    courses_dir: str = Field(default="courses")
    media_dir: str = Field(default="media")
    logs_dir: str = Field(default="logs")
    
    class Config:
        """Pydantic config."""
        env_file = ".env"
        env_nested_delimiter = "__"  # Allow env vars like AUDIO__SAMPLE_RATE=16000


def load_settings() -> AppSettings:
    """Load settings from environment variables with defaults.
    
    Environment variable naming convention:
    - AUDIO__SAMPLE_RATE=16000
    - STT__MODEL_SIZE=base
    - LLM__TEMPERATURE=0.7
    - DATABASE__HOST=localhost
    - etc.
    
    Returns:
        AppSettings: Fully populated settings object
    """
    # Load from environment
    settings = AppSettings(
        audio=AudioConfig(
            sample_rate=int(os.getenv("AUDIO__SAMPLE_RATE", "16000")),
            chunk_size=int(os.getenv("AUDIO__CHUNK_SIZE", "512")),
            speech_threshold=float(os.getenv("AUDIO__SPEECH_THRESHOLD", "0.3")),
            silence_duration=float(os.getenv("AUDIO__SILENCE_DURATION", "1.0")),
            max_audio_duration=float(os.getenv("AUDIO__MAX_AUDIO_DURATION", "30.0")),
        ),
        stt=STTConfig(
            backend=os.getenv("STT__BACKEND", "faster-whisper"),
            model_size=os.getenv("STT__MODEL_SIZE", "base"),
            device=os.getenv("STT__DEVICE", "cpu"),
            compute_type=os.getenv("STT__COMPUTE_TYPE", "int8"),
            num_threads=int(os.getenv("STT__NUM_THREADS", "4")),
            min_audio_sec=float(os.getenv("STT__MIN_AUDIO_SEC", "0.1")),
            beam_size=int(os.getenv("STT__BEAM_SIZE", "3")),
        ),
        llm=LLMConfig(
            model=os.getenv("LLM__MODEL", "gpt-4o-mini"),
            max_tokens=int(os.getenv("LLM__MAX_TOKENS", "400")),
            temperature=float(os.getenv("LLM__TEMPERATURE", "0.7")),
            max_history_turns=int(os.getenv("LLM__MAX_HISTORY_TURNS", "10")),
        ),
        rag=RAGConfig(
            enabled=os.getenv("RAG__ENABLED", "false").lower() == "true",
            num_results=int(os.getenv("RAG__NUM_RESULTS", "5")),
            embedding_model=os.getenv("RAG__EMBEDDING_MODEL", "BAAI/bge-m3"),
            db_dir=os.getenv("RAG__DB_DIR", "data/multimodal_db"),
        ),
        confusion=ConfusionDetectionConfig(
            enabled=os.getenv("CONFUSION__ENABLED", "true").lower() == "true",
            model_path=os.getenv("CONFUSION__MODEL_PATH"),
            confidence_threshold=float(os.getenv("CONFUSION__CONFIDENCE_THRESHOLD", "0.6")),
        ),
        tts=TTSConfig(
            provider=os.getenv("TTS__PROVIDER", "edge"),
            model=os.getenv("TTS__MODEL", "eleven_multilingual_v2"),
            output_format=os.getenv("TTS__OUTPUT_FORMAT", "mp3_22050_32"),
            default_voice_fr=os.getenv("TTS__DEFAULT_VOICE_FR", "fr-FR-DeniseNeural"),
            default_voice_en=os.getenv("TTS__DEFAULT_VOICE_EN", "en-US-JennyNeural"),
        ),
        realtime_session=RealtimeSessionConfig(
            enable_rate_adaptation=os.getenv("REALTIME_SESSION__ENABLE_RATE_ADAPTATION", "false").lower() == "true",
            response_timeout_sec=float(os.getenv("REALTIME_SESSION__RESPONSE_TIMEOUT_SEC", "2.5")),
            tts_cache_enabled=os.getenv("REALTIME_SESSION__TTS_CACHE_ENABLED", "true").lower() == "true",
            prefetch_next_slide=os.getenv("REALTIME_SESSION__PREFETCH_NEXT_SLIDE", "true").lower() == "true",
            max_concurrent_streams=int(os.getenv("REALTIME_SESSION__MAX_CONCURRENT_STREAMS", "3")),
        ),
        analytics=AnalyticsConfig(
            clickhouse_enabled=os.getenv("ANALYTICS__CLICKHOUSE_ENABLED", "true").lower() == "true",
            clickhouse_host=os.getenv("ANALYTICS__CLICKHOUSE_HOST", "localhost"),
            clickhouse_port=int(os.getenv("ANALYTICS__CLICKHOUSE_PORT", "9000")),
            clickhouse_db=os.getenv("ANALYTICS__CLICKHOUSE_DB", "smart_teacher"),
            csv_logging_enabled=os.getenv("ANALYTICS__CSV_LOGGING_ENABLED", "false").lower() == "true",
            log_level=os.getenv("ANALYTICS__LOG_LEVEL", "INFO"),
        ),
        database=DatabaseConfig(
            host=os.getenv("DATABASE__HOST", "localhost"),
            port=int(os.getenv("DATABASE__PORT", "5432")),
            db=os.getenv("DATABASE__DB", "smart_teacher"),
            user=os.getenv("DATABASE__USER", "admin"),
            password=os.getenv("DATABASE__PASSWORD", "secret"),
        ),
        redis=RedisConfig(
            host=os.getenv("REDIS__HOST", "localhost"),
            port=int(os.getenv("REDIS__PORT", "6379")),
            db=int(os.getenv("REDIS__DB", "0")),
        ),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY"),
        courses_dir=os.getenv("COURSES_DIR", "courses"),
        media_dir=os.getenv("MEDIA_DIR", "media"),
        logs_dir=os.getenv("LOGS_DIR", "logs"),
    )
    
    # Resolve confusion model path if not explicitly set
    if settings.confusion.model_path is None:
        settings.confusion.model_path = str(
            Path(__file__).resolve().parent.parent / "dataset" / "sight-main" / "data" / "processed" / "confusion_model_final.pth"
        )
    
    return settings


# Singleton instance
settings: AppSettings = load_settings()


__all__ = [
    "AppSettings",
    "AudioConfig",
    "STTConfig",
    "LLMConfig",
    "RAGConfig",
    "ConfusionDetectionConfig",
    "TTSConfig",
    "RealtimeSessionConfig",
    "AnalyticsConfig",
    "DatabaseConfig",
    "RedisConfig",
    "load_settings",
    "settings",
]
