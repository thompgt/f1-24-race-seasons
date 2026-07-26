"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.endpoints import router
from app.core.config import settings

app = FastAPI(
    title="F1 24-Race Normalized Seasons",
    description=(
        "Every F1 season 1950-2025 re-simulated as a 24-race season, so all-time "
        "leaderboards aren't biased toward drivers who simply had more races."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
