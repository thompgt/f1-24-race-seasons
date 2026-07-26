"""Methodology and run-metadata shapes."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import RunInfo


class MethodStep(BaseModel):
    title: str
    detail: str


class Caveat(BaseModel):
    """A known limitation, served to the UI so the panel cannot drift from the code."""

    key: str
    title: str
    detail: str


class Meta(BaseModel):
    run: RunInfo
    first_year: int
    last_year: int
    target_races: int
    shortest_season_year: int
    shortest_season_races: int
    longest_season_year: int
    longest_season_races: int
    data_sources: list[str]
    method: list[MethodStep]
    caveats: list[Caveat]
