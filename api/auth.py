from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from database.core import AsyncSessionLocal
from database.models import Student
from database.repositories.crud import create_student
from modules.pedagogy.student_profile import StudentProfile
from services.app_state import student_profile_manager

router = APIRouter(tags=["auth"])

# In-memory auth tokens for local development.
AUTH_TOKENS: dict[str, str] = {}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    first_name: str = Field(default="Etudiant", min_length=1, max_length=100)
    last_name: str = Field(default="", max_length=100)
    preferred_language: str = Field(default="fr", min_length=2, max_length=5)
    level: str = Field(default="lycee", min_length=2, max_length=20)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UpdateLearningProfileRequest(BaseModel):
    name: Optional[str] = None
    language: Optional[str] = None
    level: Optional[str] = None


def _hash_password(password: str, *, salt: Optional[str] = None) -> str:
    salt_hex = salt or secrets.token_hex(16)
    iterations = 150000
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt_hex}${pwd_hash}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, expected = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        calculated = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        ).hex()
        return hmac.compare_digest(calculated, expected)
    except Exception:
        return False


def _student_payload(student: Student) -> dict:
    return {
        "id": str(student.id),
        "email": student.email,
        "first_name": student.first_name,
        "last_name": student.last_name or "",
        "preferred_language": student.preferred_language,
        "account_level": student.account_level,
        "is_active": bool(student.is_active),
    }


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


@router.post("/register")
async def register_account(payload: RegisterRequest) -> dict:
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(Student).where(Student.email == payload.email.lower().strip()))
        if existing:
            raise HTTPException(status_code=409, detail="Un compte existe deja avec cet email")

        student = await create_student(
            db,
            email=payload.email.lower().strip(),
            password_hash=_hash_password(payload.password),
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            preferred_language=payload.preferred_language.strip().lower(),
        )
        await db.commit()
        await db.refresh(student)

    learning_profile = await student_profile_manager.get_or_create(
        str(student.id),
        language=student.preferred_language,
        level=payload.level,
    )
    learning_profile.name = student.first_name or learning_profile.name
    await student_profile_manager.save(learning_profile)

    token = secrets.token_urlsafe(32)
    AUTH_TOKENS[token] = str(student.id)

    return {
        "token": token,
        "student": _student_payload(student),
        "learning_profile": asdict(learning_profile),
    }


@router.post("/login")
async def login_account(payload: LoginRequest) -> dict:
    async with AsyncSessionLocal() as db:
        student = await db.scalar(select(Student).where(Student.email == payload.email.lower().strip()))
        if not student or not student.password_hash or not _verify_password(payload.password, student.password_hash):
            raise HTTPException(status_code=401, detail="Email ou mot de passe invalide")
        if not student.is_active:
            raise HTTPException(status_code=403, detail="Compte desactive")

    profile = await student_profile_manager.get_or_create(
        str(student.id),
        language=student.preferred_language,
    )
    token = secrets.token_urlsafe(32)
    AUTH_TOKENS[token] = str(student.id)

    return {
        "token": token,
        "student": _student_payload(student),
        "learning_profile": asdict(profile),
    }


@router.get("/me")
async def get_my_account(authorization: Optional[str] = Header(default=None)) -> dict:
    token = _extract_bearer_token(authorization)
    if not token or token not in AUTH_TOKENS:
        raise HTTPException(status_code=401, detail="Token invalide ou manquant")

    student_id = AUTH_TOKENS[token]
    async with AsyncSessionLocal() as db:
        student = await db.scalar(select(Student).where(Student.id == student_id))
        if not student:
            raise HTTPException(status_code=404, detail="Compte introuvable")

    profile = await student_profile_manager.get_or_create(
        str(student.id),
        language=student.preferred_language,
    )
    return {
        "student": _student_payload(student),
        "learning_profile": asdict(profile),
    }


@router.patch("/learning-profile")
async def update_my_learning_profile(
    payload: UpdateLearningProfileRequest,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    token = _extract_bearer_token(authorization)
    if not token or token not in AUTH_TOKENS:
        raise HTTPException(status_code=401, detail="Token invalide ou manquant")

    student_id = AUTH_TOKENS[token]
    profile = await student_profile_manager.get_or_create(student_id)

    if payload.name is not None:
        profile.name = payload.name.strip() or profile.name
    if payload.language is not None:
        profile.language = payload.language.strip().lower() or profile.language
    if payload.level is not None:
        profile.level = payload.level.strip().lower() or profile.level

    await student_profile_manager.save(profile)
    return {"status": "updated", "learning_profile": asdict(profile)}
