"""Session utilities and common helpers for WebSocket and REST handlers."""

import io
import logging
import tempfile
import os
from pathlib import Path
from collections import deque

import numpy as np
import soundfile as sf
from langdetect import detect

from config import Config

log = logging.getLogger("SmartTeacher.SessionManager")


def detect_lang_text(text: str) -> str:
    """Detect language from text."""
    try:
        code = detect(text)
        if code.startswith("fr"):
            return "fr"
        if code.startswith("ar"):
            return "ar"
        if code.startswith("tr"):
            return "tr"
        return "en"
    except Exception:
        return "en"


def audio_bytes_to_numpy(audio_bytes: bytes) -> np.ndarray:
    """Convert audio bytes (WebM) to numpy float32 array."""
    log.info(f"🔊 audio_bytes_to_numpy START: {len(audio_bytes)} bytes")
    
    # DIAGNOSTIC: Hex dump of first 64 bytes
    hex_header = " ".join(f"{b:02x}" for b in audio_bytes[:64])
    log.info(f"   Bytes header (hex): {hex_header}")
    
    # Check for different file signatures
    signatures = {
        "MP3": b"ID3" in audio_bytes[:12] or b"FF" in audio_bytes[:12].hex().encode(),
        "WebM": audio_bytes[:4] == b"\x1a\x45\xdf\xa3",
        "WAV": audio_bytes[:4] == b"RIFF",
        "OGG": audio_bytes[:4] == b"OggS",
        "FLAC": audio_bytes[:4] == b"fLaC",
        "UNKNOWN": True
    }
    detected = [fmt for fmt, found in signatures.items() if found and fmt != "UNKNOWN"]
    log.info(f"   Format detection: {', '.join(detected) if detected else 'UNKNOWN'}")
    
    try:
        log.debug("Trying soundfile...")
        data, sr = sf.read(io.BytesIO(audio_bytes))
        log.info(f"   ✅ Soundfile OK: sr={sr} shape={data.shape}")
        
        if len(data.shape) > 1:
            data = data.mean(axis=1)
        if sr != Config.SAMPLE_RATE:
            import librosa
            data = librosa.resample(data, orig_sr=sr, target_sr=Config.SAMPLE_RATE)
            log.info(f"   Resampled to {Config.SAMPLE_RATE}")
        
        result = data.astype(np.float32)
        rms = np.sqrt(np.mean(result ** 2))
        log.info(f"   Soundfile result: {len(result)} samples, RMS={rms:.6f}, range=[{result.min():.6f}, {result.max():.6f}]")
        log.debug(f"   First 20 samples: {result[:20].tolist()}")
        return result
    except Exception as e:
        log.warning(f"Soundfile failed: {e}, trying pydub...")
    
    try:
        log.debug("Trying pydub + ffmpeg...")
        from pydub import AudioSegment
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(audio_bytes)
            path = tmp.name
        
        # Detailed WebM analysis
        if len(audio_bytes) > 4:
            magic = audio_bytes[:4]
            is_webm = (magic[0] == 0x1A and magic[1] == 0x45 and magic[2] == 0xDF and magic[3] == 0xA3)
            log.info(f"   WebM magic bytes: {magic.hex()}, is_valid_webm={is_webm}")
            
            # Check for multiple EBML headers (sign of concatenated chunks)
            ebml_count = audio_bytes.count(b"\x1a\x45\xdf\xa3")
            if ebml_count > 1:
                log.warning(f"   ⚠️  CRITICAL: Found {ebml_count} EBML headers in WebM (expected 1)")
                pos = 0
                for i in range(ebml_count):
                    pos = audio_bytes.find(b"\x1a\x45\xdf\xa3", pos)
                    log.warning(f"      EBML header #{i+1} at byte offset {pos}")
                    pos += 4
        
        try:
            seg = AudioSegment.from_file(path, format="webm")
            log.info(f"   Loaded WebM: {len(seg.raw_data)} bytes, channels={seg.channels}, sr={seg.frame_rate}")
            
            seg = seg.set_frame_rate(Config.SAMPLE_RATE)
            seg = seg.set_channels(1)
            seg = seg.set_sample_width(2)
            
            samples = np.array(seg.get_array_of_samples(), dtype=np.int16)
            result = (samples / 32768.0).astype(np.float32)
            
            rms = np.sqrt(np.mean(result ** 2))
            log.info(f"   ✅ Pydub OK: {len(result)} samples, RMS={rms:.6f}")
            log.debug(f"   First 20 samples: {result[:20].tolist()}")
            
            if rms < 0.0001:
                log.warning(f"⚠️  Audio decoded but ZERO RMS (all silence)")
            
            return result
        finally:
            os.unlink(path)
    except Exception as exc:
        log.error(f"❌ Pydub/ffmpeg failed: {exc}, trying librosa...")
    
    # Last resort: librosa
    try:
        log.debug("Trying librosa...")
        import librosa
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(audio_bytes)
            path = tmp.name
        try:
            data, sr = librosa.load(path, sr=Config.SAMPLE_RATE, mono=True)
            result = data.astype(np.float32)
            
            rms = np.sqrt(np.mean(result ** 2))
            log.info(f"   ✅ Librosa OK: {len(result)} samples, RMS={rms:.6f}")
            
            return result
        finally:
            os.unlink(path)
    except Exception as exc:
        log.error(f"❌ All converters failed: {exc}")
        raise RuntimeError(f"Audio conversion failed: {exc}")


_SUBJECT_KW = {
    "math":      ["math","équation","algèbre","calcul","dérivée","intégrale"],
    "biology":   ["bio","cell","cellule","adn","évolution"],
    "physics":   ["physique","force","énergie","vitesse"],
    "chemistry": ["chimie","molécule","atome","réaction"],
    "history":   ["histoire","guerre","révolution"],
    "geography": ["géographie","pays","continent"],
    "cs":        ["algorithme","code","programmation","python"],
    "economics": ["économie","marché","finance"],
}


def detect_subject(text: str) -> str | None:
    """Detect subject matter from text."""
    t = text.lower()
    for subj, kws in _SUBJECT_KW.items():
        if any(kw in t for kw in kws):
            return subj
    return None


def get_http_session(request) -> tuple[str, list]:
    """Get or create HTTP session from request headers."""
    from fastapi import Request
    import uuid
    from handlers import HTTP_SESSIONS
    
    sid = request.headers.get("X-Session-ID") or str(uuid.uuid4())
    if sid not in HTTP_SESSIONS:
        HTTP_SESSIONS[sid] = deque(maxlen=Config.MAX_HISTORY_TURNS * 2)
    return sid, list(HTTP_SESSIONS[sid])


# Global session storage
HTTP_SESSIONS: dict[str, deque] = {}
SESSION_TOKENS: dict[str, str] = {}
