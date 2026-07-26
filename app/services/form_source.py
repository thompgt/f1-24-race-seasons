"""Read a season's end-of-year form out of the database.

The seam between storage and `app.sim.continuation`, mirroring what
`event_source` does for the bootstrap. Kept separate so the simulation module
stays database-free and testable on synthetic input.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.sim.continuation import (
    DEFAULT_ENSEMBLE,
    SeasonForm,
    fit_strength_ensemble,
    recency_weights,
)

_RACES = text(
    """
    SELECT race_id, round
    FROM races
    WHERE year = :year AND excluded = 0
    ORDER BY round
    """
)

_RESULTS = text(
    """
    SELECT rr.race_id, rr.driver_id, rr.position, rr.points_no_fl,
           rr.is_win, rr.is_podium, rr.is_shared_secondary
    FROM race_results rr
    JOIN races r ON r.race_id = rr.race_id
    WHERE r.year = :year AND r.excluded = 0
    """
)

_SPRINT_POINTS = text(
    """
    SELECT sr.driver_id, SUM(sr.points) AS points
    FROM sprint_results sr
    JOIN races r ON r.race_id = sr.race_id
    WHERE r.year = :year AND r.excluded = 0
    GROUP BY sr.driver_id
    """
)


def load_season_form(
    conn: Connection,
    year: int,
    *,
    half_life: float | None = None,
    rng: np.random.Generator | None = None,
    ensemble: int = DEFAULT_ENSEMBLE,
) -> SeasonForm:
    """Assemble one season's banked totals and fitted end-of-season form."""
    races = conn.execute(_RACES, {"year": year}).all()
    if not races:
        raise ValueError(f"No races found for {year}")
    race_order = {int(row.race_id): i for i, row in enumerate(races)}
    n_races = len(races)

    results = conn.execute(_RESULTS, {"year": year}).all()
    if not results:
        raise ValueError(f"No results found for {year}")

    driver_ids = sorted({int(row.driver_id) for row in results})
    index = {driver: i for i, driver in enumerate(driver_ids)}
    n_drivers = len(driver_ids)

    points = np.zeros(n_drivers)
    wins = np.zeros(n_drivers)
    podiums = np.zeros(n_drivers)
    starts = np.zeros(n_drivers)
    retirements = np.zeros(n_drivers)

    # Finishing orders per race, best first. Classified finishers only: a
    # retirement says nothing about pace, and is modelled as its own draw.
    finishers: dict[int, list[tuple[int, int]]] = {i: [] for i in range(n_races)}

    for row in results:
        driver = index[int(row.driver_id)]
        slot = race_order[int(row.race_id)]

        # A shared-drive co-driver did not take the car to that position on
        # their own, so they neither score nor contribute to the fit — the same
        # rule the rest of the app applies.
        if row.is_shared_secondary:
            continue

        starts[driver] += 1
        points[driver] += row.points_no_fl or 0.0
        wins[driver] += 1 if row.is_win else 0
        podiums[driver] += 1 if row.is_podium else 0

        if row.position is None:
            retirements[driver] += 1
        else:
            finishers[slot].append((int(row.position), driver))

    for driver_id, sprint in conn.execute(_SPRINT_POINTS, {"year": year}).all():
        if int(driver_id) in index:
            points[index[int(driver_id)]] += sprint or 0.0

    orderings = []
    weights_by_race = recency_weights(n_races, **({"half_life": half_life} if half_life else {}))
    kept_weights = []
    for slot in range(n_races):
        classified = sorted(finishers[slot])
        if len(classified) < 2:
            continue
        orderings.append(np.array([driver for _, driver in classified]))
        kept_weights.append(weights_by_race[slot])

    # Seeded off the year so a season's fitted form does not depend on the
    # order seasons happen to be processed in.
    strength = (
        fit_strength_ensemble(
            orderings,
            np.array(kept_weights),
            n_drivers,
            rng=rng if rng is not None else np.random.default_rng(year),
            n_samples=ensemble,
        )
        if orderings
        else np.ones((1, n_drivers))
    )

    return SeasonForm(
        year=year,
        n_races=n_races,
        driver_ids=np.array(driver_ids, dtype=np.int64),
        points=points,
        wins=wins,
        podiums=podiums,
        strength=strength,
        entry_rate=starts / n_races,
        dnf_rate=np.divide(
            retirements, starts, out=np.zeros(n_drivers), where=starts > 0
        ),
    )
