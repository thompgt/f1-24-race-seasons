"""Read a season out of the database and hand it to the simulation.

This is the only seam between storage and `app.sim`, which stays free of any
database dependency so it can be tested on synthetic input.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.sim.events import SeasonEventSet, build_event_set

_RACES = text(
    """
    SELECT race_id, pole_driver_id
    FROM races
    WHERE year = :year AND excluded = 0
    ORDER BY round
    """
)

_RESULTS = text(
    """
    SELECT rr.race_id, rr.driver_id, rr.constructor_id,
           rr.points, rr.points_no_fl, rr.is_win, rr.is_podium
    FROM race_results rr
    JOIN races r ON r.race_id = rr.race_id
    WHERE r.year = :year AND r.excluded = 0
    """
)

_SPRINTS = text(
    """
    SELECT sr.race_id, sr.driver_id, sr.constructor_id, sr.points
    FROM sprint_results sr
    JOIN races r ON r.race_id = sr.race_id
    WHERE r.year = :year AND r.excluded = 0
    """
)


def load_season_events(conn: Connection, year: int) -> SeasonEventSet:
    """Build the metric matrices for one season."""
    races = conn.execute(_RACES, {"year": year}).all()
    if not races:
        raise ValueError(f"No races found for {year}")

    race_ids = np.array([row.race_id for row in races], dtype=np.int64)
    pole_driver_ids = [row.pole_driver_id for row in races]

    results = conn.execute(_RESULTS, {"year": year}).all()
    if not results:
        raise ValueError(f"No results found for {year}")

    rows = {
        "race_id": np.array([r.race_id for r in results], dtype=np.int64),
        "driver_id": np.array([r.driver_id for r in results], dtype=np.int64),
        "constructor_id": np.array(
            [np.nan if r.constructor_id is None else r.constructor_id for r in results],
            dtype=float,
        ),
        "points": np.array([r.points for r in results], dtype=np.float32),
        "points_no_fl": np.array([r.points_no_fl for r in results], dtype=np.float32),
        "is_win": np.array([r.is_win for r in results], dtype=np.float32),
        "is_podium": np.array([r.is_podium for r in results], dtype=np.float32),
    }

    sprints = conn.execute(_SPRINTS, {"year": year}).all()
    sprint_rows = {
        "race_id": np.array([s.race_id for s in sprints], dtype=np.int64),
        "driver_id": np.array([s.driver_id for s in sprints], dtype=np.int64),
        "constructor_id": np.array(
            [np.nan if s.constructor_id is None else s.constructor_id for s in sprints],
            dtype=float,
        ),
        "points": np.array([s.points for s in sprints], dtype=np.float32),
    }

    # Only entities that actually started a race that season get a column.
    driver_ids = np.unique(rows["driver_id"])
    constructor_ids = np.unique(
        rows["constructor_id"][~np.isnan(rows["constructor_id"])]
    ).astype(np.int64)

    return build_event_set(
        year,
        race_ids=race_ids,
        driver_ids=driver_ids,
        constructor_ids=constructor_ids,
        rows=rows,
        pole_driver_ids=pole_driver_ids,
        sprint_rows=sprint_rows if len(sprints) else None,
    )


def list_seasons(conn: Connection, *, include_in_progress: bool = True) -> list[int]:
    sql = "SELECT year FROM seasons WHERE n_races > 0"
    if not include_in_progress:
        sql += " AND is_complete = 1"
    return [row.year for row in conn.execute(text(sql + " ORDER BY year")).all()]
