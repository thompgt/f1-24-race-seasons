"""Rating and win-difficulty response shapes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class RatingSort(StrEnum):
    """Which column the ratings table is ordered by.

    `PEAK` is a within-era measure: raw Elo drifts upward as the sport grows, so
    an all-time table ranked on it leans modern for reasons unrelated to driving.
    `VS_FIELD` and `TEAMMATE` are the ones to compare eras on.
    """

    PEAK = "peak"
    TEAMMATE = "teammate"
    VS_FIELD = "vs_field"
    QUALITY_WINS = "quality_wins"
    DIFFICULTY = "difficulty"


class RatingRow(BaseModel):
    rank: int
    driver_id: int
    name: str
    nationality: str | None = None
    first_year: int
    last_year: int
    races: int

    peak_rating: float
    peak_teammate_rating: float
    peak_vs_field: float
    final_rating: float

    wins: int
    #: Summed difficulty credit over those wins, on the raw record — not
    #: normalised to 24 races. The 24-race version lives on the historical
    #: leaderboard under the `quality_wins` metric.
    quality_wins: float
    #: quality_wins / wins. 1.0 is an average win; below 1 means the field was
    #: not expected to trouble them. Null for a driver who never won.
    mean_win_difficulty: float | None = None

    teammate_races: int
    teammate_wins: int


class RatingBoard(BaseModel):
    sort: RatingSort
    min_races: int
    total: int
    rows: list[RatingRow]


class NotableWin(BaseModel):
    """One race win, with the difficulty the ratings assigned it."""

    race_id: int
    year: int
    race_name: str
    driver_id: int
    driver_name: str
    constructor_name: str | None = None
    #: Credit relative to the average win in history.
    difficulty: float
    #: Where the pre-race ratings expected the winner to finish.
    expected_position: float
    starters: int


class RatingPoint(BaseModel):
    """One race in a driver's rating trace."""

    race_id: int
    year: int
    rating: float
    teammate_rating: float
    position: int | None = None
    #: Set only where the driver won, so the chart can mark wins by difficulty.
    win_difficulty: float | None = None


class DriverRating(BaseModel):
    """A driver's rating summary and trace, for their detail page."""

    peak_rating: float
    peak_teammate_rating: float
    peak_vs_field: float
    final_rating: float
    final_teammate_rating: float
    wins: int
    quality_wins: float
    mean_win_difficulty: float | None = None
    teammate_races: int
    teammate_wins: int
    #: Rank on peak team-mate rating among drivers with a comparable career.
    teammate_rank: int | None = None
    trace: list[RatingPoint] = []
