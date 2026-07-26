"""Historical-stats response shapes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from app.schemas.common import RunInfo, SimStat


class Metric(StrEnum):
    WINS = "wins"
    PODIUMS = "podiums"
    POLES = "poles"
    POINTS = "points"
    CHAMPIONSHIPS = "championships"


class GroupBy(StrEnum):
    DRIVER = "driver"
    CONSTRUCTOR = "constructor"
    DRIVER_NATIONALITY = "driver_nationality"
    CONSTRUCTOR_NATIONALITY = "constructor_nationality"


class Basis(StrEnum):
    """Which estimate the table is ranked by."""

    SIM = "sim"
    SCALED = "scaled"
    ACTUAL = "actual"


class LeaderRow(BaseModel):
    rank: int
    key: str
    label: str
    #: Career span for a driver, member count for a group.
    sublabel: str | None = None

    actual: float
    scaled: float
    sim: SimStat

    #: Rank on the unadjusted record, and the movement against it. Positive means
    #: the normalisation moved this entry up.
    rank_actual: int | None = None
    rank_delta: int | None = None

    n_entities: int = 1
    seasons_active: int | None = None
    first_year: int | None = None
    last_year: int | None = None


class LeaderBoard(BaseModel):
    metric: Metric
    group_by: GroupBy
    basis: Basis
    total: int
    #: Applied to driver leaderboards only; groups have no race count.
    min_races: int
    year_from: int | None = None
    year_to: int | None = None
    run: RunInfo
    rows: list[LeaderRow]
