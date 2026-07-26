"""All API routes. Read-only; every response is served from precomputed tables."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "database_present": settings.db_path.exists(),
    }
