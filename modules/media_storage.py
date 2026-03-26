"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Stockage Média (MinIO / Local fallback)     ║
║                                                                      ║
║  Gère le stockage des fichiers multimédia :                         ║
║    - PDF uploadés par les professeurs                               ║
║    - Slides extraites (images PNG)                                  ║
║    - Fichiers audio TTS générés                                     ║
║    - Ressources diverses                                            ║
║                                                                      ║
║  Si MinIO n'est pas configuré → stockage local dans ./media/        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import logging
import hashlib
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("SmartTeacher.MediaStorage")

# ── Configuration ──────────────────────────────────────────────────────
MINIO_ENDPOINT  = os.getenv("MINIO_ENDPOINT",  "")          # ex: localhost:9000
MINIO_ACCESS    = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET    = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET    = os.getenv("MINIO_BUCKET",    "smart-teacher")
MINIO_SECURE    = os.getenv("MINIO_SECURE",    "false").lower() == "true"
LOCAL_MEDIA_DIR = Path(os.getenv("LOCAL_MEDIA_DIR", "./media"))


class MediaStorage:
    """
    Interface unifiée pour MinIO ou stockage local.
    Détecte automatiquement si MinIO est disponible.
    """

    def __init__(self):
        self._minio   = None
        self._use_minio = False
        self._init_storage()

    def _init_storage(self):
        """Initialise MinIO si configuré, sinon stockage local."""
        LOCAL_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        (LOCAL_MEDIA_DIR / "slides").mkdir(exist_ok=True)
        (LOCAL_MEDIA_DIR / "pdfs").mkdir(exist_ok=True)
        (LOCAL_MEDIA_DIR / "audio").mkdir(exist_ok=True)

        if not MINIO_ENDPOINT:
            log.info("📁 Stockage local actif : %s", LOCAL_MEDIA_DIR)
            return

        try:
            from minio import Minio
            from minio.error import S3Error

            self._minio = Minio(
                MINIO_ENDPOINT,
                access_key=MINIO_ACCESS,
                secret_key=MINIO_SECRET,
                secure=MINIO_SECURE,
            )
            # Créer le bucket si inexistant
            if not self._minio.bucket_exists(MINIO_BUCKET):
                self._minio.make_bucket(MINIO_BUCKET)
                log.info("🪣 Bucket MinIO créé : %s", MINIO_BUCKET)
            else:
                log.info("✅ MinIO connecté : %s/%s", MINIO_ENDPOINT, MINIO_BUCKET)

            self._use_minio = True

        except ImportError:
            log.warning("⚠️  minio package non installé → stockage local")
        except Exception as e:
            log.warning("⚠️  MinIO non disponible (%s) → stockage local", e)

    # ── Upload ───────────────────────────────────────────────────────────

    def upload_bytes(self, data: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
        """
        Sauvegarde des bytes.
        Retourne l'URL publique (MinIO) ou le chemin local.
        """
        if self._use_minio:
            return self._minio_upload_bytes(data, object_name, content_type)
        return self._local_save_bytes(data, object_name)

    def upload_file(self, file_path: str, object_name: str) -> str:
        """Sauvegarde un fichier depuis le disque."""
        if self._use_minio:
            return self._minio_upload_file(file_path, object_name)
        return self._local_copy_file(file_path, object_name)

    # ── Download ─────────────────────────────────────────────────────────

    def get_url(self, object_name: str, expires_hours: int = 24) -> str:
        """Retourne une URL signée (MinIO) ou chemin local."""
        if self._use_minio:
            try:
                from datetime import timedelta
                return self._minio.presigned_get_object(
                    MINIO_BUCKET, object_name,
                    expires=timedelta(hours=expires_hours)
                )
            except Exception as e:
                log.error("MinIO get_url error: %s", e)
                return ""
        # Local : URL relative
        return f"/media/{object_name}"

    def get_bytes(self, object_name: str) -> Optional[bytes]:
        """Télécharge un objet et retourne ses bytes."""
        if self._use_minio:
            try:
                response = self._minio.get_object(MINIO_BUCKET, object_name)
                data = response.read()
                response.close()
                return data
            except Exception as e:
                log.error("MinIO get_bytes error: %s", e)
                return None
        path = LOCAL_MEDIA_DIR / object_name
        return path.read_bytes() if path.exists() else None

    def exists(self, object_name: str) -> bool:
        if self._use_minio:
            try:
                self._minio.stat_object(MINIO_BUCKET, object_name)
                return True
            except Exception:
                return False
        return (LOCAL_MEDIA_DIR / object_name).exists()

    def delete(self, object_name: str) -> bool:
        if self._use_minio:
            try:
                self._minio.remove_object(MINIO_BUCKET, object_name)
                return True
            except Exception:
                return False
        path = LOCAL_MEDIA_DIR / object_name
        if path.exists():
            path.unlink()
            return True
        return False

    def list_objects(self, prefix: str = "") -> list[str]:
        if self._use_minio:
            try:
                objects = self._minio.list_objects(MINIO_BUCKET, prefix=prefix, recursive=True)
                return [o.object_name for o in objects]
            except Exception:
                return []
        base = LOCAL_MEDIA_DIR / prefix if prefix else LOCAL_MEDIA_DIR
        if not base.exists():
            return []
        return [str(p.relative_to(LOCAL_MEDIA_DIR)) for p in base.rglob("*") if p.is_file()]

    # ── MinIO internals ──────────────────────────────────────────────────

    def _minio_upload_bytes(self, data: bytes, object_name: str, content_type: str) -> str:
        import io
        try:
            self._minio.put_object(
                MINIO_BUCKET, object_name,
                io.BytesIO(data), len(data),
                content_type=content_type,
            )
            return self.get_url(object_name)
        except Exception as e:
            log.error("MinIO upload_bytes error: %s", e)
            return self._local_save_bytes(data, object_name)

    def _minio_upload_file(self, file_path: str, object_name: str) -> str:
        try:
            self._minio.fput_object(MINIO_BUCKET, object_name, file_path)
            return self.get_url(object_name)
        except Exception as e:
            log.error("MinIO upload_file error: %s", e)
            return self._local_copy_file(file_path, object_name)

    # ── Local internals ──────────────────────────────────────────────────

    def _local_save_bytes(self, data: bytes, object_name: str) -> str:
        path = LOCAL_MEDIA_DIR / object_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"/media/{object_name}"

    def _local_copy_file(self, file_path: str, object_name: str) -> str:
        import shutil
        dest = LOCAL_MEDIA_DIR / object_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)
        return f"/media/{object_name}"

    # ── Helpers métier ───────────────────────────────────────────────────

    def save_course_pdf(self, course_id: str, filename: str, data: bytes) -> str:
        """Sauvegarde le PDF d'un cours."""
        obj = f"pdfs/{course_id}/{filename}"
        return self.upload_bytes(data, obj, "application/pdf")

    def save_audio(self, session_id: str, data: bytes, mime: str = "audio/mpeg") -> str:
        """Sauvegarde un fichier audio TTS."""
        ts  = int(time.time())
        ext = "mp3" if "mpeg" in mime else "webm"
        obj = f"audio/{session_id}/{ts}.{ext}"
        return self.upload_bytes(data, obj, mime)

    def save_slide_image(self, course_id: str, slide_idx: int, data: bytes) -> str:
        """Sauvegarde une image de slide."""
        obj = f"slides/{course_id}/slide_{slide_idx:04d}.png"
        return self.upload_bytes(data, obj, "image/png")


# Singleton
_storage: Optional[MediaStorage] = None

def get_storage() -> MediaStorage:
    global _storage
    if _storage is None:
        _storage = MediaStorage()
    return _storage
