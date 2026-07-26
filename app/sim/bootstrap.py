"""The 24-race bootstrap.

For a season that ran R races, draw 24 race weekends with replacement and total
each driver's results; repeat 10,000 times. The naive implementation would build
an (iterations x 24 x drivers) tensor. It never needs to.

Drawing 24 races with replacement from R gives a per-race count vector that is
*exactly* Multinomial(24, uniform(R)) — and since every metric is additive over
races, a driver's simulated total is just the count vector dotted with their
column. So the whole thing is one matrix multiply per metric:

    counts = rng.multinomial(24, [1/R] * R, size=n_iterations)   # (N, R)
    totals = counts @ metric_matrix                              # (N, D)

This is not an approximation of the loop — it is the same distribution, computed
in one step. It turns a 76-season run from minutes into well under a second.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.sim.events import CONSTRUCTOR_METRICS, DRIVER_METRICS, SeasonEventSet
from app.sim.rng import season_generator

DEFAULT_ITERATIONS = 10_000
DEFAULT_TARGET_RACES = 24

#: Compact storage for the per-iteration draws. Counts fit in a byte; points can
#: reach 24 x 26 = 624 for a driver and roughly double that for a constructor.
_METRIC_DTYPES = {
    "wins": np.uint8,
    "podiums": np.uint8,
    "poles": np.uint8,
    "entries": np.uint8,
    "points": np.uint16,
    "points_no_fl": np.uint16,
    "sprint_points": np.uint16,
}


@dataclass(frozen=True)
class EntitySimResult:
    """Per-iteration totals for one entity type in one season."""

    entity: str  # driver | constructor
    ids: np.ndarray  # (E,)
    totals: dict[str, np.ndarray]  # metric -> (N, E) float32
    actual: dict[str, np.ndarray]  # metric -> (E,)
    scaled: dict[str, np.ndarray]  # metric -> (E,)
    champion_index: np.ndarray  # (N,) index into ids
    runner_up_index: np.ndarray  # (N,)
    third_index: np.ndarray  # (N,)

    def champion_probability(self) -> np.ndarray:
        return _index_frequency(self.champion_index, len(self.ids))

    def top_three_probability(self) -> np.ndarray:
        counts = (
            _index_frequency(self.champion_index, len(self.ids))
            + _index_frequency(self.runner_up_index, len(self.ids))
            + _index_frequency(self.third_index, len(self.ids))
        )
        return counts

    def iteration_draws(self, metric: str) -> np.ndarray:
        """Per-iteration totals for one metric, in compact integer form."""
        return np.rint(self.totals[metric]).astype(_METRIC_DTYPES[metric])

    def championship_draws(self) -> np.ndarray:
        """(N, E) uint8 indicator of who took the title in each iteration."""
        wins = np.zeros((len(self.champion_index), len(self.ids)), dtype=np.uint8)
        wins[np.arange(len(self.champion_index)), self.champion_index] = 1
        return wins


@dataclass(frozen=True)
class SeasonSimResult:
    year: int
    n_races: int
    target_races: int
    n_iterations: int
    driver: EntitySimResult
    constructor: EntitySimResult


def _index_frequency(indices: np.ndarray, size: int) -> np.ndarray:
    return np.bincount(indices, minlength=size).astype(np.float64) / len(indices)


def _rank_by_championship_order(
    points: np.ndarray, wins: np.ndarray, podiums: np.ndarray
) -> np.ndarray:
    """Order entities per iteration by points, then the F1 countback.

    Ties on points are broken by most wins, then most podiums, matching the
    sporting regulations. The final tiebreak is the entity's own index, purely so
    the result is deterministic rather than dependent on sort stability.

    Returns an (N, E) array of entity indices, best first.
    """
    n_iterations, n_entities = points.shape
    index = np.broadcast_to(np.arange(n_entities), (n_iterations, n_entities))
    # np.lexsort takes keys in increasing priority order, so the primary key goes
    # last. Negated because lexsort is ascending and we want the best first.
    order = np.lexsort((index, -podiums, -wins, -points), axis=-1)
    return order


def _simulate_entity(
    events: SeasonEventSet,
    entity: str,
    metrics: tuple[str, ...],
    counts: np.ndarray,
    target_races: int,
) -> EntitySimResult:
    totals = {metric: counts @ events.matrix(entity, metric) for metric in metrics}

    # Season standings use the points the app treats as canonical, which include
    # sprint points — those were part of the championship in the years they ran.
    standings_points = totals["points"] + totals["sprint_points"]
    order = _rank_by_championship_order(standings_points, totals["wins"], totals["podiums"])

    n_entities = len(events.ids(entity))
    return EntitySimResult(
        entity=entity,
        ids=events.ids(entity),
        totals=totals,
        actual={metric: events.actual(entity, metric) for metric in metrics},
        scaled={metric: events.scaled(entity, metric, target_races) for metric in metrics},
        champion_index=order[:, 0],
        runner_up_index=order[:, 1] if n_entities > 1 else order[:, 0],
        third_index=order[:, 2] if n_entities > 2 else order[:, 0],
    )


def simulate_season(
    events: SeasonEventSet,
    *,
    master_seed: int,
    n_iterations: int = DEFAULT_ITERATIONS,
    target_races: int = DEFAULT_TARGET_RACES,
) -> SeasonSimResult:
    """Bootstrap one season out to `target_races` weekends.

    Seasons that already ran the target length are still resampled rather than
    passed through: the question "what would 24 races have produced" has spread
    even when 24 were actually run, and answering it consistently across every
    season is what makes the leaderboards comparable.
    """
    if events.n_races < 1:
        raise ValueError(f"Season {events.year} has no races to resample")

    rng = season_generator(master_seed, events.year)
    probabilities = np.full(events.n_races, 1.0 / events.n_races)
    counts = rng.multinomial(target_races, probabilities, size=n_iterations).astype(np.float32)

    return SeasonSimResult(
        year=events.year,
        n_races=events.n_races,
        target_races=target_races,
        n_iterations=n_iterations,
        driver=_simulate_entity(events, "driver", DRIVER_METRICS, counts, target_races),
        constructor=_simulate_entity(
            events, "constructor", CONSTRUCTOR_METRICS, counts, target_races
        ),
    )


def summarise(draws: np.ndarray) -> dict[str, np.ndarray]:
    """Mean, median, 95% interval and spread across iterations.

    `draws` is (N, E); every returned array is (E,).
    """
    percentiles = np.percentile(draws, [2.5, 50.0, 97.5], axis=0)
    return {
        "mean": draws.mean(axis=0),
        "median": percentiles[1],
        "p2_5": percentiles[0],
        "p97_5": percentiles[2],
        "std": draws.std(axis=0),
    }
