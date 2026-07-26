"""Elo ratings for F1 drivers, and the win-difficulty measure derived from them.

The 24-race bootstrap answers "how many wins would this driver have had with a
modern calendar". It deliberately says nothing about *who they had to beat* — a
win is a win whether it came against Fangio or against an empty road. This module
supplies the missing half.

Two ratings are produced, and the difference between them is the point:

- `overall` rates the **entry** — driver and car together — from pairwise results
  against the whole field. It is what actually wins races, and it is the right
  input to "how hard was this win", because the field you beat is a field in
  cars, not a field of abstract talent.
- `teammate` rates the **driver**, from pairwise results against team-mates only.
  Same car, same strategy, same reliability lottery, so machinery very largely
  cancels. It is the fairer measure of a driver stuck in a bad car for a decade.

Neither is the truth on its own. A driver with a high teammate rating and a
middling overall rating spent their career dragging an uncompetitive car; the app
shows both columns side by side rather than pretending one number settles it.

A note on drift, because it decides how the numbers may be read. Elo is
zero-sum *within* a race but not across history: drivers enter on a fixed rating
and leave carrying whatever they earned, so the pool inflates as the sport grows.
Raw ratings therefore favour the modern era for reasons that have nothing to do
with driving, and a raw all-time table is mostly a list of who raced recently.
Two things follow. Difficulty is immune, since it depends only on rating
*differences inside a single race*. Cross-era rating comparisons are not, so they
use `rating_vs_field` — a driver's margin over the mean rating of the field they
lined up against — which is drift-free by construction.

Pure numpy and stdlib — no database imports, in line with the rest of `app/sim`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Rating everyone enters the sport on. Arbitrary; only differences carry meaning.
INITIAL_RATING = 1500.0

#: Logistic scale. 400 is the chess convention: a 400-point edge implies winning
#: a pairwise comparison about 91% of the time.
RATING_SCALE = 400.0

#: Movement per race. A race is scored as one game's worth of K regardless of how
#: many cars were classified, so a 20-car field does not move ratings twenty times
#: faster than a 6-car one — see `_pairwise_delta`.
K_FACTOR = 24.0

#: Larger K while a driver is still being placed. Without this a genuinely quick
#: newcomer spends two seasons climbing out of the default rating, and the races
#: they win on the way look far harder than they were.
PROVISIONAL_K = 40.0
PROVISIONAL_RACES = 10

#: Team-mate comparisons are rarer (one per race at most) but much less noisy,
#: since the machinery is shared. A higher K keeps the rating responsive.
TEAMMATE_K_FACTOR = 32.0


@dataclass(frozen=True)
class RaceEntry:
    """One car in one race."""

    driver_id: int
    constructor_id: int | None
    #: Numeric finishing position, or None if the car was not classified. Only
    #: classified cars are compared: a blown engine is not a driver losing a duel.
    position: int | None


@dataclass(frozen=True)
class Race:
    """One race, in the order it should be rated."""

    race_id: int
    year: int
    round: int
    entries: tuple[RaceEntry, ...]


@dataclass
class RatingSnapshot:
    """A driver's ratings going into a race, and the change the race produced."""

    race_id: int
    year: int
    driver_id: int
    rating_before: float
    rating_after: float
    teammate_rating_before: float
    teammate_rating_after: float
    #: Where the pre-race ratings expected this driver to finish. See
    #: `expected_positions`.
    expected_position: float
    #: Rating measured against the mean rating of this race's field. Raw Elo
    #: drifts upward across eras (see `rating_vs_field` in the module docstring),
    #: so cross-era comparisons use this instead.
    rating_vs_field: float
    #: Numeric finishing position, or None if not classified.
    position: int | None


@dataclass
class EloResult:
    snapshots: list[RatingSnapshot] = field(default_factory=list)
    #: driver_id -> final rating after their last race.
    final: dict[int, float] = field(default_factory=dict)
    final_teammate: dict[int, float] = field(default_factory=dict)


def expected_score(rating: np.ndarray, opponent: np.ndarray) -> np.ndarray:
    """Probability that `rating` finishes ahead of `opponent`, pairwise."""
    return 1.0 / (1.0 + np.power(10.0, (opponent - rating) / RATING_SCALE))


def expected_positions(ratings: np.ndarray) -> np.ndarray:
    """Expected finishing position for each car, given the field's ratings.

    A car's expected position is one plus the number of rivals expected to beat
    it: `1 + sum_j P(j ahead of i)`. This is the whole difficulty measure in one
    line. A driver whose rating towers over the field is expected to finish first
    and gains little credit for doing so; a driver expected to finish eighth who
    wins anyway beat a field that had every reason to beat them.

    Note this is an expectation over *starters*, so a rival who later retired
    still counts toward the difficulty of the race — they were part of what had
    to be beaten when the lights went out.
    """
    # beats[i, j] = P(j finishes ahead of i)
    beats = expected_score(ratings[None, :], ratings[:, None])
    np.fill_diagonal(beats, 0.0)
    return 1.0 + beats.sum(axis=1)


def _pairwise_delta(
    ratings: np.ndarray, positions: np.ndarray, k: np.ndarray, mask: np.ndarray
) -> np.ndarray:
    """Elo change for every car in one race, from all pairwise comparisons.

    `mask[i, j]` selects which pairs are compared at all — the full field for the
    overall rating, team-mates only for the team-mate rating.

    The sum of (actual - expected) over a driver's comparisons is divided by the
    number of comparisons they took part in, so the race is worth one game of K
    rather than one per rival. Without that, ratings would swing three times
    harder in a 24-car field than a 8-car one for no sporting reason.
    """
    n = len(ratings)
    if n < 2:
        return np.zeros(n)

    expected = expected_score(ratings[:, None], ratings[None, :])

    # actual[i, j] = 1 where i finished ahead of j, 0 behind, 0.5 for a dead heat
    # (which the source data does not contain, but the symmetry costs nothing).
    ahead = positions[:, None] < positions[None, :]
    behind = positions[:, None] > positions[None, :]
    actual = np.where(ahead, 1.0, np.where(behind, 0.0, 0.5))

    comparisons = mask.sum(axis=1)
    delta = np.where(
        comparisons > 0,
        k * ((actual - expected) * mask).sum(axis=1) / np.maximum(comparisons, 1),
        0.0,
    )
    return delta


def _teammate_mask(constructor_ids: list[int | None], classified: np.ndarray) -> np.ndarray:
    """Pairs sharing a constructor, both classified, excluding self-pairs."""
    ids = np.array([-1 if c is None else int(c) for c in constructor_ids])
    same = (ids[:, None] == ids[None, :]) & (ids[:, None] >= 0)
    np.fill_diagonal(same, False)
    return same & classified[:, None] & classified[None, :]


def rate(
    races: list[Race],
    *,
    k_factor: float = K_FACTOR,
    teammate_k_factor: float = TEAMMATE_K_FACTOR,
    provisional_k: float = PROVISIONAL_K,
    provisional_races: int = PROVISIONAL_RACES,
    priors: dict[int, float] | None = None,
    teammate_priors: dict[int, float] | None = None,
) -> EloResult:
    """Rate every driver over `races`, which must already be in calendar order.

    `priors` supplies a starting rating per driver; anyone absent starts at
    `INITIAL_RATING`. `rate_with_priors` uses this to run a second pass, which is
    what removes the cold-start distortion from the earliest seasons.
    """
    ratings: dict[int, float] = dict(priors or {})
    teammate_ratings: dict[int, float] = dict(teammate_priors or {})
    starts: dict[int, int] = {}
    result = EloResult()

    for race in races:
        drivers = [e.driver_id for e in race.entries]
        if len(drivers) < 2:
            continue

        current = np.array([ratings.setdefault(d, INITIAL_RATING) for d in drivers])
        current_tm = np.array(
            [teammate_ratings.setdefault(d, INITIAL_RATING) for d in drivers]
        )

        # Not-classified cars are parked at a position behind every finisher so
        # the comparison matrix is well formed; the mask then drops them.
        positions = np.array(
            [len(drivers) + 1 if e.position is None else e.position for e in race.entries],
            dtype=float,
        )
        classified = np.array([e.position is not None for e in race.entries])

        k = np.array(
            [
                provisional_k if starts.get(d, 0) < provisional_races else k_factor
                for d in drivers
            ]
        )

        field_mask = classified[:, None] & classified[None, :]
        np.fill_diagonal(field_mask, False)
        delta = _pairwise_delta(current, positions, k, field_mask)

        tm_mask = _teammate_mask([e.constructor_id for e in race.entries], classified)
        delta_tm = _pairwise_delta(
            current_tm, positions, np.full(len(drivers), teammate_k_factor), tm_mask
        )

        # Difficulty is measured on the ratings carried *into* the race, so a
        # win never gets credit from the rating it itself produced.
        expected_pos = expected_positions(current)
        field_mean = float(current.mean())

        for i, entry in enumerate(race.entries):
            result.snapshots.append(
                RatingSnapshot(
                    race_id=race.race_id,
                    year=race.year,
                    driver_id=entry.driver_id,
                    rating_before=float(current[i]),
                    rating_after=float(current[i] + delta[i]),
                    teammate_rating_before=float(current_tm[i]),
                    teammate_rating_after=float(current_tm[i] + delta_tm[i]),
                    expected_position=float(expected_pos[i]),
                    rating_vs_field=float(current[i] - field_mean),
                    position=entry.position,
                )
            )
            ratings[entry.driver_id] = float(current[i] + delta[i])
            teammate_ratings[entry.driver_id] = float(current_tm[i] + delta_tm[i])
            starts[entry.driver_id] = starts.get(entry.driver_id, 0) + 1

    result.final = ratings
    result.final_teammate = teammate_ratings
    return result


def rate_with_priors(races: list[Race], *, passes: int = 2, **kwargs) -> EloResult:
    """Rate the field, seeding each driver from a previous pass over the same data.

    A single pass starts everyone at 1500, which is badly wrong for 1950: the
    entire grid is rated identically, every car is expected to finish mid-pack,
    and so every early-fifties win scores as heroically difficult purely because
    the model had not met anyone yet. That is an artefact of the initialisation,
    not a fact about the era.

    The fix is to run the history once, take each driver's rating at the end of
    their *first season* as a data-driven estimate of the level they entered on,
    and replay from there. Later passes change the earliest seasons a lot and the
    modern ones barely at all, which is exactly the intended shape.

    This does mean a 1950 race is rated using information from later seasons. For
    a rating that is the right call — we want the best available estimate of how
    good those drivers were, not a deliberately naive one — but it is disclosed
    alongside the figures rather than buried here.
    """
    result = rate(races, **kwargs)
    for _ in range(passes - 1):
        result = rate(
            races,
            priors=_first_season_ratings(result, "rating_after"),
            teammate_priors=_first_season_ratings(result, "teammate_rating_after"),
            **kwargs,
        )
    return result


def _first_season_ratings(result: EloResult, attribute: str) -> dict[int, float]:
    """Each driver's rating at the end of the first season they appeared in."""
    first_year: dict[int, int] = {}
    latest: dict[int, float] = {}
    for snapshot in result.snapshots:
        driver = snapshot.driver_id
        if driver not in first_year:
            first_year[driver] = snapshot.year
        if snapshot.year == first_year[driver]:
            latest[driver] = getattr(snapshot, attribute)
    return latest


def win_difficulty(snapshots: list[RatingSnapshot]) -> dict[tuple[int, int], float]:
    """Difficulty credit for every race win, normalised so the mean win is 1.0.

    A win's raw difficulty is the winner's expected finishing position: beating a
    field that was expected to beat you scores higher than converting from a
    position the ratings already handed you. Dividing through by the mean across
    every win in history puts the result on the same scale as raw wins, so
    "quality-adjusted wins" and "wins" are directly comparable and a driver whose
    wins were all of average difficulty scores exactly their win count.

    Returns {(race_id, driver_id): credit} for winners only.
    """
    winners = [s for s in snapshots if s.position == 1]
    if not winners:
        return {}

    mean_difficulty = float(np.mean([s.expected_position for s in winners]))
    if mean_difficulty <= 0:
        return {}

    return {
        (s.race_id, s.driver_id): s.expected_position / mean_difficulty for s in winners
    }


#: Races averaged over when locating a career peak. A single race's rating is
#: noisy — one wet afternoon can spike it — so the peak is the best *sustained*
#: level rather than the highest instant.
PEAK_WINDOW = 10


def _rolling_peak(values: list[float], window: int) -> float:
    """Highest mean over any `window` consecutive entries."""
    if len(values) <= window:
        return float(np.mean(values)) if values else 0.0
    array = np.asarray(values, dtype=float)
    cumulative = np.concatenate(([0.0], np.cumsum(array)))
    means = (cumulative[window:] - cumulative[:-window]) / window
    return float(means.max())


def peak_ratings(
    snapshots: list[RatingSnapshot],
    *,
    min_races: int = PROVISIONAL_RACES,
    window: int = PEAK_WINDOW,
) -> dict[int, dict[str, float]]:
    """Career peak, final and margin-over-field ratings per driver.

    Peaks skip a driver's first `min_races` races, where the rating is still
    provisional and its swings say more about the initialisation than the driver,
    and are taken over a rolling window so a single result cannot define a career.

    `peak_vs_field` is the one to rank eras against each other on; `peak` inflates
    with time, for the reason set out in the module docstring.
    """
    by_driver: dict[int, list[RatingSnapshot]] = {}
    for snapshot in snapshots:
        by_driver.setdefault(snapshot.driver_id, []).append(snapshot)

    out: dict[int, dict[str, float]] = {}
    for driver, items in by_driver.items():
        settled = items[min_races:] or items[-1:]
        out[driver] = {
            "peak": _rolling_peak([s.rating_after for s in settled], window),
            "peak_teammate": _rolling_peak([s.teammate_rating_after for s in settled], window),
            "peak_vs_field": _rolling_peak([s.rating_vs_field for s in settled], window),
            "final": items[-1].rating_after,
            "final_teammate": items[-1].teammate_rating_after,
            "races": float(len(items)),
        }
    return out
