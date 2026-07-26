"""Precomputed simulation output.

Written once by `scripts/run_simulations.py`, read at request time. The API never
simulates anything — 77 seasons at 10,000 iterations is a batch job, not a
request handler.

Three tiers, because no single one serves both reads:

  * `season_*_sim` — summary quantiles. Drives every season-tab render with one
    indexed query, and could not be reconstructed from the blobs cheaply.
  * `sim_iterations` — the raw per-iteration draws. Career and group intervals
    cannot be derived from per-season summaries at all (see `app.sim.career`),
    and keeping them means a new grouping dimension can be added later without
    re-running the Monte Carlo.
  * `career_driver_sim` / `group_sim` — rollups precomputed from the blobs, so
    the historical tab does not decompress thousands of arrays per request.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, Index, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SimRun(Base):
    """One execution of the batch job. The API reads the newest complete run."""

    __tablename__ = "sim_runs"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    n_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    target_races: Mapped[int] = mapped_column(Integer, nullable=False)
    master_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Set only once every table is written, so a crashed run is never served.
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seasons_simulated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String)


class SeasonDriverSim(Base):
    __tablename__ = "season_driver_sim"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The team the driver drove for most that season, for labelling.
    constructor_id: Mapped[int | None] = mapped_column(Integer)

    actual_races: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    actual_points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_points_no_fl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_wins: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_podiums: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_poles: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    #: The naive 24/R projection, shown beside every simulated figure.
    scaled_points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled_points_no_fl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled_wins: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled_podiums: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled_poles: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    points_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    points_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    points_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    points_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    wins_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wins_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wins_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wins_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    podiums_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    podiums_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    podiums_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    podiums_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    poles_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    poles_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    poles_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    poles_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    #: Expected starts out of the target 24 — context for part-season entrants.
    entries_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entries_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entries_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    p_champion: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p_top3: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: Where the driver actually finished the real championship.
    actual_position: Mapped[int | None] = mapped_column(Integer)


Index("idx_season_driver_sim_year", SeasonDriverSim.run_id, SeasonDriverSim.year)
Index("idx_season_driver_sim_driver", SeasonDriverSim.run_id, SeasonDriverSim.driver_id)


class SeasonConstructorSim(Base):
    __tablename__ = "season_constructor_sim"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    constructor_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    actual_points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_wins: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_podiums: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    scaled_points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled_wins: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled_podiums: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    points_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    points_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    points_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    points_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    wins_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wins_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wins_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wins_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    podiums_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    podiums_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    podiums_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    podiums_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    p_champion: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


Index(
    "idx_season_constructor_sim_year",
    SeasonConstructorSim.run_id,
    SeasonConstructorSim.year,
)


class SimIteration(Base):
    """Compressed per-iteration draws, one row per (season, entity, metric).

    Roughly 3,300 driver-seasons at 10,000 iterations. Counts fit in uint8 and
    points in uint16, and the arrays are highly repetitive — most are all-zero —
    so zlib brings the total to tens of megabytes.
    """

    __tablename__ = "sim_iterations"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String, primary_key=True)  # driver|constructor
    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric: Mapped[str] = mapped_column(String, primary_key=True)

    dtype: Mapped[str] = mapped_column(String, nullable=False)
    n_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


Index(
    "idx_sim_iterations_entity",
    SimIteration.run_id,
    SimIteration.entity_type,
    SimIteration.entity_id,
    SimIteration.metric,
)


class CareerDriverSim(Base):
    """All-time driver totals, summed from the iteration draws — not the medians."""

    __tablename__ = "career_driver_sim"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    seasons_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_year: Mapped[int] = mapped_column(Integer, nullable=False)
    last_year: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_races: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    actual_wins: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_podiums: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_poles: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_championships: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    scaled_wins: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled_podiums: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled_poles: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled_points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    wins_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wins_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wins_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wins_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    podiums_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    podiums_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    podiums_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    podiums_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    poles_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    poles_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    poles_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    poles_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    points_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    points_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    points_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    points_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    championships_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    championships_median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    championships_p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    championships_p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: JSON {n: P(titles >= n)} — the headline number the summaries cannot give.
    championships_at_least: Mapped[str | None] = mapped_column(String)


class GroupSim(Base):
    """Aggregations by constructor, nationality, decade or era."""

    __tablename__ = "group_sim"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dimension: Mapped[str] = mapped_column(String, primary_key=True)
    group_key: Mapped[str] = mapped_column(String, primary_key=True)
    metric: Mapped[str] = mapped_column(String, primary_key=True)

    group_label: Mapped[str] = mapped_column(String, nullable=False)
    n_entities: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    actual: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scaled: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    median: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p2_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p97_5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


Index("idx_group_sim_lookup", GroupSim.run_id, GroupSim.dimension, GroupSim.metric)
