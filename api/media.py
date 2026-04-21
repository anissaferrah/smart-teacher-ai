from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from modules.data.media_storage import LOCAL_MEDIA_DIR
from services.app_state import media_service

router = APIRouter(tags=["media"])


@router.get("/media/{path:path}")
async def serve_media_file(path: str):
    file_path = LOCAL_MEDIA_DIR / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    return FileResponse(str(file_path))


@router.get("/media-list")
async def list_media_objects(prefix: str = "") -> dict:
    objects = media_service.list_objects(prefix)
    return {"count": len(objects), "objects": objects[:100]}
