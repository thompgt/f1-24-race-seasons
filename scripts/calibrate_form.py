"""Fit the continuation's form model to the seasons that really happened.

`FormDynamics` has three numbers in it, and a model whose drama depends on
three hand-chosen constants is not a model, it is a preference. So they are
estimated here, by out-of-sample predictive likelihood, from every race
1950-2025.

The procedure is one walk-forward loop and one grid search:

1. Cut each season after race k. Fit strengths on races 1..k alone — as an
   ensemble of bootstrap refits, exactly as the simulator uses them.
2. For horizons h = 1..H, score the *pairwise* orderings of race k+h under
   those strengths, widened by the drift the candidate dynamics imply after h
   races (`drift_spread`), and optionally shifted by the momentum a driver
   carried into the cut (`recent_surprise`).
3. Sum the negative log predictive probability over every pair at every
   horizon in every season, and take the parameters that minimise it.

Nothing after a cut informs the fit that is scored against it, so this is
prediction rather than description. And because the ensemble is inside the
likelihood, the drift term is estimated as the movement in pace left over
*after* the uncertainty in the fit is accounted for — which is what stops the
simulator from counting the same doubt twice.

The criterion is log-loss rather than hit rate throughout. A model can be right
slightly more often while being wildly overconfident about it, and for a
championship simulation confidence is the entire product: the question is never
"who was quicker" but "how sure can anyone be".

    python scripts/calibrate_form.py
    python scripts/calibrate_form.py --years 1980 1981 --ensemble 8 --quick
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.sim.backtest import (  # noqa: E402
    drift_spread,
    pair_hit_rate,
    pair_margins,
    pair_win_probability,
    race_pairs,
    recent_surprise,
)
from app.sim.continuation import (  # noqa: E402
    FormDynamics,
    expected_beat_fraction,
    fit_strength_ensemble,
    recency_weights,
)

#: How far ahead the fit is asked to predict. Eight is the largest gap the
#: continuation ever has to cover — a sixteen-race season stretched to 24 — so
#: the parameters are estimated over exactly the range they are used on.
MAX_HORIZON = 8

#: Races of history required before a cut is scored. Below this the fit is
#: mostly prior and the pairs say more about `PRIOR_RACES` than about form.
MIN_HISTORY = 5

#: Ensemble size for calibration. Smaller than the simulator's 40 because the
#: whole grid is refitted per half-life; the estimate it feeds is an average
#: over hundreds of cuts, so the extra Monte Carlo noise washes out.
CALIBRATION_ENSEMBLE = 12

HALF_LIFE_GRID = (2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 1e6)
PERSISTENCE_GRID = (0.0, 0.3, 0.5, 0.7, 0.85, 1.0)
VOLATILITY_GRID = (0.0, 0.1, 0.2, 0.3, 0.45, 0.6, 0.8, 1.1)
#: Includes a negative value so the search is free to report that recent
#: over-performance predicts a *worse* next race — the regression-to-the-mean
#: answer, and the one a momentum term has to beat to be worth having.
MOMENTUM_GRID = (-0.2, 0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)

_RACES = text(
    """
    SELECT r.race_id, r.round
    FROM races r
    WHERE r.year = :year AND r.excluded = 0
    ORDER BY r.round
    """
)

_RESULTS = text(
    """
    SELECT rr.race_id, rr.driver_id, rr.position
    FROM race_results rr
    JOIN races r ON r.race_id = rr.race_id
    WHERE r.year = :year AND r.excluded = 0
      AND rr.position IS NOT NULL
      AND rr.is_shared_secondary = 0
    """
)

_YEARS = text("SELECT DISTINCT year FROM races WHERE excluded = 0 ORDER BY year")


def load_orderings(conn, year: int) -> tuple[list[np.ndarray], int, np.ndarray]:
    """Per-race finishing orders for a season, best finisher first.

    Classified finishers only — the same evidence `fit_strengths` is given,
    since a retirement says nothing about pace. Also returns each driver's
    entry rate, which weights the expectation the momentum term measures
    surprise against.
    """
    races = conn.execute(_RACES, {"year": year}).all()
    race_order = {int(row.race_id): i for i, row in enumerate(races)}
    rows = conn.execute(_RESULTS, {"year": year}).all()
    if not rows or not races:
        return [], 0, np.zeros(0)

    driver_ids = sorted({int(row.driver_id) for row in rows})
    index = {driver: i for i, driver in enumerate(driver_ids)}

    finishers: dict[int, list[tuple[int, int]]] = {i: [] for i in range(len(races))}
    starts = np.zeros(len(driver_ids))
    for row in rows:
        slot = race_order[int(row.race_id)]
        driver = index[int(row.driver_id)]
        finishers[slot].append((int(row.position), driver))
        starts[driver] += 1

    orderings = [
        np.array([driver for _, driver in sorted(finishers[slot])])
        for slot in range(len(races))
    ]
    return orderings, len(driver_ids), starts / max(len(races), 1)


def cut_points(n_races: int, *, quick: bool) -> list[int]:
    """Where to cut a season. `quick` thins them out for a fast pass."""
    available = list(range(MIN_HISTORY, n_races))
    if quick and len(available) > 4:
        available = available[:: len(available) // 4][:4]
    return available


def collect_margins(
    conn, years: list[int], *, half_life: float, ensemble: int, quick: bool, seed: int
) -> dict[int, dict[str, np.ndarray]]:
    """Walk every season forward, scoring each cut against races it never saw.

    Returns, per horizon, the fitted log-strength margins of the pairs that
    actually occurred — as (ensemble, pairs) — plus the momentum differential
    each pair carried into the cut. Both are independent of the drift and
    momentum parameters, so the grid search below runs over cached arrays
    rather than refitting for every candidate.
    """
    by_horizon: dict[int, dict[str, list[np.ndarray]]] = {
        h: {"margins": [], "momentum": []} for h in range(1, MAX_HORIZON + 1)
    }

    for year in years:
        orderings, n_drivers, entry_rate = load_orderings(conn, year)
        if n_drivers < 3 or len(orderings) <= MIN_HISTORY:
            continue

        for cut in cut_points(len(orderings), quick=quick):
            history = orderings[:cut]
            usable = [o for o in history if len(o) >= 2]
            if len(usable) < 2:
                continue

            weights = recency_weights(cut, half_life=half_life)
            kept = np.array([w for o, w in zip(history, weights) if len(o) >= 2])
            # Seeded off the cut, so a season's fits do not depend on the order
            # the calibration happens to visit years in.
            strength = fit_strength_ensemble(
                usable,
                kept,
                n_drivers,
                rng=np.random.default_rng([seed, year, cut]),
                n_samples=ensemble,
            )
            log_strength = np.log(np.maximum(strength, 1e-12))

            # Momentum carried into the cut, replayed over the history alone.
            # Accumulated undecayed here; the grid applies the decay it is
            # testing, so this need not be recomputed per candidate.
            expected = expected_beat_fraction(strength.mean(axis=0), entry_rate)
            carried = recent_surprise(usable, expected, n_drivers, persistence=1.0)

            for horizon in range(1, MAX_HORIZON + 1):
                target = cut + horizon - 1
                if target >= len(orderings) or len(orderings[target]) < 2:
                    continue
                ordering = orderings[target]
                margins = np.vstack(
                    [pair_margins(row, ordering) for row in log_strength]
                )
                if margins.shape[1] == 0:
                    continue
                ahead, behind = race_pairs(ordering)
                by_horizon[horizon]["margins"].append(margins.astype(np.float32))
                by_horizon[horizon]["momentum"].append(
                    (carried[ahead] - carried[behind]).astype(np.float32)
                )

    return {
        h: {
            key: np.concatenate(values, axis=-1) if values else np.zeros((1, 0))
            for key, values in parts.items()
        }
        for h, parts in by_horizon.items()
    }


def predictive_loss(
    cached: dict[int, dict[str, np.ndarray]], dynamics: FormDynamics
) -> tuple[float, int]:
    """Mean negative log predictive probability over every scored pair.

    The ensemble is averaged *inside* the logarithm, which is what makes this a
    predictive likelihood rather than an average of likelihoods: the model's
    stated probability for a pair is the one it would quote after integrating
    over its own uncertainty about the fit.
    """
    total, count = 0.0, 0
    for horizon, parts in cached.items():
        margins = parts["margins"]
        if margins.shape[1] == 0:
            continue
        shifted = margins.astype(np.float64)
        if dynamics.momentum:
            # A deviation carried into the cut has decayed for h-1 races by the
            # time this horizon is reached, the same as in the simulator.
            decay = dynamics.persistence ** (horizon - 1)
            shifted = shifted + dynamics.momentum * decay * parts["momentum"][None, :]

        spread = drift_spread(dynamics, horizon)
        probability = np.mean(
            [pair_win_probability(row, spread) for row in shifted], axis=0
        )
        total += float(-np.log(np.maximum(probability, 1e-12)).sum())
        count += len(probability)
    return (total / count if count else float("nan")), count


def horizon_report(
    cached: dict[int, dict[str, np.ndarray]], dynamics: FormDynamics
) -> list[dict]:
    """Per-horizon hit rate and loss, actual against what the model asserts."""
    report = []
    for horizon in sorted(cached):
        margins = cached[horizon]["margins"]
        if margins.shape[1] == 0:
            continue
        centre = margins.mean(axis=0).astype(np.float64)
        spread = drift_spread(dynamics, horizon)
        report.append(
            {
                "horizon": horizon,
                "pairs": int(margins.shape[1]),
                "actual_hit_rate": pair_hit_rate(centre),
                "model_hit_rate": float(
                    pair_win_probability(np.abs(centre), spread).mean()
                ),
                "loss": predictive_loss({horizon: cached[horizon]}, dynamics)[0],
            }
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=settings.db_path)
    parser.add_argument("--years", nargs="*", type=int)
    parser.add_argument("--ensemble", type=int, default=CALIBRATION_ENSEMBLE)
    parser.add_argument("--seed", type=int, default=20240424)
    parser.add_argument(
        "--quick", action="store_true", help="four cuts per season, for a fast pass"
    )
    parser.add_argument("--out", type=Path, default=Path("data/form_calibration.json"))
    args = parser.parse_args()

    engine = create_engine(f"sqlite:///{args.db}")
    with engine.connect() as conn:
        years = args.years or [int(row[0]) for row in conn.execute(_YEARS).all()]

        # Stage one: the half-life, scored under no drift so that the recency
        # question is settled on its own terms before drift is introduced.
        best = None
        cache_by_half_life = {}
        for half_life in HALF_LIFE_GRID:
            cached = collect_margins(
                conn,
                years,
                half_life=half_life,
                ensemble=args.ensemble,
                quick=args.quick,
                seed=args.seed,
            )
            cache_by_half_life[half_life] = cached
            loss, pairs = predictive_loss(cached, FormDynamics())
            label = "none" if half_life > 1e5 else f"{half_life:g}"
            print(f"half-life {label:>6}  loss {loss:.5f}  pairs {pairs:,}")
            if best is None or loss < best[1]:
                best = (half_life, loss)

    half_life = best[0]
    cached = cache_by_half_life[half_life]
    print(f"\nchosen half-life: {half_life:g}\n")

    # Stage two: drift, over the horizons the continuation actually spans.
    grid = []
    for persistence, volatility in product(PERSISTENCE_GRID, VOLATILITY_GRID):
        dynamics = FormDynamics(persistence=persistence, volatility=volatility)
        loss, _ = predictive_loss(cached, dynamics)
        grid.append((loss, persistence, volatility))
    grid.sort()
    print("best drift settings (persistence, volatility):")
    for loss, persistence, volatility in grid[:5]:
        print(f"  p={persistence:<5} v={volatility:<5} loss {loss:.5f}")
    _, persistence, volatility = grid[0]

    # Stage three: momentum, which is the only term making a claim about
    # streaks rather than about uncertainty — and so the one asked to earn its
    # place against a zero it is free to return to.
    momentum_grid = []
    for momentum in MOMENTUM_GRID:
        dynamics = FormDynamics(
            persistence=persistence, volatility=volatility, momentum=momentum
        )
        momentum_grid.append((predictive_loss(cached, dynamics)[0], momentum))
    momentum_grid.sort()
    print("\nbest momentum settings:")
    for loss, momentum in momentum_grid[:5]:
        print(f"  m={momentum:<5} loss {loss:.5f}")
    momentum = momentum_grid[0][1]

    chosen = FormDynamics(
        persistence=persistence, volatility=volatility, momentum=momentum
    )
    baseline, _ = predictive_loss(cached, FormDynamics())
    final, pairs = predictive_loss(cached, chosen)

    print(f"\nstatic form  loss {baseline:.5f}")
    print(f"fitted form  loss {final:.5f}  ({100 * (baseline - final) / baseline:+.2f}%)")
    print("\nhorizon   pairs   actual   model    loss")
    report = horizon_report(cached, chosen)
    for row in report:
        print(
            f"{row['horizon']:>7}  {row['pairs']:>6,}   {row['actual_hit_rate']:.3f}"
            f"    {row['model_hit_rate']:.3f}   {row['loss']:.4f}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "half_life": half_life,
                "persistence": persistence,
                "volatility": volatility,
                "momentum": momentum,
                "static_loss": baseline,
                "fitted_loss": final,
                "pairs": pairs,
                "seasons": len(years),
                "horizons": report,
            },
            indent=2,
        )
    )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
