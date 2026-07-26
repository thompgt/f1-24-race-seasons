"""A season reduced to race x entity matrices, ready to be resampled.

Every metric the app reports — points, wins, podiums, poles, entries — is a sum
over races. Laying a season out as one matrix per metric therefore turns the
whole bootstrap into a matrix multiply: see `app.sim.bootstrap`.

The resampling unit is the race *weekend*, not the Grand Prix alone. A sprint
travels with the weekend it belongs to, so a 22-race season with 6 sprints
normalises to 24 weekends carrying about 6.5 sprints, and the sprint-to-GP ratio
of the era is preserved. Sprint points are still scored on their own scale and
reported as their own metric.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Metrics carried per driver. Each is additive over races, which is the property
#: the bootstrap depends on.
#:
#: `quality_wins` is a win weighted by how contested it was — see `app.sim.elo`.
#: It is additive over races exactly like a raw win, so it needs nothing special
#: here and is bootstrapped by the same matrix multiply. That composition is the
#: point: the two corrections this app makes (opportunity, and difficulty) are
#: independent, and applying both answers "how many *contested* wins would this
#: driver have taken over a modern calendar".
DRIVER_METRICS = (
    "points",
    "points_no_fl",
    "sprint_points",
    "wins",
    "quality_wins",
    "podiums",
    "poles",
    "entries",
)

#: Constructors have no pole or entry concept worth reporting separately.
CONSTRUCTOR_METRICS = ("points", "points_no_fl", "sprint_points", "wins", "quality_wins", "podiums")


@dataclass(frozen=True)
class SeasonEventSet:
    """One season's races as (races x entities) matrices.

    Rows are races in calendar order; columns are the drivers or constructors who
    started at least one race that season. A driver absent from a race is simply
    zero in that row, which is why part-season entrants need no special handling:
    their expected 24-race total is their actual total scaled by 24/R, and the
    `entries` metric reports how many of the 24 they would have started.
    """

    year: int
    n_races: int
    driver_ids: np.ndarray
    constructor_ids: np.ndarray
    #: Modal constructor per driver that season, for display.
    driver_constructor: np.ndarray
    driver: dict[str, np.ndarray]
    constructor: dict[str, np.ndarray]

    def matrix(self, entity: str, metric: str) -> np.ndarray:
        return (self.driver if entity == "driver" else self.constructor)[metric]

    def ids(self, entity: str) -> np.ndarray:
        return self.driver_ids if entity == "driver" else self.constructor_ids

    def actual(self, entity: str, metric: str) -> np.ndarray:
        """Season totals as they really happened, summed over races."""
        return self.matrix(entity, metric).sum(axis=0)

    def scaled(self, entity: str, metric: str, target_races: int) -> np.ndarray:
        """The naive pro-rata projection: actual x target/R.

        Shown alongside every simulated figure. It is also exactly what the
        bootstrap mean must converge to, which makes it a correctness check as
        well as a comparison — see tests/test_bootstrap.py.
        """
        return self.actual(entity, metric) * (target_races / self.n_races)


def build_event_set(
    year: int,
    *,
    race_ids: np.ndarray,
    driver_ids: np.ndarray,
    constructor_ids: np.ndarray,
    rows: dict[str, np.ndarray],
    pole_driver_ids: np.ndarray,
    sprint_rows: dict[str, np.ndarray] | None = None,
) -> SeasonEventSet:
    """Assemble the metric matrices from flat per-result arrays.

    `rows` holds parallel arrays over race results: race_id, driver_id,
    constructor_id, points, points_no_fl, is_win, is_podium. `pole_driver_ids` is
    one entry per race, aligned with `race_ids`.

    Kept free of any database or pandas dependency so the simulation can be
    exercised on synthetic input.
    """
    race_index = {int(r): i for i, r in enumerate(race_ids)}
    driver_index = {int(d): i for i, d in enumerate(driver_ids)}
    constructor_index = {int(c): i for i, c in enumerate(constructor_ids)}

    n_races = len(race_ids)
    n_drivers = len(driver_ids)
    n_constructors = len(constructor_ids)

    driver_mats = {
        metric: np.zeros((n_races, n_drivers), dtype=np.float32) for metric in DRIVER_METRICS
    }
    constructor_mats = {
        metric: np.zeros((n_races, n_constructors), dtype=np.float32)
        for metric in CONSTRUCTOR_METRICS
    }

    race_pos = np.array([race_index[int(r)] for r in rows["race_id"]], dtype=np.intp)
    driver_pos = np.array([driver_index[int(d)] for d in rows["driver_id"]], dtype=np.intp)

    # np.add.at rather than fancy-index assignment: a driver can appear only once
    # per race, but constructors have two cars, so their rows must accumulate.
    # A season built without Elo ratings yet — as the ingest tests do — simply
    # carries no quality credit, and the metric stays zero rather than erroring.
    quality = rows.get("quality_win")
    if quality is None:
        quality = np.zeros(len(race_pos), dtype=np.float32)

    for metric, values in (
        ("points", rows["points"]),
        ("points_no_fl", rows["points_no_fl"]),
        ("wins", rows["is_win"]),
        ("quality_wins", quality),
        ("podiums", rows["is_podium"]),
    ):
        np.add.at(driver_mats[metric], (race_pos, driver_pos), np.asarray(values, dtype=np.float32))
    np.add.at(driver_mats["entries"], (race_pos, driver_pos), np.float32(1.0))

    has_constructor = np.array(
        [c is not None and not np.isnan(float(c)) for c in rows["constructor_id"]], dtype=bool
    )
    ctor_pos = np.array(
        [constructor_index[int(c)] for c in np.asarray(rows["constructor_id"])[has_constructor]],
        dtype=np.intp,
    )
    ctor_race_pos = race_pos[has_constructor]
    for metric, values in (
        ("points", rows["points"]),
        ("points_no_fl", rows["points_no_fl"]),
        ("wins", rows["is_win"]),
        ("quality_wins", quality),
        ("podiums", rows["is_podium"]),
    ):
        np.add.at(
            constructor_mats[metric],
            (ctor_race_pos, ctor_pos),
            np.asarray(values, dtype=np.float32)[has_constructor],
        )

    if sprint_rows is not None and len(sprint_rows["race_id"]):
        sprint_race_pos = np.array(
            [race_index[int(r)] for r in sprint_rows["race_id"]], dtype=np.intp
        )
        sprint_driver_pos = np.array(
            [driver_index[int(d)] for d in sprint_rows["driver_id"]], dtype=np.intp
        )
        sprint_points = np.asarray(sprint_rows["points"], dtype=np.float32)
        np.add.at(
            driver_mats["sprint_points"], (sprint_race_pos, sprint_driver_pos), sprint_points
        )

        sprint_has_ctor = np.array(
            [c is not None and not np.isnan(float(c)) for c in sprint_rows["constructor_id"]],
            dtype=bool,
        )
        np.add.at(
            constructor_mats["sprint_points"],
            (
                sprint_race_pos[sprint_has_ctor],
                np.array(
                    [
                        constructor_index[int(c)]
                        for c in np.asarray(sprint_rows["constructor_id"])[sprint_has_ctor]
                    ],
                    dtype=np.intp,
                ),
            ),
            sprint_points[sprint_has_ctor],
        )

    # Poles: one-hot per race. A race with no attributed pole contributes nothing.
    for race_id, pole_driver in zip(race_ids, pole_driver_ids):
        if pole_driver is None:
            continue
        pole = int(pole_driver)
        if pole in driver_index:
            driver_mats["poles"][race_index[int(race_id)], driver_index[pole]] = 1.0

    driver_constructor = _modal_constructor(
        rows, driver_index, constructor_index, n_drivers, constructor_ids
    )

    return SeasonEventSet(
        year=year,
        n_races=n_races,
        driver_ids=np.asarray(driver_ids, dtype=np.int64),
        constructor_ids=np.asarray(constructor_ids, dtype=np.int64),
        driver_constructor=driver_constructor,
        driver=driver_mats,
        constructor=constructor_mats,
    )


def _modal_constructor(
    rows: dict[str, np.ndarray],
    driver_index: dict[int, int],
    constructor_index: dict[int, int],
    n_drivers: int,
    constructor_ids: np.ndarray,
) -> np.ndarray:
    """The team each driver drove for most that season.

    Mid-season switches are real (and the constructor matrices attribute each
    race to whoever the driver actually drove for), so this is for labelling only.
    """
    counts = np.zeros((n_drivers, len(constructor_ids)), dtype=np.int32)
    for driver, constructor in zip(rows["driver_id"], rows["constructor_id"]):
        if constructor is None or np.isnan(float(constructor)):
            continue
        counts[driver_index[int(driver)], constructor_index[int(constructor)]] += 1

    modal = np.full(n_drivers, -1, dtype=np.int64)
    seen = counts.sum(axis=1) > 0
    modal[seen] = np.asarray(constructor_ids, dtype=np.int64)[counts[seen].argmax(axis=1)]
    return modal
