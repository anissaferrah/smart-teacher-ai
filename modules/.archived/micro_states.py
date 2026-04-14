"""
🎯 EXHAUSTIVE Micro-States Definition System
============================================
Defines all 30+ micro-states across 5 phases for PERFECT real-time state visibility.
Each micro-state has metrics, display templates, and phase tracking.
"""

from enum import Enum
from typing import Dict, Any, List

class MicroStatePhase(str, Enum):
    """Major phases of AI teacher operation"""
    AUDIO = "audio"           # 🎙️  Audio input analysis
    RAG = "rag"              # 🔍 Information retrieval
    CONFUSION = "confusion"   # 🤔 Confusion detection
    LLM = "llm"              # 🧠 LLM generation
    TTS = "tts"              # 🎙️  Text-to-speech output


class MicroStateStatus(str, Enum):
    """Status of a micro-state"""
    IDLE = "idle"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ERROR = "error"
    SKIPPED = "skipped"


# ================================================
# PHASE 1: AUDIO ANALYSIS (🎙️ 4 states)
# ================================================

AUDIO_STATES = {
    "audio_received": {
        "phase": MicroStatePhase.AUDIO,
        "order": 1,
        "emoji": "🎙️",
        "label": "Analyse Audio",
        "metrics": ["duration_ms", "bytes", "sample_rate", "channels"],
        "progress_range": (5, 10),
        "display_template": "🎙️ Audio reçu: {bytes} bytes, {duration_ms}ms",
    },
    "vad_detection": {
        "phase": MicroStatePhase.AUDIO,
        "order": 2,
        "emoji": "📊",
        "label": "Détection Voix (VAD)",
        "metrics": ["silence_duration_ms", "silence_removed_pct", "voice_segments"],
        "progress_range": (10, 15),
        "display_template": "📊 VAD: {silence_removed_pct}% silence détecté, {voice_segments} segments",
    },
    "prosody_extraction": {
        "phase": MicroStatePhase.AUDIO,
        "order": 3,
        "emoji": "📈",
        "label": "Extraction Prosody",
        "metrics": ["speech_rate", "hesitations", "confidence", "duration_ms"],
        "progress_range": (15, 25),
        "display_template": "📈 Prosody: {speech_rate}wpm, {hesitations} hésitations, confidence={confidence}",
    },
    "audio_validation": {
        "phase": MicroStatePhase.AUDIO,
        "order": 4,
        "emoji": "✓",
        "label": "Validation Audio",
        "metrics": ["snr", "quality_score", "duration_ms"],
        "progress_range": (25, 30),
        "display_template": "✓ Audio OK: SNR={snr}dB, quality={quality_score}",
    },
}

# ================================================
# PHASE 2: RAG RETRIEVAL (🔍 4 states)
# ================================================

RAG_STATES = {
    "rag_bm25_search": {
        "phase": MicroStatePhase.RAG,
        "order": 1,
        "emoji": "🔍",
        "label": "Recherche BM25",
        "metrics": ["chunks_found", "avg_score", "duration_ms"],
        "progress_range": (30, 40),
        "display_template": "🔍 BM25: {chunks_found} chunks trouvés, score moyen={avg_score}",
    },
    "rag_ranking": {
        "phase": MicroStatePhase.RAG,
        "order": 2,
        "emoji": "📊",
        "label": "Classement Chunks",
        "metrics": ["ranked_chunks", "top_score", "bottom_score", "duration_ms"],
        "progress_range": (40, 45),
        "display_template": "📊 Ranking: top={top_score}, bottom={bottom_score}, {duration_ms}ms",
    },
    "rag_deduplication": {
        "phase": MicroStatePhase.RAG,
        "order": 3,
        "emoji": "🔗",
        "label": "Déduplication",
        "metrics": ["before_count", "after_count", "duplicates_removed", "duration_ms"],
        "progress_range": (45, 48),
        "display_template": "🔗 Dédup: {duplicates_removed} doublons supprimés ({before_count}→{after_count})",
    },
    "rag_formatting": {
        "phase": MicroStatePhase.RAG,
        "order": 4,
        "emoji": "📋",
        "label": "Formatage Contexte",
        "metrics": ["total_length", "chunk_count", "duration_ms"],
        "progress_range": (48, 50),
        "display_template": "📋 Contexte: {total_length} chars, {chunk_count} chunks",
    },
}

# ================================================
# PHASE 3: CONFUSION DETECTION (🤔 6 states)
# ================================================

CONFUSION_STATES = {
    "confusion_keywords": {
        "phase": MicroStatePhase.CONFUSION,
        "order": 1,
        "emoji": "🔑",
        "label": "Vérification Mots-clés",
        "metrics": ["keywords_checked", "keywords_matched", "confidence", "duration_ms"],
        "progress_range": (50, 55),
        "display_template": "🔑 Keywords: {keywords_matched}/{keywords_checked} matches, confidence={confidence}",
    },
    "confusion_hash": {
        "phase": MicroStatePhase.CONFUSION,
        "order": 2,
        "emoji": "🔢",
        "label": "Vérification Répétition",
        "metrics": ["hashes_compared", "exact_match", "similarity_threshold", "duration_ms"],
        "progress_range": (55, 58),
        "display_template": "🔢 Hash: {hashes_compared} comparés, match={exact_match}",
    },
    "confusion_patterns": {
        "phase": MicroStatePhase.CONFUSION,
        "order": 3,
        "emoji": "📐",
        "label": "Analyse Patterns",
        "metrics": ["questions_analyzed", "pattern_type", "pattern_count", "confidence", "duration_ms"],
        "progress_range": (58, 61),
        "display_template": "📐 Patterns: {questions_analyzed} Q analysées, type={pattern_type}, confidence={confidence}",
    },
    "confusion_semantic": {
        "phase": MicroStatePhase.CONFUSION,
        "order": 4,
        "emoji": "📚",
        "label": "Similarité Sémantique",
        "metrics": ["similarity_score", "threshold", "is_similar", "duration_ms"],
        "progress_range": (61, 64),
        "display_template": "📚 Sémantique: score={similarity_score}, seuil={threshold}, similar={is_similar}",
    },
    "confusion_prosody": {
        "phase": MicroStatePhase.CONFUSION,
        "order": 5,
        "emoji": "🎵",
        "label": "Analyse Prosody",
        "metrics": ["speech_rate_z_score", "hesitation_z_score", "overall_z_score", "is_anomaly", "duration_ms"],
        "progress_range": (64, 67),
        "display_template": "🎵 Prosody: z_scores=[{speech_rate_z_score}, {hesitation_z_score}], anomaly={is_anomaly}",
    },
    "confusion_adaptive_threshold": {
        "phase": MicroStatePhase.CONFUSION,
        "order": 6,
        "emoji": "⚠️",
        "label": "Seuil Adaptatif",
        "metrics": ["base_threshold", "multiplier", "adjusted_threshold", "is_confused", "duration_ms"],
        "progress_range": (67, 70),
        "display_template": "⚠️ Adaptive: multiplier={multiplier}, seuil={adjusted_threshold}, confused={is_confused}",
    },
}

# ================================================
# PHASE 4: LLM GENERATION (🧠 4 states)
# ================================================

LLM_STATES = {
    "llm_prompt_assembly": {
        "phase": MicroStatePhase.LLM,
        "order": 1,
        "emoji": "📝",
        "label": "Assemblage Prompt",
        "metrics": ["system_prompt_length", "context_length", "total_length", "duration_ms"],
        "progress_range": (70, 75),
        "display_template": "📝 Prompt: {total_length} chars (système={system_prompt_length}, contexte={context_length})",
    },
    "llm_streaming": {
        "phase": MicroStatePhase.LLM,
        "order": 2,
        "emoji": "🧠",
        "label": "Génération (Streaming)",
        "metrics": ["tokens_generated", "tokens_per_sec", "current_token", "duration_ms"],
        "progress_range": (75, 85),
        "display_template": "🧠 LLM: {tokens_generated} tokens, {tokens_per_sec} tok/s, {duration_ms}ms",
    },
    "llm_streaming_complete": {
        "phase": MicroStatePhase.LLM,
        "order": 3,
        "emoji": "✅",
        "label": "LLM Complété",
        "metrics": ["total_tokens", "total_length", "finish_reason", "duration_ms"],
        "progress_range": (85, 88),
        "display_template": "✅ LLM Done: {total_tokens} tokens, raison={finish_reason}",
    },
    "llm_fallback": {
        "phase": MicroStatePhase.LLM,
        "order": 4,
        "emoji": "🖥️",
        "label": "Fallback Ollama",
        "metrics": ["error_type", "model_name", "duration_ms"],
        "progress_range": (75, 88),
        "display_template": "🖥️ Fallback: {error_type}, model={model_name}",
    },
}

# ================================================
# PHASE 5: TTS GENERATION (🎙️ 4 states)
# ================================================

TTS_STATES = {
    "tts_text_chunking": {
        "phase": MicroStatePhase.TTS,
        "order": 1,
        "emoji": "✂️",
        "label": "Chunking Texte",
        "metrics": ["chunks_total", "avg_chunk_length", "duration_ms"],
        "progress_range": (88, 90),
        "display_template": "✂️ TTS Chunking: {chunks_total} chunks (avg={avg_chunk_length} chars)",
    },
    "tts_generation": {
        "phase": MicroStatePhase.TTS,
        "order": 2,
        "emoji": "🎵",
        "label": "Génération Audio",
        "metrics": ["audio_bytes", "duration_ms", "engine", "voice"],
        "progress_range": (90, 96),
        "display_template": "🎵 TTS Gen: {audio_bytes} bytes, {duration_ms}ms, {engine}/{voice}",
    },
    "tts_streaming": {
        "phase": MicroStatePhase.TTS,
        "order": 3,
        "emoji": "📤",
        "label": "Streaming Audio",
        "metrics": ["chunks_sent", "total_chunks", "bytes_sent", "duration_ms"],
        "progress_range": (96, 99),
        "display_template": "📤 TTS Stream: {chunks_sent}/{total_chunks} chunks, {bytes_sent} bytes",
    },
    "tts_completion": {
        "phase": MicroStatePhase.TTS,
        "order": 4,
        "emoji": "✅",
        "label": "TTS Complété",
        "metrics": ["total_duration_ms", "total_bytes"],
        "progress_range": (99, 100),
        "display_template": "✅ TTS OK: {total_duration_ms}ms, {total_bytes} bytes",
    },
}

# ================================================
# COMPLETE REGISTRY
# ================================================

ALL_MICRO_STATES: Dict[str, Dict[str, Any]] = {
    **AUDIO_STATES,
    **RAG_STATES,
    **CONFUSION_STATES,
    **LLM_STATES,
    **TTS_STATES,
}

# Map phase to states
STATES_BY_PHASE = {
    MicroStatePhase.AUDIO: AUDIO_STATES,
    MicroStatePhase.RAG: RAG_STATES,
    MicroStatePhase.CONFUSION: CONFUSION_STATES,
    MicroStatePhase.LLM: LLM_STATES,
    MicroStatePhase.TTS: TTS_STATES,
}

# ================================================
# UTILITY FUNCTIONS
# ================================================

def get_micro_state_definition(state_name: str) -> Dict[str, Any] | None:
    """Get definition of a micro-state by name"""
    return ALL_MICRO_STATES.get(state_name)

def get_phase_states(phase: MicroStatePhase) -> Dict[str, Dict[str, Any]]:
    """Get all states in a phase"""
    return STATES_BY_PHASE.get(phase, {})

def get_progress_range(state_name: str) -> tuple[int, int] | None:
    """Get progress percentage range for a state (min, max)"""
    state_def = get_micro_state_definition(state_name)
    if state_def:
        return state_def.get("progress_range", (0, 100))
    return None

def format_metrics(state_name: str, metrics: Dict[str, Any]) -> str:
    """Format metrics according to state template"""
    state_def = get_micro_state_definition(state_name)
    if not state_def:
        return ""
    
    template = state_def.get("display_template", "")
    try:
        return template.format(**metrics)
    except KeyError as e:
        # Missing metric in template
        return f"{state_def.get('emoji', '📊')} {state_def.get('label', state_name)}"

# Example usage:
"""
async def emit_micro_state(state_name: str, metrics: dict, send_state_func):
    '''Helper to emit a micro-state with proper formatting'''
    definition = get_micro_state_definition(state_name)
    if not definition:
        return
    
    display_text = format_metrics(state_name, metrics)
    progress_min, progress_max = get_progress_range(state_name)
    
    await send_state_func(
        DialogState.PROCESSING,
        state_name,
        {},
        {
            **metrics,
            "progress_pct": progress_min + (metrics.get("progress_pct", 0) % (progress_max - progress_min)),
            "display": display_text,
        }
    )
"""
