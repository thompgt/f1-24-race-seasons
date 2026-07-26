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


@dataclass(frozen=True)
class FormDynamics:
    """How a driver's pace moves from one simulated race to the next.

    Holding strength fixed across the whole continuation says that whoever was
    quickest at the end of the season stays exactly that quick for every
    remaining race. That is the assumption which makes a points lead close to
    unassailable: with pace frozen, the only thing left to vary is race noise,
    and eight races of race noise are not enough to overturn seventy points. It
    is also plainly false — 1989 fits Senna *faster* than Prost and still gives
    him one title in 250, because his form is never allowed to turn into a run.

    So pace is carried as a state instead. Each driver has a deviation from
    their fitted anchor which evolves race by race:

        dev <- persistence x dev  +  momentum x surprise  +  volatility x noise

    and their strength for the next race is `anchor x exp(dev)`.

    The three terms are three distinct claims, each separately calibrated in
    `scripts/calibrate_form.py` against the real history rather than assumed:

    - `volatility` — pace genuinely wanders. Cars are developed, tracks suit
      different machinery, and a fit from sixteen races does not pin next
      Sunday to a point.
    - `persistence` — that wandering is correlated. Being quick in Belgium says
      more about Italy than about a race half a season away, which is the same
      observation that motivates the recency-weighted fit, applied forwards.
    - `momentum` — a result better than a driver's own norm feeds back into
      their next race. This is the only term that is a substantive claim about
      streaks rather than about uncertainty, and it is the one the calibration
      is most sceptical of: it is measured as the residual predictive power of
      recent over-performance *after* fitted strength is accounted for.

    Together they mean the extra races are not eight draws from one fixed
    distribution but a sequence in which the odds move — a chaser can find a
    run, and a leader can lose one. Reversion is what keeps that honest: a
    purple patch decays back towards the anchor rather than compounding without
    limit, so the model finds drama where the season left room for it and not
    otherwise.
    """

    #: Fraction of a form deviation carried into the next race. 0 forgets each
    #: race, 1 makes a deviation permanent.
    persistence: float = 0.0
    #: Standard deviation of the per-race innovation, in log-strength.
    volatility: float = 0.0
    #: Sensitivity to beating one's own expected result. In log-strength per
    #: unit of beat-fraction surprise, which ranges over [-1, 1].
    momentum: float = 0.0
    #: Hard cap on |dev|, in log-strength. Guards against a compounding streak
    #: running away in the tail of ten thousand iterations; at the calibrated
    #: settings it binds on well under one draw in a thousand.
    band: float = 2.5

    @property
    def is_static(self) -> bool:
        """True when this reduces to holding strength fixed all the way."""
        return self.volatility == 0.0 and self.momentum == 0.0


#: Pace frozen at the fitted anchor — the behaviour before form was modelled as
#: a state. Kept as a named baseline so tests and the calibration can measure
#: against it.
STATIC_FORM = FormDynamics()


def expected_beat_fraction(
    strength: np.ndarray, entry_rate: np.ndarray | None = None
) -> np.ndarray:
    """Each driver's expected share of rivals beaten, per strength row.

    Under Plackett-Luce the probability that i finishes ahead of j is
    `s_i / (s_i + s_j)`, so averaging over rivals gives the fraction of the
    field a driver should expect to beat. That is the reference the momentum
    term measures surprise against: doing better than *this* is a driver
    exceeding their own norm, not merely being quick.

    Rivals are weighted by `entry_rate` because the observed beat-fraction is
    taken over the drivers who actually entered. Averaging the expectation over
    the whole season's entry list instead would hold every regular to a
    standard set partly by part-timers who are rarely on the grid, and so hand
    the midfield a standing negative surprise.

    Returns (B, D) for a (B, D) input, or (D,) for (D,).
    """
    flat = np.atleast_2d(strength).astype(np.float64)
    rows, n_drivers = flat.shape
    if n_drivers < 2:
        result = np.zeros_like(flat)
        return result if strength.ndim > 1 else result[0]

    weights = (
        np.ones(n_drivers)
        if entry_rate is None
        else np.asarray(entry_rate, dtype=np.float64)
    )

    safe = np.maximum(flat, 1e-12)
    # pairwise[b, i, j] = P(i beats j). The diagonal is a self-comparison at
    # exactly 0.5 and is subtracted back out rather than masked, which keeps
    # this to one broadcast instead of a per-driver loop.
    pairwise = safe[:, :, None] / (safe[:, :, None] + safe[:, None, :])
    totals = (pairwise * weights[None, None, :]).sum(axis=2) - 0.5 * weights[None, :]
    divisor = np.maximum(weights.sum() - weights, 1e-12)

    result = totals / divisor[None, :]
    return result if strength.ndim > 1 else result[0]


def _draw_rows(
    values: np.ndarray, picks: np.ndarray, n_drivers: int
) -> np.ndarray:
    """Expand a (D,) constant or a (B, D) ensemble to one row per iteration."""
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 1:
        return np.broadcast_to(array, (len(picks), n_drivers))
    return array[picks]


def simulate_continuation(
    form: SeasonForm,
    *,
    rng: np.random.Generator,
    n_iterations: int,
    target_races: int,
    points_table: tuple[int, ...] = MODERN_POINTS,
    dynamics: FormDynamics = STATIC_FORM,
) -> dict[str, np.ndarray]:
    """Race out the remainder of a season, `n_iterations` times.

    Returns per-iteration totals: `points`, `wins` and `podiums`, each (N, D)
    and inclusive of what was already banked, plus `extra_races` and
    `lead_share` — the fraction of iterations each driver leads the standings
    after each extra race, which is the race-by-race path of the title fight
    rather than only its endpoint.

    The extra races are run one at a time, in order, because `dynamics` makes
    each one depend on the last: form is a state that the previous result
    updates. With the default `STATIC_FORM` the state never moves and this
    reduces to sampling every remaining race from one fixed set of strengths.

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
            "lead_share": _lead_share(points, wins, podiums)[None, :],
        }

    # One row per simulated championship, so a season is raced out under a
    # single coherent view of who was quick rather than a fresh one each race —
    # the estimate is uncertain, not unstable. Reliability and entry are drawn
    # on the same index as strength where they are given as ensembles, so an
    # iteration sees one self-consistent version of the season.
    ensemble = np.atleast_2d(form.strength)
    picks = rng.integers(0, len(ensemble), size=n_iterations)
    anchor = np.log(np.maximum(ensemble[picks], 1e-12))
    entry_rate = _draw_rows(form.entry_rate, picks, n_drivers)
    dnf_rate = _draw_rows(form.dnf_rate, picks, n_drivers)

    # The driver's own norm, held fixed at the anchor: surprise is measured
    # against how they were expected to do all along, not against a target that
    # chases their recent results and so can never be beaten twice running.
    norm = expected_beat_fraction(ensemble, np.atleast_2d(form.entry_rate).mean(axis=0))[picks]

    # A grid smaller than the points table scores only as far as it reaches.
    scoring = np.zeros(n_drivers)
    payable = min(len(points_table), n_drivers)
    scoring[:payable] = points_table[:payable]

    deviation = np.zeros((n_iterations, n_drivers))
    lead_share = np.empty((extra + 1, n_drivers))
    lead_share[0] = _lead_share(points, wins, podiums)

    for race in range(extra):
        entered = rng.random((n_iterations, n_drivers)) < entry_rate
        finished = entered & (rng.random((n_iterations, n_drivers)) >= dnf_rate)

        keys = anchor + deviation + rng.gumbel(size=(n_iterations, n_drivers))
        # Anyone who did not take the flag cannot be classified, so they are
        # pushed below every finisher rather than removed — which keeps the
        # array shape.
        keys = np.where(finished, keys, -np.inf)

        # Rank 0 is the winner. argsort of argsort turns keys into positions.
        order = np.argsort(-keys, axis=-1, kind="stable")
        rank = np.argsort(order, axis=-1, kind="stable")

        points += np.where(finished, scoring[rank], 0.0)
        wins += finished & (rank == 0)
        podiums += finished & (rank < 3)

        lead_share[race + 1] = _lead_share(points, wins, podiums)

        if race + 1 == extra:
            break  # nothing left for the updated form to act on
        deviation = _advance_form(
            deviation, rank, finished, norm, dynamics=dynamics, rng=rng
        )

    return {
        "points": points,
        "wins": wins,
        "podiums": podiums,
        "extra_races": np.full(n_iterations, extra),
        "lead_share": lead_share,
    }


def _advance_form(
    deviation: np.ndarray,
    rank: np.ndarray,
    finished: np.ndarray,
    norm: np.ndarray,
    *,
    dynamics: FormDynamics,
    rng: np.random.Generator,
) -> np.ndarray:
    """One step of the form process, given how the race just run turned out."""
    if dynamics.is_static:
        return deviation * dynamics.persistence

    updated = deviation * dynamics.persistence

    if dynamics.momentum:
        # Observed share of the classified field beaten. Only finishers update:
        # a retirement is not evidence about pace, which is the same rule the
        # strength fit applies to the races that actually happened.
        n_finishers = finished.sum(axis=1, keepdims=True)
        beat = np.where(
            n_finishers > 1,
            (n_finishers - 1 - rank) / np.maximum(n_finishers - 1, 1),
            0.5,
        )
        surprise = np.where(finished, beat - norm, 0.0)
        updated = updated + dynamics.momentum * surprise

    if dynamics.volatility:
        updated = updated + dynamics.volatility * rng.standard_normal(deviation.shape)

    return np.clip(updated, -dynamics.band, dynamics.band)


def _lead_share(
    points: np.ndarray, wins: np.ndarray, podiums: np.ndarray
) -> np.ndarray:
    """Fraction of iterations in which each driver heads the standings."""
    return champion_probability(points, wins, podiums)


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
