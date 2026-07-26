"""Continue a season instead of resampling it.

The bootstrap in `app.sim.bootstrap` asks: *if this season's 24 races were drawn
from the form it actually showed, what would the totals be?* That is the right
question for career leaderboards, and its expected value is exactly
`actual x 24/R` — which is also its limitation. Scaling a season preserves the
championship margin. The leader stays the leader and simply wins by more, and a
title only changes hands through resampling noise or through the modern points
system.

This module asks the other question: *the season stopped at race R because the
calendar ran out, not because anything was settled — so what if it had kept
going?* The R races that happened are kept exactly as they happened. The
remaining `24 - R` are raced.

Which means the answer depends on **who was quick at the end**, not on who
averaged best across the year. A driver who spent the first half in a broken car
and the second half winning carries that form into the extra races; a driver who
built a lead early and faded loses it. That is the sense in which this is a
momentum model — not a claim that winning is psychologically self-sustaining,
but the ordinary observation that recent races predict the next race better than
old ones do.

How a single extra race is produced:

1. **Who enters.** Each driver starts with the probability they started a race
   that season, so a driver who did three rounds of ten does not suddenly appear
   at every remaining one.
2. **Who finishes.** A Bernoulli draw on their retirement rate that season.
   Reliability is part of a championship and pretending otherwise would flatter
   fragile cars.
3. **What order.** Sampled from a Plackett-Luce model over per-driver strengths
   fitted to that season's finishing orders, with races weighted by recency —
   see `fit_strengths`.
4. **Points.** The modern system, exactly as the rest of the app scores.

The order model is Plackett-Luce, sampled by the Gumbel-max trick: adding
independent Gumbel noise to each log-strength and sorting descending yields
*exactly* a Plackett-Luce ordering — the same distribution as drawing finishers
one at a time in proportion to remaining strength, but vectorised over every
iteration and race at once instead of looped.

The strengths are themselves uncertain, and the model says so: they are refitted
on bootstrap resamples of the season and each simulated championship draws one
fit. Without that the odds are badly overconfident — the model would know
exactly how quick everyone was and only roll dice on race results.

Pure numpy, no database imports, in line with the rest of `app/sim`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.sim.scoring import MODERN_POINTS

#: Races after which a result carries half the weight it did when new. Five is
#: roughly a third of a 1970s season and a fifth of a modern one, which is a
#: deliberate compromise: short seasons should not be fitted almost entirely to
#: their last two races.
DEFAULT_HALF_LIFE = 5.0

#: Strength of the shrinkage prior, in synthetic races. Each driver is given this
#: many notional wins and losses against a reference of average strength, so an
#: undefeated driver's fitted strength stays finite and a stand-in with one start
#: cannot out-rate a season-long front-runner.
#:
#: Calibrated rather than guessed. At 0.5 a driver who beat the championship
#: leader in their only race outrates them more than two to one, and a dominant
#: car is fitted at 1,150x a backmarker — an estimate the evidence does not
#: support. Two synthetic races is the smallest value that orders a one-start
#: driver below a full season, and it still leaves roughly a 95x spread between
#: the best and worst cars in a dominant year, with recent form still able to
#: overturn a raw win record.
PRIOR_RACES = 2.0

#: Fixed-point iterations for the Plackett-Luce fit. The MM algorithm converges
#: monotonically; 200 is far past the point where the ordering stops changing.
FIT_ITERATIONS = 200


@dataclass(frozen=True)
class SeasonForm:
    """Everything the continuation needs about a season that has been run."""

    year: int
    n_races: int
    driver_ids: np.ndarray  # (D,)
    #: Championship points already banked, on the modern scale. (D,)
    points: np.ndarray
    #: Wins, podiums and poles already banked, carried forward unchanged. (D,)
    wins: np.ndarray
    podiums: np.ndarray
    #: Fitted per-driver strengths for the Plackett-Luce order model, as an
    #: ensemble of (B, D) — one row per bootstrap refit of the season. Drawing a
    #: row per iteration carries the uncertainty in the *estimate* into the
    #: result, instead of treating one fit as the truth. A single-row ensemble is
    #: accepted and simply means that uncertainty is ignored.
    strength: np.ndarray
    #: P(this driver starts any given race). (D,)
    entry_rate: np.ndarray
    #: P(retirement | started). (D,)
    dnf_rate: np.ndarray


def recency_weights(n_races: int, half_life: float = DEFAULT_HALF_LIFE) -> np.ndarray:
    """Weight per race, oldest first, halving every `half_life` races.

    Normalised to average 1.0 so the prior's strength stays comparable across
    seasons of very different lengths.
    """
    if n_races <= 0:
        return np.zeros(0)
    age = np.arange(n_races - 1, -1, -1, dtype=float)
    weights = 0.5 ** (age / half_life)
    return weights / weights.mean()


def fit_strengths(
    orderings: list[np.ndarray],
    weights: np.ndarray,
    n_drivers: int,
    *,
    iterations: int = FIT_ITERATIONS,
    prior: float = PRIOR_RACES,
) -> np.ndarray:
    """Fit Plackett-Luce strengths to weighted finishing orders.

    `orderings[r]` holds driver indices for race r, best finisher first, and
    covers classified finishers only — a retirement is not evidence about pace,
    and is modelled separately as a reliability draw.

    Fitted by Hunter's MM algorithm, which is the standard maximum-likelihood
    routine for this model and converges monotonically from any positive start.
    Each race contributes in proportion to `weights[r]`, which is what makes the
    fit favour recent form.

    A reference competitor of fixed strength is appended, and every driver is
    given `prior` notional wins and losses against it. Without that an undefeated
    driver has unbounded likelihood — 1955 Mercedes would be assigned infinite
    strength — and a two-start driver who finished ahead of one car would outrank
    a season-long front-runner.
    """
    reference = n_drivers  # a competitor of fixed, average strength
    pad = n_drivers + 1  # sentinel slot, held at zero strength
    n = n_drivers + 2

    races: list[np.ndarray] = [o for o in orderings if len(o) >= 2]
    race_weights = [
        w for o, w in zip(orderings, np.asarray(weights, dtype=float)) if len(o) >= 2
    ]
    for driver in range(n_drivers):
        races.append(np.array([driver, reference]))
        race_weights.append(prior)
        races.append(np.array([reference, driver]))
        race_weights.append(prior)

    weight_vector = np.asarray(race_weights, dtype=float)
    n_races = len(races)
    widest = max(len(o) for o in races)

    # One padded (races x widest) matrix, so an MM iteration is a fixed handful
    # of array operations rather than a Python loop over races. Fitting is run
    # tens of times per season for the uncertainty ensemble, which makes the
    # difference between seconds and half an hour across the full history.
    grid = np.full((n_races, widest), pad, dtype=np.intp)
    sizes = np.empty(n_races, dtype=np.intp)
    for r, order in enumerate(races):
        grid[r, : len(order)] = order
        sizes[r] = len(order)

    stage = np.arange(widest)
    # A stage is a real choice only while at least two cars remain, so the last
    # position of each race contributes nothing — and neither does any padding.
    active = stage[None, :] < (sizes[:, None] - 1)

    # W[i]: weighted count of races where i is "chosen", i.e. placed anywhere
    # but last, since the final position involves no further choice.
    chosen = np.zeros(n)
    np.add.at(chosen, grid.ravel(), np.where(active, weight_vector[:, None], 0.0).ravel())

    gamma = np.ones(n)
    gamma[pad] = 0.0  # padding must not add to any tail sum
    for _ in range(iterations):
        # tail_sums[r, t] = total strength of everyone placed at or after t.
        tail_sums = np.cumsum(gamma[grid][:, ::-1], axis=1)[:, ::-1]
        contribution = np.where(active, weight_vector[:, None] / np.maximum(tail_sums, 1e-12), 0.0)
        # A driver placed at t was in contention for every stage up to t, so
        # their share is the running total. Zeroing inactive stages above is what
        # caps the last position correctly, with no special case.
        running = np.cumsum(contribution, axis=1)

        denominator = np.zeros(n)
        np.add.at(denominator, grid.ravel(), running.ravel())

        updated = np.where(denominator > 0, chosen / np.maximum(denominator, 1e-12), gamma)
        updated = np.maximum(updated, 1e-9)
        # The likelihood is scale-invariant; pinning the reference keeps the
        # numbers stable and comparable between seasons.
        gamma = updated / updated[reference]
        gamma[pad] = 0.0

    return gamma[:n_drivers]


#: Bootstrap refits used to estimate how uncertain the strengths themselves are.
DEFAULT_ENSEMBLE = 40


def fit_strength_ensemble(
    orderings: list[np.ndarray],
    weights: np.ndarray,
    n_drivers: int,
    *,
    rng: np.random.Generator,
    n_samples: int = DEFAULT_ENSEMBLE,
    **kwargs,
) -> np.ndarray:
    """Refit strengths on bootstrap resamples of the season. Returns (B, D).

    One fit treated as the truth makes the continuation badly overconfident: it
    knows exactly how quick everyone was and only rolls dice on race outcomes,
    which pushes a modest points lead to a 99%+ title. But a strength estimated
    from sixteen races is itself uncertain, and over a whole championship that
    uncertainty matters more than the race-to-race noise.

    So the season's races are resampled with replacement and refitted, and each
    simulated championship draws one row. The reported odds then span both "who
    wins these eight races" and "how sure are we who was actually quicker".

    The first row is always the fit on the season as it stands, so the ensemble
    is centred on the real record rather than on a resample of it.
    """
    orderings = list(orderings)
    weights = np.asarray(weights, dtype=float)
    rows = [fit_strengths(orderings, weights, n_drivers, **kwargs)]

    n_races = len(orderings)
    for _ in range(max(n_samples - 1, 0)):
        if n_races == 0:
            rows.append(rows[0])
            continue
        picks = rng.integers(0, n_races, size=n_races)
        rows.append(
            fit_strengths(
                [orderings[i] for i in picks], weights[picks], n_drivers, **kwargs
            )
        )
    return np.vstack(rows)


def simulate_continuation(
    form: SeasonForm,
    *,
    rng: np.random.Generator,
    n_iterations: int,
    target_races: int,
    points_table: tuple[int, ...] = MODERN_POINTS,
) -> dict[str, np.ndarray]:
    """Race out the remainder of a season, `n_iterations` times.

    Returns per-iteration totals: `points`, `wins` and `podiums`, each (N, D) and
    inclusive of what was already banked, plus `extra_races`.

    A season that already ran the full distance has nothing left to race, so
    every iteration returns exactly what happened. That is not a defect of the
    model — it is the honest answer to "what if it had kept going" for a season
    that did not stop early, and it is precisely why this cannot replace the
    bootstrap for cross-era leaderboards.
    """
    n_drivers = len(form.driver_ids)
    extra = max(target_races - form.n_races, 0)

    points = np.tile(form.points.astype(np.float64), (n_iterations, 1))
    wins = np.tile(form.wins.astype(np.float64), (n_iterations, 1))
    podiums = np.tile(form.podiums.astype(np.float64), (n_iterations, 1))

    if extra == 0 or n_drivers == 0:
        return {
            "points": points,
            "wins": wins,
            "podiums": podiums,
            "extra_races": np.full(n_iterations, extra),
        }

    shape = (n_iterations, extra)
    entered = rng.random(shape + (n_drivers,)) < form.entry_rate
    finished = entered & (rng.random(shape + (n_drivers,)) >= form.dnf_rate)

    # One strength row per simulated championship, so a season is raced out
    # under a single coherent view of who was quick rather than a fresh one each
    # race — the estimate is uncertain, not unstable.
    ensemble = np.atleast_2d(form.strength)
    drawn = ensemble[rng.integers(0, len(ensemble), size=n_iterations)]
    log_strength = np.log(np.maximum(drawn, 1e-12))[:, None, :]

    gumbel = rng.gumbel(size=shape + (n_drivers,))
    keys = log_strength + gumbel
    # Anyone who did not take the flag cannot be classified, so they are pushed
    # below every finisher rather than removed — which keeps the array shape.
    keys = np.where(finished, keys, -np.inf)

    # Rank 0 is the winner. argsort of argsort turns keys into positions.
    order = np.argsort(-keys, axis=-1, kind="stable")
    rank = np.argsort(order, axis=-1, kind="stable")

    # A grid smaller than the points table scores only as far as it reaches.
    scoring = np.zeros(n_drivers)
    payable = min(len(points_table), n_drivers)
    scoring[:payable] = points_table[:payable]
    awarded = np.where(finished, scoring[rank], 0.0)

    points += awarded.sum(axis=1)
    wins += (finished & (rank == 0)).sum(axis=1)
    podiums += (finished & (rank < 3)).sum(axis=1)

    return {
        "points": points,
        "wins": wins,
        "podiums": podiums,
        "extra_races": np.full(n_iterations, extra),
    }


def champion_probability(
    points: np.ndarray, wins: np.ndarray, podiums: np.ndarray
) -> np.ndarray:
    """P(title) per driver, under the championship countback.

    Ties on points are broken by wins, then podiums — the sporting regulations,
    and the same order `app.sim.bootstrap` applies.
    """
    n_iterations, n_drivers = points.shape
    index = np.broadcast_to(np.arange(n_drivers), (n_iterations, n_drivers))
    order = np.lexsort((index, -podiums, -wins, -points), axis=-1)
    champions = order[:, 0]
    return np.bincount(champions, minlength=n_drivers) / n_iterations
