from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from database.core import AsyncSessionLocal
from domains_config import auto_detect_course
from modules.pedagogy.course_builder import CourseBuilder
from services.app_state import agentic_document_manager, ingestion_service, knowledge_retrieval_engine, media_service

log = logging.getLogger("SmartTeacher.CourseAPI")

router = APIRouter(tags=["course"])


def _media_upload_object_name(domain: str, course: str, chapter: str, filename: str) -> str:
    safe_filename = Path(filename).name
    return f"uploads/{domain}/{course}/{chapter}/{safe_filename}"


@router.post("/ingest")
async def ingest_course_files(files: list[UploadFile] = File(...), incremental: bool = Form(True), course_id: str | None = Form(None)):
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    upload_dir = Path("courses")
    upload_dir.mkdir(exist_ok=True)
    saved_paths: list[str] = []

    for uploaded_file in files:
        destination = upload_dir / Path(uploaded_file.filename).name
        destination.write_bytes(await uploaded_file.read())
        saved_paths.append(str(destination.resolve()))

    __import__("logging").getLogger("SmartTeacher.CourseAPI").info(f"📤 Ingestion lancée ({len(saved_paths)} fichier(s))")
    if course_id:
        __import__("logging").getLogger("SmartTeacher.CourseAPI").info(f"   📚 course_id={course_id}")

    __import__("asyncio").create_task(
        _run_course_ingestion_background(saved_paths, incremental=incremental, domain="general", course="uploaded", course_id=course_id)
    )

    return {
        "status": "ingestion_started",
        "files": [f.filename for f in files],
        "message": "Ingestion lancée en arrière-plan. Consultez /ingestion/status pour suivre la progression.",
    }


async def _run_course_ingestion_background(file_paths: list[str], incremental: bool = False, domain: str = "general", course: str = "uploaded", course_id: str | None = None) -> None:
    try:
        await ingestion_service.start_ingestion(len(file_paths))
        loop = __import__("asyncio").get_event_loop()
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
            total_chunks = stats.get("total_docs", 0)
            await ingestion_service.complete_ingestion(total_chunks)
        else:
            await ingestion_service.fail_ingestion("run_ingestion_pipeline_for_files returned False")
    except Exception as exc:
        await ingestion_service.fail_ingestion(str(exc))


@router.get("/ingestion/status")
async def get_ingestion_status() -> dict:
    return await ingestion_service.get_status()


@router.post("/course/build")
async def build_course_from_upload(files: list[UploadFile] = File(...), language: str = Form("fr"), level: str = Form("lycée"), domain: str = Form("general")):
    builder = CourseBuilder()
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    total_files = len(files)
    await ingestion_service.start_ingestion(total_files, current_step="Préparation de l'import…")

    results = []

    files_to_index: list[dict] = []

    for index, uploaded_file in enumerate(files, start=1):
        raw_upload_name = (uploaded_file.filename or "upload.pdf").replace("\\", "/")
        upload_filename = Path(raw_upload_name).name or f"upload_{uuid.uuid4().hex[:8]}.pdf"
        payload = await uploaded_file.read()
        temp_path: Path | None = None

        file_start = int(((index - 1) / max(total_files, 1)) * 90)
        file_end = int((index / max(total_files, 1)) * 90)

        await ingestion_service.update_progress(
            processed_files=index - 1,
            chunks_count=0,
            progress_percent=max(1, file_start + 2),
            current_step=f"[{index}/{total_files}] Lecture du fichier {upload_filename}",
            stage="read_file",
        )

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(upload_filename).suffix or ".pdf") as tmp:
                tmp.write(payload)
                temp_path = Path(tmp.name)

            await ingestion_service.update_progress(
                processed_files=index - 1,
                chunks_count=0,
                progress_percent=max(file_start + 6, file_start + 2),
                current_step=f"[{index}/{total_files}] Analyse du contenu ({upload_filename})",
                stage="extract_content",
            )

            detected_domain, detected_course = auto_detect_course(str(temp_path))
            target_domain = detected_domain if detected_domain != "general" else domain
            fallback_course = detected_course if detected_course != "generic" else None
            chapter_hint = None

            extracted_title = ""
            extracted_text = ""
            try:
                extracted_text = builder.extractor.extract(str(temp_path))
                extracted_title = builder._infer_course_title(extracted_text, detected_course, Path(upload_filename).stem)
            except Exception:
                extracted_title = Path(upload_filename).stem

            for candidate in (upload_filename, extracted_title, extracted_text):
                if not candidate:
                    continue
                lines = [candidate] if "\n" not in candidate else candidate.splitlines()[:5]
                for line in lines:
                    number = builder._chapter_number_from_value(line)
                    if number:
                        chapter_hint = f"chapter_{number}"
                        break
                if chapter_hint:
                    break

            if not fallback_course or fallback_course in {"generic", "general"}:
                fallback_course = builder._course_slug(extracted_title, fallback=detected_course or upload_filename, domain=target_domain)

            if fallback_course is None and upload_filename:
                stem_hint = Path(upload_filename).stem
                if not builder._looks_like_chapter(stem_hint):
                    fallback_course = stem_hint

            target_domain, target_course, target_chapter = builder.infer_upload_context(
                raw_upload_name,
                fallback_domain=target_domain,
                fallback_course=fallback_course,
                fallback_chapter=chapter_hint or "chapter_1",
            )

            target_dir = Path("courses") / target_domain / target_course / target_chapter
            target_dir.mkdir(parents=True, exist_ok=True)
            destination = target_dir / upload_filename
            destination.write_bytes(payload)

            await ingestion_service.update_progress(
                processed_files=index - 1,
                chunks_count=0,
                progress_percent=max(file_start + 18, file_start + 2),
                current_step=f"[{index}/{total_files}] Sauvegarde locale du cours",
                stage="save_local",
            )

            media_upload_path = ""
            try:
                media_upload_path = media_service.upload_bytes(
                    payload,
                    _media_upload_object_name(target_domain, target_course, target_chapter, upload_filename),
                    uploaded_file.content_type or "application/octet-stream",
                )
            except Exception as exc:
                __import__("logging").getLogger("SmartTeacher.CourseAPI").warning(
                    "media/uploads mirror failed for %s: %s",
                    destination,
                    exc,
                )

            await ingestion_service.update_progress(
                processed_files=index - 1,
                chunks_count=0,
                progress_percent=max(file_start + 32, file_start + 2),
                current_step=f"[{index}/{total_files}] Construction de la structure pédagogique",
                stage="build_structure",
            )

            course_data = await builder.build_from_file_direct(
                str(destination),
                language=language,
                level=level,
                domain=target_domain,
                subject=target_course,
                chapter=target_chapter,
                course_title_hint=extracted_title,
            )
            log.info(f"📄 build_from_file_direct result: title={course_data.get('title')}, chapters={len(course_data.get('chapters', []))}, sections={sum(len(ch.get('sections',[])) for ch in course_data.get('chapters',[]))}")

            course_id = None
            db_error = None
            await ingestion_service.update_progress(
                processed_files=index - 1,
                chunks_count=0,
                progress_percent=max(file_start + 48, file_start + 2),
                current_step=f"[{index}/{total_files}] Enregistrement base de données",
                stage="save_database",
            )
            try:
                async with AsyncSessionLocal() as db:
                    course_id = await builder.save_to_database(course_data, db, domain=target_domain)
            except Exception as exc:
                db_error = str(exc)
                log.error(f"❌ save_to_database a échoué pour {upload_filename}: {exc}", exc_info=True)

            files_to_index.append({
                "course_data": course_data,
                "course_id": course_id,
                "domain": target_domain,
                "course": target_course,
                "chapter": target_chapter,
                "storage_path": str(destination.resolve()),
                "media_upload_path": media_upload_path,
            })
            log.info(f"✅ fichier ajouté à files_to_index: {upload_filename}, sections={len(course_data.get('sections', []))}, chapters={len(course_data.get('chapters', []))}")

            if db_error:
                log.warning(f"⚠️ DB save partial pour {upload_filename}: {db_error}")

            chapters = len(course_data.get("chapters", []))
            sections = sum(len(ch.get("sections", [])) for ch in course_data.get("chapters", []))
            results.append({
                "file": upload_filename,
                "course_id": course_id,
                "title": course_data.get("title"),
                "chapters": chapters,
                "sections": sections,
                "domain": target_domain,
                "course": target_course,
                "chapter": target_chapter,
                "storage_path": str(destination),
                "media_upload_path": media_upload_path,
                "status": "ok" if db_error is None else "partial",
                "db_error": db_error,
            })

            await ingestion_service.update_progress(
                processed_files=index,
                chunks_count=0,
                progress_percent=max(file_end - 2, file_start + 2),
                current_step=f"[{index}/{total_files}] Fichier traité: {upload_filename}",
                stage="file_done",
            )
        except Exception as exc:
            log.error(f"❌ Erreur traitement fichier {upload_filename}: {exc}", exc_info=True)
            results.append({"file": uploaded_file.filename, "status": "error", "error": str(exc)})

            await ingestion_service.update_progress(
                processed_files=index,
                chunks_count=0,
                progress_percent=max(file_end - 2, file_start + 2),
                current_step=f"[{index}/{total_files}] Échec sur {upload_filename}",
                stage="file_error",
            )
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    if not files_to_index and results:
        # Tous les fichiers ont échoué — diagnostics
        errors = [r.get("error", "unknown") for r in results if r.get("status") == "error"]
        log.error(f"❌ Aucun fichier indexé. Erreurs: {errors}")

    if files_to_index:
        await ingestion_service.update_progress(
            processed_files=len(files_to_index),
            chunks_count=0,
            progress_percent=94,
            current_step="Indexation documentaire RAG…",
            stage="rag_indexing",
        )

        for item in files_to_index:
            course_data = item["course_data"]
            course_id = item["course_id"]
            target_domain = item["domain"]
            target_course = item["course"]
            try:
                ok = agentic_document_manager.index_course_data(
                    course_data,
                    domain=target_domain,
                    course=target_course,
                    course_id=course_id,
                    incremental=True,
                )
                if not ok:
                    log.warning(f"⚠️ index_course_data a retourné False pour course_id={course_id}")
            except Exception as exc:
                log.error(f"❌ index_course_data a levé: {exc}", exc_info=True)

        stats = knowledge_retrieval_engine.get_stats()
        await ingestion_service.complete_ingestion(int(stats.get("total_docs", 0)))
    else:
        await ingestion_service.fail_ingestion("Aucun fichier n'a pu être importé")

    return {"results": results, "rag_stats": knowledge_retrieval_engine.get_stats()}


@router.get("/course/list")
async def list_courses() -> dict:
    try:
        from database.core import AsyncSessionLocal
        from database.repositories.crud import get_all_courses
        async with AsyncSessionLocal() as db:
            courses = await get_all_courses(db)
            seen_keys: set[str] = set()
            payload_courses = []

            for course in courses:
                dedupe_key = (course.file_path or str(course.id)).strip()
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                chapters = list(course.chapters or [])
                chapter_count = len(chapters)
                section_count = sum(len(chapter.sections or []) for chapter in chapters)

                payload_courses.append({
                    "id": str(course.id),
                    "title": course.title,
                    "display_title": course.title or course.subject or "Cours importé",
                    "subject": course.subject,
                    "domain": course.domain,
                    "language": course.language,
                    "level": course.level,
                    "chapter_count": chapter_count,
                    "section_count": section_count,
                    "file_path": course.file_path,
                })

            return {"courses": payload_courses}
    except Exception as exc:
        return {"courses": [], "error": str(exc)}


@router.get("/course/{course_id}/structure")
async def get_course_structure(course_id: str) -> dict:
    try:
        from database.core import AsyncSessionLocal
        from database.repositories.crud import get_course_with_structure
        async with AsyncSessionLocal() as db:
            course = await get_course_with_structure(db, uuid.UUID(course_id))
            if not course:
                raise HTTPException(status_code=404, detail="Cours introuvable")

            slides = []
            chapters_data = []
            for chapter in course.chapters:
                sections_data = []
                for section in chapter.sections:
                    slide_path = section.image_url or (section.image_urls[0] if getattr(section, "image_urls", None) else "")
                    if slide_path:
                        slides.append(slide_path)
                    sections_data.append({
                        "id": str(section.id),
                        "title": section.title,
                        "order": section.order,
                        "content": section.content,
                        "image_url": slide_path,
                        "image_urls": section.image_urls or ([] if not slide_path else [slide_path]),
                        "duration_s": section.duration_s,
                        "concepts": [
                            {
                                "id": str(concept.id),
                                "term": concept.term,
                                "definition": concept.definition,
                                "example": concept.example,
                                "type": concept.concept_type,
                            }
                            for concept in section.concepts
                        ],
                    })
                chapters_data.append({
                    "id": str(chapter.id),
                    "title": chapter.title,
                    "order": chapter.order,
                    "summary": chapter.summary,
                    "sections": sections_data,
                })

            return {
                "course": {
                    "id": str(course.id),
                    "title": course.title,
                    "subject": course.subject,
                    "domain": course.domain,
                    "language": course.language,
                    "level": course.level,
                    "description": course.description,
                },
                "chapters": chapters_data,
                "slides": slides,
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
