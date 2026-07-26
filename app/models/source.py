"""Source-data tables: the ingested historical record, before any simulation.

Identity columns reuse Ergast's integer ids so the CSV dump loads without
remapping. Drivers and constructors that appear only in Jolpica data (2025+) are
assigned ids from JOLPICA_ID_BASE upward — see `app.ingestion.normalize`.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

#: Synthetic ids for entities that exist only in Jolpica, never in the CSV dump.
JOLPICA_ID_BASE = 10_000


class Season(Base):
    __tablename__ = "seasons"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Championship races after exclusions (Indy 500 1950-60).
    n_races: Mapped[int] = mapped_column(Integer, nullable=False)
    n_sprints: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: False for a season still in progress (e.g. a partial 2026).
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # ergast_csv | jolpica

    #: Who actually won the title, under the rules of the day — the baseline the
    #: simulated champion is compared against.
    actual_champion_driver_id: Mapped[int | None] = mapped_column(Integer)


class Driver(Base):
    __tablename__ = "drivers"

    driver_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_ref: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    code: Mapped[str | None] = mapped_column(String)
    forename: Mapped[str] = mapped_column(String, nullable=False)
    surname: Mapped[str] = mapped_column(String, nullable=False)
    dob: Mapped[str | None] = mapped_column(String)
    nationality: Mapped[str | None] = mapped_column(String)


class Constructor(Base):
    __tablename__ = "constructors"

    constructor_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    constructor_ref: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    nationality: Mapped[str | None] = mapped_column(String)


class Circuit(Base):
    __tablename__ = "circuits"

    circuit_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    circuit_ref: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str | None] = mapped_column(String)
    country: Mapped[str | None] = mapped_column(String)


class Race(Base):
    __tablename__ = "races"

    race_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(
        Integer, ForeignKey("seasons.year"), nullable=False
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    circuit_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("circuits.circuit_id")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[str | None] = mapped_column(String)
    has_sprint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Counted for the WDC historically but excluded here (Indy 500 1950-60).
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String)

    #: Derived at ingest, not at simulation time.
    pole_driver_id: Mapped[int | None] = mapped_column(Integer)
    pole_source: Mapped[str | None] = mapped_column(String)  # grid | qualifying


Index("idx_races_year", Race.year)


class RaceResult(Base):
    __tablename__ = "race_results"

    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id"), primary_key=True
    )
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.driver_id"), primary_key=True
    )
    constructor_id: Mapped[int | None] = mapped_column(Integer)

    #: Starting grid slot; 0 in the source data where unknown (e.g. pit start).
    grid: Mapped[int | None] = mapped_column(Integer)
    #: Classified finishing position, or NULL. Points are scored off THIS, never
    #: off position_order, which is a dense rank that includes retirements.
    position: Mapped[int | None] = mapped_column(Integer)
    #: Raw Ergast positionText, preserved for audit: R/W/D/N/F/E mean not classified.
    position_text: Mapped[str | None] = mapped_column(String)
    position_order: Mapped[int | None] = mapped_column(Integer)

    #: Only ever true from 2004 — earlier seasons have no fastest-lap data at all.
    set_fastest_lap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: 1950s shared drives put two or three drivers on one classified position —
    #: 1,128 win-rows across 1,125 races. The lowest-resultId row in each
    #: (race, position) group is canonical; co-drivers are flagged here and score
    #: nothing, so "one win and three podiums per race" holds exactly.
    is_shared_secondary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: Same, with the fastest-lap point excluded. All-time leaderboards use this,
    #: because FL data existing only from 2004 would re-create the era bias.
    points_no_fl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    is_win: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_podium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: How contested this win was, normalised so the average win in history is
    #: worth 1.0; zero for anything that was not a win. Written by
    #: `scripts/build_elo.py` from pre-race ratings — see `app.sim.elo`.
    #:
    #: `server_default` rather than a Python-side default because the ingest
    #: writes this table through pandas `to_sql`, which names its columns
    #: explicitly and never sees SQLAlchemy's defaults. The value has to come
    #: from the DDL or the insert fails on the NOT NULL.
    quality_win: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )


Index("idx_race_results_driver", RaceResult.driver_id)


class SprintResult(Base):
    __tablename__ = "sprint_results"

    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id"), primary_key=True
    )
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.driver_id"), primary_key=True
    )
    constructor_id: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class Qualifying(Base):
    """Optional, Jolpica-sourced, 1994+ only.

    Used to cross-check the grid-derived pole attribution; the simulation itself
    never depends on it, since `grid == 1` has full coverage back to 1950.
    """

    __tablename__ = "qualifying"

    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id"), primary_key=True
    )
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.driver_id"), primary_key=True
    )
    position: Mapped[int | None] = mapped_column(Integer)


class DriverRaceRating(Base):
    """Elo ratings carried into and out of every race, per driver.

    One row per entry — around 27,000 in total, which is small enough to store
    outright and makes the rating traces on driver pages a single indexed read
    rather than a replay of the whole history.

    Written by `scripts/build_elo.py`. Unlike the simulation tables this carries
    no `run_id`: ratings are a deterministic function of the source results, so
    there is only ever one version of them for a given database.
    """

    __tablename__ = "driver_race_ratings"

    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id"), primary_key=True
    )
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.driver_id"), primary_key=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    rating_before: Mapped[float] = mapped_column(Float, nullable=False)
    rating_after: Mapped[float] = mapped_column(Float, nullable=False)
    teammate_rating_before: Mapped[float] = mapped_column(Float, nullable=False)
    teammate_rating_after: Mapped[float] = mapped_column(Float, nullable=False)
    #: Margin over the mean rating of this race's field. Raw ratings drift upward
    #: across eras, so cross-era comparisons use this instead.
    rating_vs_field: Mapped[float] = mapped_column(Float, nullable=False)
    #: Where the pre-race ratings expected this driver to finish. The basis of
    #: `RaceResult.quality_win`.
    expected_position: Mapped[float] = mapped_column(Float, nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)


Index("idx_driver_race_ratings_driver", DriverRaceRating.driver_id)
Index("idx_driver_race_ratings_year", DriverRaceRating.year)


class DriverElo(Base):
    """Career rating summary per driver, rolled up from the per-race ratings."""

    __tablename__ = "driver_elo"

    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.driver_id"), primary_key=True
    )
    races: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_year: Mapped[int] = mapped_column(Integer, nullable=False)
    last_year: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Best sustained level over a rolling window, not the highest single race.
    peak_rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_teammate_rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: The era-neutral one. Rank cross-era tables on this, not `peak_rating`.
    peak_vs_field: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    final_rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_teammate_rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    #: Wins, their summed difficulty credit, and the resulting average. Kept here
    #: as well as in the simulation tables because they describe what actually
    #: happened, independently of any 24-race run.
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_wins: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mean_win_difficulty: Mapped[float | None] = mapped_column(Float)
    #: Team-mate head-to-head record on classified finishes, for context on the
    #: team-mate rating.
    teammate_races: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    teammate_wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
