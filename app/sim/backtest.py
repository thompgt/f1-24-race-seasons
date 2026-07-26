"""Score the form model against what actually happened next.

`app.sim.continuation` fits a driver's pace from the races behind them and then
races out the ones the calendar never got to. Every number in that model is a
claim about prediction — that recent races say more than old ones, that a fit
from sixteen races is uncertain, that pace drifts, that a run of results
carries. Each of those is checkable against seventy-five seasons of races the
fit did not see.

The method throughout is walk-forward. Cut a season after race k, fit strengths
on races 1..k only, and ask how well they order race k+h. Nothing downstream of
the cut informs the fit, so the score is honest out-of-sample prediction rather
than a measure of how well the fit describes races it was shown.

Everything is scored on **pairs**. For two drivers both classified in the target
race, the model says the quicker finishes ahead with probability
`s_i / (s_i + s_j)` — equivalently `sigmoid(log s_i - log s_j)`. Pairs are the
natural unit because they are comparable across eras: a 1950 grid of thirty and
a 2021 grid of twenty produce pair outcomes on the same scale, where finishing
positions do not.

Two statistics matter, and they identify different parameters:

- **Hit rate and log-loss at h = 1** measure how well the fit describes current
  pace, which is what the recency half-life controls.
- **How the hit rate decays as h grows** measures how fast pace stops being
  current — which is exactly what the drift terms in `FormDynamics` describe,
  and the reason they can be calibrated rather than chosen.

Pure numpy, no database imports, in line with the rest of `app/sim`.
"""

from __future__ import annotations

import numpy as np

from app.sim.continuation import FormDynamics

#: Nodes for the Gauss-Hermite quadrature used to average a logistic over
#: normal noise. Twenty is far more than the integrand's smoothness needs.
_QUADRATURE_NODES = 20


def race_pairs(ordering: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Every ordered pair of classified finishers, as (ahead, behind) indices.

    `ordering` is driver indices, best finisher first — the same convention as
    `fit_strengths`. The result always reads "the first beat the second", so an
    upset shows up as a negative strength difference rather than as a zero
    outcome, and both statistics below are one-sided in the same way.
    """
    order = np.asarray(ordering)
    if len(order) < 2:
        empty = np.empty(0, dtype=np.intp)
        return empty, empty
    ahead, behind = np.triu_indices(len(order), k=1)
    return order[ahead], order[behind]


def pair_margins(log_strength: np.ndarray, ordering: np.ndarray) -> np.ndarray:
    """Fitted log-strength advantage of the driver who actually finished ahead.

    Positive is a call the model got right, negative an upset, and the
    magnitude is how confident it was. Both `pair_hit_rate` and `pair_log_loss`
    are functions of this one vector.
    """
    ahead, behind = race_pairs(ordering)
    if len(ahead) == 0:
        return np.empty(0)
    return np.asarray(log_strength)[ahead] - np.asarray(log_strength)[behind]


def pair_hit_rate(margins: np.ndarray) -> float:
    """Share of pairs the model ordered correctly. Ties count as a half."""
    if len(margins) == 0:
        return float("nan")
    return float((margins > 0).mean() + 0.5 * (margins == 0).mean())


def pair_log_loss(margins: np.ndarray, spread: float = 0.0) -> float:
    """Mean negative log probability the model gave to what happened.

    `spread` is the standard deviation of the *difference* in unmodelled form
    between the two drivers, so a model that admits pace has drifted since the
    fit is scored on the wider probability it actually asserts. At `spread = 0`
    this is the plain Plackett-Luce likelihood of each pair.

    Log-loss rather than hit rate is what the half-life is chosen on: hit rate
    is blind to confidence, and a fit that is right slightly more often while
    being wildly overconfident is not the better description of a season.
    """
    if len(margins) == 0:
        return float("nan")
    return float(-np.log(np.maximum(pair_win_probability(margins, spread), 1e-12)).mean())


def pair_win_probability(margins: np.ndarray, spread: float = 0.0) -> np.ndarray:
    """P(the stronger-by-`margins` driver finishes ahead), given drift.

    With no drift this is the logistic of the margin, which is the
    Plackett-Luce pairwise probability. With drift the margin is itself
    uncertain by `spread`, and the answer is the logistic averaged over that
    normal — computed by Gauss-Hermite quadrature, since no closed form exists.

    Drift always pulls the probability towards a coin flip, which is the whole
    content of the drift terms: the further ahead you ask, the less a fitted
    advantage is worth.
    """
    margins = np.asarray(margins, dtype=np.float64)
    if spread <= 0:
        return _sigmoid(margins)

    nodes, weights = np.polynomial.hermite_e.hermegauss(_QUADRATURE_NODES)
    # hermegauss integrates against exp(-x^2/2), so weights normalise by sqrt(2 pi)
    # and the nodes are already in standard-normal units.
    shifted = margins[:, None] + spread * nodes[None, :]
    return (_sigmoid(shifted) * weights[None, :]).sum(axis=1) / np.sqrt(2 * np.pi)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))


def drift_spread(dynamics: FormDynamics, horizon: int) -> float:
    """Standard deviation of the *gap* in accumulated form drift after h races.

    The deviation process is an AR(1) started from zero, so after h steps its
    variance is the geometric sum `v^2 (1 - p^{2h}) / (1 - p^2)`. Two drivers
    drift independently, so the variance of the difference between them is
    twice that — and it is the difference, not the level, that moves a pairwise
    probability.

    At `persistence = 1` the sum degenerates to a random walk, `h v^2`, which is
    the correct limit and not a special case worth avoiding.
    """
    if horizon <= 0 or dynamics.volatility <= 0:
        return 0.0
    p, v = dynamics.persistence, dynamics.volatility
    if abs(p) >= 1.0:
        variance = horizon * v * v
    else:
        variance = v * v * (1.0 - p ** (2 * horizon)) / (1.0 - p * p)
    return float(np.sqrt(2.0 * variance))


def recent_surprise(
    orderings: list[np.ndarray],
    expected: np.ndarray,
    n_drivers: int,
    *,
    persistence: float,
) -> np.ndarray:
    """Each driver's accumulated over-performance going into the next race.

    Replays the momentum term of `FormDynamics` over races that really
    happened: a driver who beat more of the field than `expected` gains, the
    total decays by `persistence` each race, and a driver absent from a race is
    carried unchanged. The result is the deviation the simulator would be
    holding at the cut, up to the momentum coefficient itself — which is what
    lets that coefficient be estimated by asking whether this vector predicts
    the next race at all.
    """
    deviation = np.zeros(n_drivers)
    for ordering in orderings:
        deviation *= persistence
        order = np.asarray(ordering)
        if len(order) < 2:
            continue
        beaten = (len(order) - 1 - np.arange(len(order))) / (len(order) - 1)
        deviation[order] += beaten - expected[order]
    return deviation
