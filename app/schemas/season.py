"""Season-tab response shapes."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ConstructorRef, DriverRef, RunInfo, SimStat


class SeasonSummary(BaseModel):
    year: int
    n_races: int
    n_sprints: int
    is_complete: bool
    source: str
    actual_champion: DriverRef | None = None
    #: The driver who takes the title most often across iterations.
    likeliest_champion: DriverRef | None = None
    likeliest_champion_probability: float = 0.0
    #: True when the simulation's likeliest champion is not the real one.
    champion_changes: bool = False


class ActualTotals(BaseModel):
    races: int
    points: float
    points_no_fl: float
    wins: float
    podiums: float
    poles: float
    position: int | None = None


class ScaledTotals(BaseModel):
    """The naive pro-rata projection, actual x 24/R."""

    points: float
    wins: float
    podiums: float
    poles: float


class SeasonDriverRow(BaseModel):
    driver: DriverRef
    constructor: ConstructorRef | None = None
    actual: ActualTotals
    scaled: ScaledTotals
    points: SimStat
    wins: SimStat
    podiums: SimStat
    poles: SimStat
    #: Expected starts out of the target 24 — context for part-season entrants.
    entries_mean: float
    entries_p2_5: float
    entries_p97_5: float
    p_champion: float
    p_top3: float
    is_actual_champion: bool = False
    #: Flagged in the UI: this driver contested less than half the season.
    is_part_season: bool = False


class SeasonConstructorRow(BaseModel):
    constructor: ConstructorRef
    actual_points: float
    actual_wins: float
    actual_podiums: float
    scaled_points: float
    scaled_wins: float
    scaled_podiums: float
    points: SimStat
    wins: SimStat
    podiums: SimStat
    p_champion: float


class ExcludedRace(BaseModel):
    name: str
    reason: str


class SeasonDetail(BaseModel):
    year: int
    n_races: int
    n_sprints: int
    target_races: int
    is_complete: bool
    actual_champion: DriverRef | None = None
    excluded_races: list[ExcludedRace] = []
    run: RunInfo
    drivers: list[SeasonDriverRow]
    constructors: list[SeasonConstructorRow]


class ChampionOdds(BaseModel):
    driver: DriverRef
    p_champion: float
    is_actual_champion: bool
