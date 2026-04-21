from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from modules.pedagogy.student_profile import StudentProfile
from services.app_state import student_profile_manager

router = APIRouter(tags=["profile"])


@router.get("/profile/{student_id}")
async def get_student_learning_profile(student_id: str) -> dict:
    profile = await student_profile_manager.get_or_create(student_id)
    return asdict(profile)


@router.post("/profile/{student_id}/reset")
async def reset_student_learning_profile(student_id: str) -> dict:
    profile = StudentProfile(student_id=student_id)
    await student_profile_manager.save(profile)
    return {"status": "reset", "student_id": student_id}
