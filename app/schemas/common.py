"""Response shapes shared across endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SimStat(BaseModel):
    """A simulated total: the central estimate and its 95% interval."""

    mean: float
    median: float
    p2_5: float = Field(description="2.5th percentile across iterations")
    p97_5: float = Field(description="97.5th percentile across iterations")


class RunInfo(BaseModel):
    run_id: int
    created_at: str
    n_iterations: int
    target_races: int
    master_seed: int
    seasons_simulated: int


class DriverRef(BaseModel):
    driver_id: int
    name: str
    code: str | None = None
    nationality: str | None = None


class ConstructorRef(BaseModel):
    constructor_id: int
    name: str
    nationality: str | None = None
