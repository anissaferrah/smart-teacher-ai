from __future__ import annotations

import json
import logging
from pathlib import Path

from modules.data.media_storage import LOCAL_MEDIA_DIR
from services.app_state import media_service

log = logging.getLogger("SmartTeacher.MediaService")


async def store_media_bytes(object_name: str, data: bytes, content_type: str) -> None:
    try:
        await __import__("asyncio").to_thread(media_service.upload_bytes, data, object_name, content_type)
    except Exception as exc:
        log.debug("media save skipped (%s): %s", object_name, exc)


async def store_media_json(object_name: str, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    await store_media_bytes(object_name, data, "application/json")


async def read_local_media_file(path: str) -> Path:
    return LOCAL_MEDIA_DIR / path
