"""All API routes. Read-only; every response is served from precomputed tables."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.common import DriverRef, RunInfo
from app.schemas.driver import DriverDetail
from app.schemas.historical import Basis, GroupBy, LeaderBoard, Metric
from app.schemas.meta import Meta
from app.schemas.ratings import NotableWin, RatingBoard, RatingSort
from app.schemas.season import ChampionOdds, SeasonDetail, SeasonSummary
from app.services import (
    driver_service,
    historical_service,
    meta_service,
    ratings_service,
    season_service,
)

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


@router.get("/meta", response_model=Meta)
async def get_meta(
    db: AsyncSession = Depends(get_db), run: RunInfo = Depends(require_run)
) -> Meta:
    return await meta_service.build_meta(db, run)


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


@router.get("/historical/leaders", response_model=LeaderBoard)
async def get_leaders(
    metric: Metric = Metric.WINS,
    group_by: GroupBy = GroupBy.DRIVER,
    basis: Basis = Basis.SIM,
    min_races: int = Query(historical_service.DEFAULT_MIN_RACES, ge=0, le=400),
    year_from: int | None = Query(None, ge=1950, le=2100),
    year_to: int | None = Query(None, ge=1950, le=2100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    run: RunInfo = Depends(require_run),
) -> LeaderBoard:
    if year_from is not None and year_to is not None and year_from > year_to:
        raise HTTPException(
            status_code=422, detail="year_from must not be later than year_to"
        )
    if group_by is not GroupBy.DRIVER and (year_from or year_to):
        raise HTTPException(
            status_code=422,
            detail=(
                "The year range applies to driver leaderboards only; group totals "
                "cover full history."
            ),
        )
    return await historical_service.leaderboard(
        db,
        run,
        metric=metric,
        group_by=group_by,
        basis=basis,
        min_races=min_races,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
        offset=offset,
    )


@router.get("/ratings/leaders", response_model=RatingBoard)
async def get_rating_leaders(
    sort: RatingSort = RatingSort.TEAMMATE,
    min_races: int = Query(ratings_service.DEFAULT_MIN_RACES, ge=0, le=400),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> RatingBoard:
    return await ratings_service.leaderboard(
        db, sort=sort, min_races=min_races, limit=limit, offset=offset
    )


@router.get("/ratings/wins", response_model=list[NotableWin])
async def get_notable_wins(
    order: str = Query("hardest", pattern="^(hardest|easiest)$"),
    limit: int = Query(15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[NotableWin]:
    return await ratings_service.notable_wins(db, hardest=order == "hardest", limit=limit)


@router.get("/drivers/search", response_model=list[DriverRef])
async def search_drivers(
    q: str = Query(..., min_length=1, max_length=60),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    run: RunInfo = Depends(require_run),
) -> list[DriverRef]:
    return await driver_service.search_drivers(db, q, run, limit=limit)


@router.get("/drivers/{driver_id}", response_model=DriverDetail)
async def get_driver(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    run: RunInfo = Depends(require_run),
) -> DriverDetail:
    driver = await driver_service.get_driver(db, driver_id, run)
    if driver is None:
        raise HTTPException(status_code=404, detail=f"No driver {driver_id}")
    return driver
