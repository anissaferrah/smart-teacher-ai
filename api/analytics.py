from __future__ import annotations

from fastapi import APIRouter

from services.app_state import analytics_service

router = APIRouter(tags=["analytics"])


@router.get("/analytics/report")
async def get_analytics_report() -> dict:
    return analytics_service.full_report()


@router.get("/analytics/kpi")
async def get_kpi_summary(hours: int = 24) -> dict:
    return analytics_service.kpi_summary(hours=hours)


@router.get("/analytics/progression/{course_id}")
async def get_course_progression(course_id: str) -> dict:
    return {
        "course_id": course_id,
        "progression": analytics_service.progression_by_course(course_id),
    }


@router.get("/analytics/latency")
async def get_latency_distribution() -> dict:
    return analytics_service.latency_distribution()
