"""Driver-detail response shapes."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ConstructorRef, DriverRef, RunInfo, SimStat
from app.schemas.ratings import DriverRating


class DriverSeason(BaseModel):
    year: int
    constructor: ConstructorRef | None = None
    races: int
    actual_wins: float
    actual_podiums: float
    actual_poles: float
    actual_points: float
    actual_quality_wins: float
    scaled_wins: float
    quality_wins: SimStat
    wins: SimStat
    podiums: SimStat
    poles: SimStat
    points: SimStat
    p_champion: float
    is_actual_champion: bool


class CareerTotals(BaseModel):
    seasons: int
    first_year: int
    last_year: int
    races: int
    actual_wins: float
    actual_podiums: float
    actual_poles: float
    actual_points: float
    actual_championships: int
    scaled_wins: float
    scaled_podiums: float
    scaled_poles: float
    actual_quality_wins: float
    quality_wins: SimStat
    wins: SimStat
    podiums: SimStat
    poles: SimStat
    points: SimStat
    championships: SimStat
    #: P(career titles >= n), keyed by n. The number summed probabilities cannot give.
    championships_at_least: dict[int, float]


class DriverDetail(BaseModel):
    driver: DriverRef
    dob: str | None = None
    run: RunInfo
    career: CareerTotals
    seasons: list[DriverSeason]
    #: Absent for a driver with no rated races (every excluded-round entrant).
    rating: DriverRating | None = None
