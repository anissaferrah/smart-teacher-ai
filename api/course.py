from __future__ import annotations

import logging
import tempfile
import uuid
import asyncio
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from database.core import AsyncSessionLocal
from domains_config import auto_detect_course
from modules.pedagogy.course_builder import CourseBuilder
from services.app_state import (
    agentic_document_manager,
    ingestion_service,
    knowledge_retrieval_engine,
    media_service,
)

log = logging.getLogger("SmartTeacher.CourseAPI")

router = APIRouter(tags=["course"])


# ========================================
# UTIL
# ========================================
def _media_upload_object_name(domain: str, course: str, chapter: str, filename: str) -> str:
    safe_filename = Path(filename).name
    return f"uploads/{domain}/{course}/{chapter}/{safe_filename}"


# ========================================
# INGEST SIMPLE FILES
# ========================================
@router.post("/ingest")
async def ingest_course_files(
    files: list[UploadFile] = File(...),
    incremental: bool = Form(True),
    course_id: str | None = Form(None),
):
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    upload_dir = Path("courses")
    upload_dir.mkdir(exist_ok=True)

    saved_paths: list[str] = []

    for file in files:
        dest = upload_dir / Path(file.filename).name
        dest.write_bytes(await file.read())
        saved_paths.append(str(dest.resolve()))

    log.info(f"📤 Ingestion lancée ({len(saved_paths)} fichiers)")

    if course_id:
        log.info(f"📚 course_id={course_id}")

    asyncio.create_task(
        _run_course_ingestion_background(
            saved_paths,
            incremental=incremental,
            domain="general",
            course="uploaded",
            course_id=course_id,
        )
    )

    return {
        "status": "ingestion_started",
        "files": [f.filename for f in files],
        "message": "Ingestion en arrière-plan",
    }


# ========================================
# BACKGROUND INGESTION
# ========================================
async def _run_course_ingestion_background(
    file_paths: list[str],
    incremental: bool = False,
    domain: str = "general",
    course: str = "uploaded",
    course_id: str | None = None,
):
    try:
        await ingestion_service.start_ingestion(len(file_paths))

        loop = asyncio.get_running_loop()

        ok = await loop.run_in_executor(
            None,
            lambda: agentic_document_manager.index_course_files(
                file_paths,
                domain=domain,
                course=course,
                course_id=course_id,
                incremental=incremental,
            ),
        )

        if ok:
            stats = knowledge_retrieval_engine.get_stats()
            await ingestion_service.complete_ingestion(stats.get("total_docs", 0))
        else:
            await ingestion_service.fail_ingestion("index_course_files returned False")

    except Exception as e:
        log.error(f"Ingestion error: {e}", exc_info=True)
        await ingestion_service.fail_ingestion(str(e))


# ========================================
# STATUS
# ========================================
@router.get("/ingestion/status")
async def get_ingestion_status():
    return await ingestion_service.get_status()


# ========================================
# BUILD COURSE FROM UPLOAD
# ========================================
@router.post("/course/build")
async def build_course_from_upload(
    files: list[UploadFile] = File(...),
    language: str = Form("fr"),
    level: str = Form("lycée"),
    domain: str = Form("general"),
):
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    builder = CourseBuilder()
    total = len(files)

    await ingestion_service.start_ingestion(total, current_step="Initialisation...")

    results = []
    files_to_index = []

    for i, file in enumerate(files, start=1):
        filename = Path(file.filename or "upload.pdf").name
        content = await file.read()

        temp_path = None

        file_start = int(((i - 1) / total) * 90)
        file_end = int((i / total) * 90)

        # ========================================
        # STEP 1 - READ
        # ========================================
        await ingestion_service.update_progress(
            processed_files=i - 1,
            chunks_count=0,
            progress_percent=file_start + 2,
            current_step=f"[{i}/{total}] Lecture {filename}",
            stage="read_file",
        )

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
                tmp.write(content)
                temp_path = Path(tmp.name)

            # ========================================
            # STEP 2 - EXTRACT
            # ========================================
            extracted_text = ""
            extracted_title = filename

            try:
                extracted_text = builder.extractor.extract(str(temp_path))
                extracted_title = builder._infer_course_title(extracted_text, "", filename)
            except Exception:
                extracted_title = filename

            await ingestion_service.update_progress(
                processed_files=i - 1,
                chunks_count=0,
                progress_percent=file_start + 10,
                current_step=f"[{i}/{total}] Analyse {filename}",
                stage="extract",
            )

            # ========================================
            # AUTO DETECT
            # ========================================
            detected_domain, detected_course = auto_detect_course(str(temp_path))
            target_domain = detected_domain if detected_domain != "general" else domain
            target_course = builder._course_slug(extracted_title, fallback=filename, domain=target_domain)
            target_chapter = "chapter_1"

            # ========================================
            # SAVE LOCAL
            # ========================================
            target_dir = Path("courses") / target_domain / target_course / target_chapter
            target_dir.mkdir(parents=True, exist_ok=True)

            saved_path = target_dir / filename
            saved_path.write_bytes(content)

            await ingestion_service.update_progress(
                processed_files=i - 1,
                chunks_count=0,
                progress_percent=file_start + 20,
                current_step=f"[{i}/{total}] Sauvegarde",
                stage="save",
            )

            # ========================================
            # BUILD COURSE
            # ========================================
            course_data = await builder.build_from_file_direct(
                str(saved_path),
                language=language,
                level=level,
                domain=target_domain,
                subject=target_course,
                chapter=target_chapter,
                course_title_hint=extracted_title,
            )

            # ========================================
            # DB SAVE
            # ========================================
            course_id = None

            async with AsyncSessionLocal() as db:
                course_id = await builder.save_to_database(course_data, db, domain=target_domain)

            # ========================================
            # INDEX LIST
            # ========================================
            files_to_index.append(
                {
                    "course_data": course_data,
                    "course_id": course_id,
                    "domain": target_domain,
                    "course": target_course,
                }
            )

            results.append(
                {
                    "file": filename,
                    "course_id": course_id,
                    "title": course_data.get("title"),
                    "status": "ok",
                }
            )

            await ingestion_service.update_progress(
                processed_files=i,
                chunks_count=0,
                progress_percent=file_end,
                current_step=f"[{i}/{total}] Terminé {filename}",
                stage="done",
            )

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log.error(f"File error {filename}: {e}\n{tb}", exc_info=True)

            results.append(
                {
                    "file": filename,
                    "status": "error",
                    "error": str(e),
                    "traceback": tb,
                }
            )

        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()

    # ========================================
    # RAG INDEXING
    # ========================================
    if files_to_index:
        await ingestion_service.update_progress(
            processed_files=len(files_to_index),
            chunks_count=0,
            progress_percent=95,
            current_step="Indexation RAG",
            stage="rag",
        )

        for item in files_to_index:
            try:
                agentic_document_manager.index_course_data(
                    item["course_data"],
                    domain=item["domain"],
                    course=item["course"],
                    course_id=item["course_id"],
                    incremental=True,
                )
            except Exception as e:
                log.error(f"Index error: {e}")

        stats = knowledge_retrieval_engine.get_stats()
        await ingestion_service.complete_ingestion(stats.get("total_docs", 0))

    else:
        await ingestion_service.fail_ingestion("No file processed")

    return {
        "results": results,
        "rag_stats": knowledge_retrieval_engine.get_stats(),
    }


# ========================================
# COURSE LIST
# ========================================
@router.get("/course/list")
async def list_courses():
    from database.repositories.crud import get_all_courses

    async with AsyncSessionLocal() as db:
        courses = await get_all_courses(db)

        return {
            "courses": [
                {
                    "id": str(c.id),
                    "title": c.title,
                    "domain": c.domain,
                    "subject": c.subject,
                }
                for c in courses
            ]
        }


# ========================================
# COURSE STRUCTURE
# ========================================
@router.get("/course/{course_id}/structure")
async def get_course_structure(course_id: str):
    from database.repositories.crud import get_course_with_structure

    async with AsyncSessionLocal() as db:
        course = await get_course_with_structure(db, uuid.UUID(course_id))

        if not course:
            raise HTTPException(status_code=404, detail="Course not found")

        return {
            "course": {
                "id": str(course.id),
                "title": course.title,
                "domain": course.domain,
            },
            "chapters": course.chapters,
        }