"""All API routes. Read-only; every response is served from precomputed tables."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.common import RunInfo
from app.schemas.season import ChampionOdds, SeasonDetail, SeasonSummary
from app.services import season_service

router = APIRouter()


async def require_run(db: AsyncSession = Depends(get_db)) -> RunInfo:
    """The newest complete simulation run, or a clear error explaining the fix."""
    run = await season_service.current_run(db)
    if run is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No completed simulation run. Build the database with "
                "scripts/build_db.py, then run scripts/run_simulations.py."
            ),
        )
    return run


@router.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", "database_present": settings.db_path.exists()}


@router.get("/seasons", response_model=list[SeasonSummary])
async def get_seasons(
    db: AsyncSession = Depends(get_db), run: RunInfo = Depends(require_run)
) -> list[SeasonSummary]:
    return await season_service.list_seasons(db, run)


@router.get("/seasons/{year}", response_model=SeasonDetail)
async def get_season(
    year: int, db: AsyncSession = Depends(get_db), run: RunInfo = Depends(require_run)
) -> SeasonDetail:
    season = await season_service.get_season(db, year, run)
    if season is None:
        raise HTTPException(status_code=404, detail=f"No season {year}")
    return season


@router.get("/seasons/{year}/champion-odds", response_model=list[ChampionOdds])
async def get_champion_odds(
    year: int, db: AsyncSession = Depends(get_db), run: RunInfo = Depends(require_run)
) -> list[ChampionOdds]:
    odds = await season_service.champion_odds(db, year, run)
    if not odds:
        raise HTTPException(status_code=404, detail=f"No season {year}")
    return odds
