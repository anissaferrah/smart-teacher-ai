"""
╔══════════════════════════════════════════════════════════════════════╗
║           SMART TEACHER — Configuration Centralisée                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration centrale du projet Smart Teacher."""

    # ══════════════════════════════════════════════════════════════════
    # API KEYS  (dans .env — ne jamais commiter!)
    # ══════════════════════════════════════════════════════════════════
    OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")   # optionnel

    # ══════════════════════════════════════════════════════════════════
    # INFRASTRUCTURE (DB/Cache)
    # ══════════════════════════════════════════════════════════════════
    POSTGRES_HOST      = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT      = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB        = os.getenv("POSTGRES_DB", "smart_teacher")
    POSTGRES_USER      = os.getenv("POSTGRES_USER", "admin")
    POSTGRES_PASSWORD  = os.getenv("POSTGRES_PASSWORD", "secret")
    DATABASE_URL       = os.getenv(
        "DATABASE_URL",
        (
            f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
            f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
        ),
    )

    # ══════════════════════════════════════════════════════════════════
    # AUDIO — Capture microphone
    # ══════════════════════════════════════════════════════════════════
    SAMPLE_RATE        = 16000   # Hz — Whisper exige 16 kHz
    CHUNK_SIZE         = 512     # Samples par chunk (~32 ms)
    SPEECH_THRESHOLD   = 0.5     # Seuil VAD Silero (0–1)
    SILENCE_DURATION   = 1.5     # Secondes de silence → envoi Whisper
    MAX_AUDIO_DURATION = 30.0    # Durée max d'un segment (s)

    # ══════════════════════════════════════════════════════════════════
    # STT — Whisper
    # ══════════════════════════════════════════════════════════════════
    WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "tiny")   # tiny|base|small|medium|large-v3
    WHISPER_DEVICE     = os.getenv("WHISPER_DEVICE", "cpu")
    WHISPER_COMPUTE    = os.getenv("WHISPER_COMPUTE", "int8")      # int8 = rapide + peu de RAM
    WHISPER_THREADS    = int(os.getenv("WHISPER_THREADS", "4"))

    # ══════════════════════════════════════════════════════════════════
    # LLM — OpenAI
    # ══════════════════════════════════════════════════════════════════
    GPT_MODEL          = os.getenv("GPT_MODEL", "gpt-4o-mini")     # ou "gpt-4o" pour plus de précision
    GPT_MAX_TOKENS     = int(os.getenv("GPT_MAX_TOKENS", "400"))
    GPT_TEMPERATURE    = float(os.getenv("GPT_TEMPERATURE", "0.7"))
    MAX_HISTORY_TURNS  = int(os.getenv("MAX_HISTORY_TURNS", "10"))  # Paires (user+assistant) gardées

    # ══════════════════════════════════════════════════════════════════
    # RAG — Qdrant multimodal
    # ══════════════════════════════════════════════════════════════════
    RAG_DB_DIR         = os.getenv("RAG_DB_DIR", "data/multimodal_db")
    RAG_NUM_RESULTS    = int(os.getenv("RAG_NUM_RESULTS", "5"))      # Chunks retournés par requête
    RAG_COLLECTION     = os.getenv("RAG_COLLECTION", "smart_teacher_multimodal")

    # Ancien RAG Chroma (gardé pour compatibilité)
    RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    VECTORSTORE_DIR     = os.getenv("VECTORSTORE_DIR", "data/chroma_db")

    # ══════════════════════════════════════════════════════════════════
    # TTS — Edge-TTS (gratuit) + ElevenLabs (optionnel)
    # ══════════════════════════════════════════════════════════════════
    TTS_PROVIDER       = os.getenv("TTS_PROVIDER", "edge")            # "edge" | "elevenlabs"
    TTS_MODEL          = os.getenv("TTS_MODEL", "eleven_multilingual_v2")
    TTS_OUTPUT_FORMAT  = os.getenv("TTS_OUTPUT_FORMAT", "mp3_22050_32")

    # Voix Edge-TTS par langue
    EDGE_VOICES = {
        "fr": "fr-FR-DeniseNeural",
        "ar": "ar-SA-ZariyahNeural",
        "en": "en-US-JennyNeural",
        "tr": "tr-TR-EmelNeural",
    }
    EDGE_DEFAULT_VOICE = "en-US-JennyNeural"

    # ══════════════════════════════════════════════════════════════════
    # CHEMINS
    # ══════════════════════════════════════════════════════════════════
    COURSES_DIR    = os.getenv("COURSES_DIR", "courses")
    LOGS_DIR       = os.getenv("LOGS_DIR", "logs")
    CSV_LOG_FILE   = os.getenv("CSV_LOG_FILE", "logs/metrics.csv")
    STT_LOG_FILE   = os.getenv("STT_LOG_FILE", "logs/stt_metrics.csv")

    # ══════════════════════════════════════════════════════════════════
    # SERVEUR
    # ══════════════════════════════════════════════════════════════════
    SERVER_HOST    = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT    = int(os.getenv("SERVER_PORT", "8000"))

    # ══════════════════════════════════════════════════════════════════
    # KPIs (objectifs du projet)
    # ══════════════════════════════════════════════════════════════════
    MAX_RESPONSE_TIME         = 5.0   # Secondes (tour complet)
    MAX_INTERRUPTION_LATENCY  = 0.5   # Secondes (détection interruption)
    TARGET_WER_FR             = 0.10  # WER cible français
    TARGET_WER_AR             = 0.20  # WER cible arabe
    TARGET_WER_EN             = 0.10  # WER cible anglais
    TARGET_RTF                = 0.50  # Real-Time Factor cible

    # ══════════════════════════════════════════════════════════════════
    # DEBUG
    # ══════════════════════════════════════════════════════════════════
    ENABLE_CSV_LOGGING     = True
    ENABLE_CONSOLE_LOGGING = True

    # ══════════════════════════════════════════════════════════════════
    # VALIDATION
    # ══════════════════════════════════════════════════════════════════
    @classmethod
    def validate(cls):
        """Vérifie que les clés API essentielles sont présentes."""
        errors = []
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY manquante dans .env")

        # ElevenLabs optionnel si on utilise Edge-TTS
        if cls.TTS_PROVIDER == "elevenlabs" and not cls.ELEVENLABS_API_KEY:
            errors.append("ELEVENLABS_API_KEY manquante (requis si TTS_PROVIDER=elevenlabs)")

        if errors:
            print("\n" + "=" * 60)
            print("❌ ERREURS DE CONFIGURATION")
            print("=" * 60)
            for err in errors:
                print(f"   • {err}")
            print("\n💡 Créez un fichier .env :")
            print("   OPENAI_API_KEY=sk-...")
            print("   ELEVENLABS_API_KEY=... (optionnel)")
            print("=" * 60 + "\n")
            sys.exit(1)

        print("✅ Configuration validée")

    @classmethod
    def print_info(cls):
        """Affiche la configuration active (pour debug)."""
        print("\n" + "=" * 60)
        print("⚙️  SMART TEACHER — CONFIGURATION")
        print("=" * 60)
        print(f"\n🎙️  AUDIO:  {cls.SAMPLE_RATE}Hz | chunk={cls.CHUNK_SIZE} | silence={cls.SILENCE_DURATION}s")
        print(f"🧠 STT:    Whisper {cls.WHISPER_MODEL_SIZE} | {cls.WHISPER_DEVICE} | {cls.WHISPER_COMPUTE}")
        print(f"💬 LLM:    {cls.GPT_MODEL} | max_tokens={cls.GPT_MAX_TOKENS} | history={cls.MAX_HISTORY_TURNS}")
        print(f"🔊 TTS:    {cls.TTS_PROVIDER}")
        print(f"📚 RAG:    {cls.RAG_DB_DIR} | top-k={cls.RAG_NUM_RESULTS}")
        print(f"🌐 Server: {cls.SERVER_HOST}:{cls.SERVER_PORT}")
        print(f"\n🎯 KPIs:   réponse<{cls.MAX_RESPONSE_TIME}s | RTF<{cls.TARGET_RTF}")
        print("=" * 60 + "\n")
