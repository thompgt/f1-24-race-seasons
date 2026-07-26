"""Ask the continuation for title odds on championships already decided.

`scripts/calibrate_form.py` checks the model one race at a time, and on that
test it does well: told two drivers are close, it is right about how close.
But a championship is not a race. The continuation's actual claim is about
eight of them compounded, over a points table, with reliability and entry
folded in — and a model can be perfectly calibrated per race and badly
overconfident about the season, because errors that are independent per pair
are not independent per title.

So this asks the question the model is really for. Cut a real season after
race k, hand the continuation only what had happened by then, and let it race
out the rounds that remain. The champion is already known, so the odds can be
scored. Do that for every season and every cut and the result is a reliability
diagram over titles: when this model says 90%, how often does that driver
actually win?

The cuts are chosen to leave 2 to 8 races, which is the range the production
continuation covers when it stretches a short season to 24.

That the answer can be checked at all is the point. "More Alonso than expected
in 2007" is not a testable claim, but "the model's 90%s come in 90% of the
time" is, and it is the one that decides whether a title race the model calls
settled really was.

    python scripts/backtest_titles.py
    python scripts/backtest_titles.py --iterations 2000 --years 1988 2007 2021
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.services.form_source import load_season_form  # noqa: E402
from app.sim.continuation import (  # noqa: E402
    STATIC_FORM,
    FormDynamics,
    champion_probability,
    simulate_continuation,
)

#: Races left to run at each cut. The continuation's real workload: a 16-race
#: 1980s season stretched to 24 leaves eight, a modern 22-race season leaves two.
REMAINING = (2, 3, 4, 5, 6, 7, 8)

#: Cuts below this leave too little of a season to fit form from.
MIN_HISTORY = 6

_YEARS = text(
    """
    SELECT year, COUNT(*) AS races
    FROM races WHERE excluded = 0
    GROUP BY year HAVING races >= 8 ORDER BY year
    """
)


def actual_standings(form_full) -> np.ndarray:
    """Who really finished where, on the same modern scale the model uses.

    Taken from a full-season `SeasonForm` rather than from the record books, so
    that the model is scored against the championship *as this project counts
    it* — modern points, no fastest lap, Indianapolis excluded. Scoring it
    against the historical champion instead would mix a question about the
    simulation with a question about 1950s points systems.
    """
    return champion_probability(
        form_full.points[None, :], form_full.wins[None, :], form_full.podiums[None, :]
    )


def build_cases(conn, years, *, seed: int) -> list[dict]:
    """Fit every (season, cut) once, so candidate dynamics can be swept cheaply.

    Fitting the strength ensemble is almost all of the cost here and none of it
    depends on the dynamics being scored, so a grid search that refitted per
    candidate would spend hours recomputing identical numbers.
    """
    cases = []
    for year, n_races in years:
        try:
            full = load_season_form(conn, year, ensemble=1)
        except ValueError:
            continue
        champion_id = int(full.driver_ids[int(np.argmax(actual_standings(full)))])

        for remaining in REMAINING:
            cut = n_races - remaining
            if cut < MIN_HISTORY:
                continue
            try:
                form = load_season_form(
                    conn,
                    year,
                    through_race=cut,
                    rng=np.random.default_rng([seed, year, cut]),
                )
            except ValueError:
                continue

            # Mapped by driver id rather than by position, because a driver who
            # debuts after the cut is in one form and not the other.
            position = {int(d): i for i, d in enumerate(form.driver_ids)}
            if champion_id not in position:
                continue

            leader = int(np.argmax(form.points))
            cases.append(
                {
                    "year": year,
                    "cut": cut,
                    "remaining": remaining,
                    "n_races": n_races,
                    "form": form,
                    "champion_slot": position[champion_id],
                    "leader_slot": leader,
                    "leader_won": bool(int(form.driver_ids[leader]) == champion_id),
                    "margin": float(
                        np.max(form.points) - np.partition(form.points, -2)[-2]
                    ),
                }
            )
    return cases


def score(cases, *, iterations: int, dynamics: FormDynamics, seed: int) -> list[dict]:
    """Run every cut under one set of dynamics and record the odds it gave."""
    records = []
    for case in cases:
        form = case["form"]
        result = simulate_continuation(
            form,
            rng=np.random.default_rng(
                [seed, case["year"], case["cut"], case["remaining"]]
            ),
            n_iterations=iterations,
            target_races=case["n_races"],
            dynamics=dynamics,
        )
        odds = champion_probability(
            result["points"], result["wins"], result["podiums"]
        )
        records.append(
            {
                "year": case["year"],
                "cut": case["cut"],
                "remaining": case["remaining"],
                "p_champion": float(odds[case["champion_slot"]]),
                "p_leader": float(odds[case["leader_slot"]]),
                "leader_won": case["leader_won"],
                "margin": case["margin"],
            }
        )
    return records


def reliability(records: list[dict], edges) -> list[dict]:
    """Bucket the odds given to the driver who was leading at the cut.

    Scored on the leader rather than on the eventual champion because that is
    the decision the model is accused of getting wrong: a leader the model
    calls safe. Every cut contributes exactly one leader, so the buckets are a
    partition and no season is counted twice.
    """
    predicted = np.array([r["p_leader"] for r in records])
    outcome = np.array([r["leader_won"] for r in records], dtype=float)

    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        selected = (predicted >= lo) & (predicted < hi)
        if not selected.any():
            continue
        rows.append(
            {
                "bucket": f"{lo:.2f}-{hi:.2f}",
                "n": int(selected.sum()),
                "model": float(predicted[selected].mean()),
                "actual": float(outcome[selected].mean()),
            }
        )
    return rows


def brier(records: list[dict]) -> float:
    """Mean squared error of the leader's odds — lower is better calibrated."""
    predicted = np.array([r["p_leader"] for r in records])
    outcome = np.array([r["leader_won"] for r in records], dtype=float)
    return float(((predicted - outcome) ** 2).mean())


def log_loss(records: list[dict]) -> float:
    predicted = np.clip(np.array([r["p_leader"] for r in records]), 1e-6, 1 - 1e-6)
    outcome = np.array([r["leader_won"] for r in records], dtype=float)
    return float(
        -(outcome * np.log(predicted) + (1 - outcome) * np.log(1 - predicted)).mean()
    )


def report(label: str, records: list[dict]) -> None:
    edges = [0.0, 0.5, 0.7, 0.85, 0.95, 0.99, 1.0001]
    print(f"\n=== {label} ===  {len(records)} cuts")
    print("odds given leader        n     model    actual     gap")
    for row in reliability(records, edges):
        print(
            f"  {row['bucket']:>12}  {row['n']:>6}    {row['model']:.3f}"
            f"     {row['actual']:.3f}   {row['actual'] - row['model']:+.3f}"
        )
    print(f"  brier {brier(records):.4f}   log-loss {log_loss(records):.4f}")


#: Coarse sweep for `--search`. Persistence sits high throughout because the
#: overconfidence being corrected is a *season-level* error: independent
#: race-to-race noise averages out over eight races and barely moves a title,
#: whereas a form deviation that persists does not average out at all. That is
#: also why the per-race calibration in `calibrate_form.py` cannot find this on
#: its own — it scores each pair separately, and so is blind to exactly the
#: correlation across races that decides a championship.
#:
#: Volatility runs past 1.0 deliberately. An earlier grid stopped at 1.0 and the
#: optimum landed exactly on that edge in the main fit *and* in both split-half
#: folds, which says nothing about where the optimum is — only that the grid was
#: too narrow to contain it. The deviation is clipped to `FormDynamics.band`
#: anyway, so the upper values saturate rather than diverge.
SEARCH_GRID = tuple(
    FormDynamics(persistence=p, volatility=v, momentum=m)
    for p in (0.7, 0.9, 1.0)
    for v in (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0)
    for m in (0.0, 0.5, 1.0)
)


def holdout(cases, *, iterations: int, seed: int) -> None:
    """Fit the grid on half the seasons, score it on the other half.

    Three parameters chosen on 425 cuts sounds comfortable, but the cuts within
    a season overlap heavily and the real sample size is closer to the number of
    seasons. Splitting by parity of year keeps eras on both sides — a
    chronological split would fit the drift of the 1950s and test it on the
    hybrid era — and asks the only question that matters: do the settings
    picked without seeing these seasons still beat static form on them?
    """
    halves = {
        "odd": [c for c in cases if c["year"] % 2],
        "even": [c for c in cases if not c["year"] % 2],
    }
    print("\nsplit-half check")
    for fit_on, test_on in (("odd", "even"), ("even", "odd")):
        ranked = sorted(
            (
                log_loss(
                    score(
                        halves[fit_on],
                        iterations=iterations,
                        dynamics=dynamics,
                        seed=seed,
                    )
                ),
                index,
                dynamics,
            )
            for index, dynamics in enumerate(SEARCH_GRID)
        )
        picked = ranked[0][2]
        tested = log_loss(
            score(halves[test_on], iterations=iterations, dynamics=picked, seed=seed)
        )
        baseline = log_loss(
            score(halves[test_on], iterations=iterations, dynamics=STATIC_FORM, seed=seed)
        )
        print(
            f"  fit {fit_on} -> p={picked.persistence} v={picked.volatility}"
            f" m={picked.momentum}; on {test_on}: fitted {tested:.4f}"
            f" vs static {baseline:.4f} ({100 * (baseline - tested) / baseline:+.1f}%)"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=settings.db_path)
    parser.add_argument("--years", nargs="*", type=int)
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20240424)
    parser.add_argument("--persistence", type=float, default=None)
    parser.add_argument("--volatility", type=float, default=None)
    parser.add_argument("--momentum", type=float, default=None)
    parser.add_argument(
        "--search",
        action="store_true",
        help="sweep SEARCH_GRID and rank by title-level log-loss",
    )
    parser.add_argument("--out", type=Path, default=Path("data/title_backtest.json"))
    args = parser.parse_args()

    engine = create_engine(f"sqlite:///{args.db}")
    with engine.connect() as conn:
        years = [(int(r.year), int(r.races)) for r in conn.execute(_YEARS).all()]
        if args.years:
            years = [row for row in years if row[0] in set(args.years)]
        cases = build_cases(conn, years, seed=args.seed)
    print(f"{len(cases)} cuts across {len(years)} seasons")

    if args.search:
        ranked = []
        for dynamics in SEARCH_GRID:
            records = score(
                cases, iterations=args.iterations, dynamics=dynamics, seed=args.seed
            )
            ranked.append((log_loss(records), brier(records), dynamics))
            print(
                f"  p={dynamics.persistence:<4} v={dynamics.volatility:<5}"
                f" m={dynamics.momentum:<4}  log-loss {ranked[-1][0]:.4f}"
                f"  brier {ranked[-1][1]:.4f}"
            )
        ranked.sort(key=lambda row: row[0])
        print("\nbest by title log-loss:")
        for loss, score_, dynamics in ranked[:5]:
            print(
                f"  p={dynamics.persistence:<4} v={dynamics.volatility:<5}"
                f" m={dynamics.momentum:<4}  log-loss {loss:.4f}  brier {score_:.4f}"
            )
        chosen = ranked[0][2]
        holdout(cases, iterations=args.iterations, seed=args.seed)
    elif args.volatility is not None or args.momentum is not None:
        chosen = FormDynamics(
            persistence=args.persistence or 0.0,
            volatility=args.volatility or 0.0,
            momentum=args.momentum or 0.0,
        )
    else:
        chosen = None

    candidates = {"static": STATIC_FORM}
    if chosen is not None and not chosen.is_static:
        candidates["fitted"] = chosen

    results = {}
    for label, dynamics in candidates.items():
        records = score(
            cases, iterations=args.iterations, dynamics=dynamics, seed=args.seed
        )
        report(label, records)
        results[label] = {
            "dynamics": vars(dynamics),
            "brier": brier(records),
            "log_loss": log_loss(records),
            "reliability": reliability(
                records, [0.0, 0.5, 0.7, 0.85, 0.95, 0.99, 1.0001]
            ),
            "records": records,
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
