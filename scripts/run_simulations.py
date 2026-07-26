"""Precompute every season's 24-race bootstrap into data/f1.db.

    python scripts/run_simulations.py --iterations 10000 --seed 20240424

Each invocation writes a new run_id and marks it complete only once every table
is written, so the API — which reads the newest complete run — never serves a
half-finished rebuild.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models import sim as _sim  # noqa: E402,F401  (registers tables)
from app.models import source as _source  # noqa: E402,F401
from app.services.event_source import list_seasons, load_season_events  # noqa: E402
from app.services.form_source import load_season_form  # noqa: E402
from app.sim.bootstrap import (  # noqa: E402
    DEFAULT_ITERATIONS,
    DEFAULT_TARGET_RACES,
    scale_of,
    simulate_season,
    summarise,
)
from app.sim.career import Summary, aggregate_group, encode_draws, probability_at_least  # noqa: E402
from app.sim.continuation import (  # noqa: E402
    champion_probability as continuation_champion_probability,
    simulate_continuation,
)
from app.sim.rng import continuation_generator  # noqa: E402

logger = logging.getLogger("run_simulations")

#: Metrics whose per-iteration draws are persisted and rolled up into careers.
PERSISTED_DRIVER_METRICS = (
    "points", "points_no_fl", "wins", "quality_wins", "podiums", "poles", "entries",
)
PERSISTED_CONSTRUCTOR_METRICS = ("points", "points_no_fl", "wins", "quality_wins", "podiums")

#: Grouping dimensions offered by the historical tab. Decade and era are served
#: by the year-range filter instead: summing every driver's wins within a decade
#: would just return 24 x the number of seasons, which says nothing.
GROUP_DIMENSIONS = ("constructor", "driver_nationality", "constructor_nationality")

CAREER_METRICS = (
    "points", "points_no_fl", "wins", "quality_wins", "podiums", "poles", "championships",
)
TITLE_THRESHOLDS = range(1, 11)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _quantile_columns(prefix: str, draws: np.ndarray) -> dict[str, float]:
    stats = summarise(draws)
    return {
        f"{prefix}_mean": stats["mean"],
        f"{prefix}_median": stats["median"],
        f"{prefix}_p2_5": stats["p2_5"],
        f"{prefix}_p97_5": stats["p97_5"],
    }


def _career_summary(metric: str, draws: np.ndarray) -> Summary:
    """Summarise career draws, converting fixed-point metrics back to real units."""
    return Summary.of(draws).divided_by(scale_of(metric))


def _summary_columns(prefix: str, summary: Summary) -> dict[str, float]:
    return {
        f"{prefix}_mean": summary.mean,
        f"{prefix}_median": summary.median,
        f"{prefix}_p2_5": summary.p2_5,
        f"{prefix}_p97_5": summary.p97_5,
    }


def insert_many(conn, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    statement = text(
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(':' + c for c in columns)})"
    )
    conn.execute(statement, rows)


def run_season(
    conn, run_id: int, year: int, args, retained: dict, *, retain: bool = True
) -> tuple[int, int]:
    """Simulate one season, write its rows, and retain draws for the career pass.

    `retain=False` for a season still in progress: it is still simulated and shown
    in the Seasons tab as a projection, but folding a half-run season into career
    totals would credit a driver with a full 24-race season they have not had.
    """
    events = load_season_events(conn, year)
    result = simulate_season(
        events,
        master_seed=args.seed,
        n_iterations=args.iterations,
        target_races=args.target_races,
    )

    driver = result.driver
    champion_probability = driver.champion_probability()
    top3_probability = driver.top_three_probability()
    actual_positions = _actual_positions(conn, year)

    driver_rows = []
    for i, driver_id in enumerate(driver.ids):
        constructor = events.driver_constructor[i]
        row = {
            "run_id": run_id,
            "year": year,
            "driver_id": int(driver_id),
            "constructor_id": int(constructor) if constructor >= 0 else None,
            "actual_races": int(driver.actual["entries"][i]),
            "actual_points": float(driver.actual["points"][i]),
            "actual_points_no_fl": float(driver.actual["points_no_fl"][i]),
            "actual_wins": float(driver.actual["wins"][i]),
            "actual_quality_wins": float(driver.actual["quality_wins"][i]),
            "actual_podiums": float(driver.actual["podiums"][i]),
            "actual_poles": float(driver.actual["poles"][i]),
            "scaled_points": float(driver.scaled["points"][i]),
            "scaled_points_no_fl": float(driver.scaled["points_no_fl"][i]),
            "scaled_wins": float(driver.scaled["wins"][i]),
            "scaled_quality_wins": float(driver.scaled["quality_wins"][i]),
            "scaled_podiums": float(driver.scaled["podiums"][i]),
            "scaled_poles": float(driver.scaled["poles"][i]),
            "p_champion": float(champion_probability[i]),
            "p_top3": float(top3_probability[i]),
            "actual_position": actual_positions.get(int(driver_id)),
        }
        for metric in ("points", "wins", "quality_wins", "podiums", "poles"):
            row.update(
                {k: float(v[i]) for k, v in _quantile_columns(metric, driver.totals[metric]).items()}
            )
        entries = summarise(driver.totals["entries"])
        row.update(
            {
                "entries_mean": float(entries["mean"][i]),
                "entries_p2_5": float(entries["p2_5"][i]),
                "entries_p97_5": float(entries["p97_5"][i]),
            }
        )
        driver_rows.append(row)

    constructor_sim = result.constructor
    constructor_champion = constructor_sim.champion_probability()
    constructor_rows = []
    for i, constructor_id in enumerate(constructor_sim.ids):
        row = {
            "run_id": run_id,
            "year": year,
            "constructor_id": int(constructor_id),
            "actual_points": float(constructor_sim.actual["points"][i]),
            "actual_wins": float(constructor_sim.actual["wins"][i]),
            "actual_quality_wins": float(constructor_sim.actual["quality_wins"][i]),
            "actual_podiums": float(constructor_sim.actual["podiums"][i]),
            "scaled_points": float(constructor_sim.scaled["points"][i]),
            "scaled_wins": float(constructor_sim.scaled["wins"][i]),
            "scaled_quality_wins": float(constructor_sim.scaled["quality_wins"][i]),
            "scaled_podiums": float(constructor_sim.scaled["podiums"][i]),
            "p_champion": float(constructor_champion[i]),
        }
        for metric in ("points", "wins", "quality_wins", "podiums"):
            row.update(
                {
                    k: float(v[i])
                    for k, v in _quantile_columns(metric, constructor_sim.totals[metric]).items()
                }
            )
        constructor_rows.append(row)

    # --- Per-iteration draws: stored, and retained for the career pass -------
    blob_rows = []
    for entity_result, metrics in (
        (driver, PERSISTED_DRIVER_METRICS),
        (constructor_sim, PERSISTED_CONSTRUCTOR_METRICS),
    ):
        championships = entity_result.championship_draws()
        for metric in (*metrics, "championships"):
            draws = (
                championships
                if metric == "championships"
                else entity_result.iteration_draws(metric)
            )
            for i, entity_id in enumerate(entity_result.ids):
                column = np.ascontiguousarray(draws[:, i])
                blob_rows.append(
                    {
                        "run_id": run_id,
                        "year": year,
                        "entity_type": entity_result.entity,
                        "entity_id": int(entity_id),
                        "metric": metric,
                        "dtype": str(column.dtype),
                        "n_iterations": args.iterations,
                        "data": encode_draws(column),
                    }
                )
                if retain and metric in CAREER_METRICS:
                    retained[entity_result.entity][int(entity_id)][metric].append(
                        (year, column)
                    )

    insert_many(conn, "season_continuation_sim", _continuation_rows(conn, run_id, year, args))
    insert_many(conn, "season_driver_sim", driver_rows)
    insert_many(conn, "season_constructor_sim", constructor_rows)
    insert_many(conn, "sim_iterations", blob_rows)
    return len(driver_rows), len(constructor_rows)


def _continuation_rows(conn, run_id: int, year: int, args) -> list[dict]:
    """Race out the remainder of a season from end-of-year form.

    Deliberately a separate pass over the same season rather than a branch
    inside the bootstrap: the two models share no state, answer different
    questions, and are seeded from independent streams.
    """
    form = load_season_form(conn, year)
    rng = continuation_generator(args.seed, year)
    result = simulate_continuation(
        form,
        rng=rng,
        n_iterations=args.iterations,
        target_races=args.target_races,
    )
    odds = continuation_champion_probability(
        result["points"], result["wins"], result["podiums"]
    )
    stats = summarise(result["points"])
    strength = np.atleast_2d(form.strength).mean(axis=0)

    return [
        {
            "run_id": run_id,
            "year": year,
            "driver_id": int(driver_id),
            "extra_races": int(result["extra_races"][0]),
            "banked_points": float(form.points[i]),
            "form_strength": float(strength[i]),
            "points_mean": float(stats["mean"][i]),
            "points_median": float(stats["median"][i]),
            "points_p2_5": float(stats["p2_5"][i]),
            "points_p97_5": float(stats["p97_5"][i]),
            "wins_mean": float(result["wins"].mean(axis=0)[i]),
            "podiums_mean": float(result["podiums"].mean(axis=0)[i]),
            "p_champion": float(odds[i]),
        }
        for i, driver_id in enumerate(form.driver_ids)
    ]


def _actual_positions(conn, year: int) -> dict[int, int]:
    """Where each driver really finished the championship, for comparison."""
    rows = conn.execute(
        text(
            """
            SELECT rr.driver_id, SUM(rr.points_no_fl) AS pts, SUM(rr.is_win) AS wins
            FROM race_results rr
            JOIN races r ON r.race_id = rr.race_id AND r.excluded = 0
            WHERE r.year = :year
            GROUP BY rr.driver_id
            ORDER BY pts DESC, wins DESC
            """
        ),
        {"year": year},
    ).all()
    return {int(row.driver_id): position for position, row in enumerate(rows, start=1)}


def write_careers(conn, run_id: int, retained: dict, args) -> int:
    """Roll season draws into career totals, summing vectors not medians."""
    actual_titles = dict(
        conn.execute(
            text(
                """
                SELECT actual_champion_driver_id, COUNT(*)
                FROM seasons WHERE actual_champion_driver_id IS NOT NULL
                GROUP BY actual_champion_driver_id
                """
            )
        ).all()
    )

    rows = []
    for driver_id, metrics in retained["driver"].items():
        years = sorted({year for year, _ in metrics["wins"]})
        career: dict[str, np.ndarray] = {}
        for metric, entries in metrics.items():
            total = np.zeros(args.iterations, dtype=np.int64)
            for _, vector in entries:
                total += vector.astype(np.int64)
            career[metric] = total

        row = {
            "run_id": run_id,
            "driver_id": driver_id,
            "seasons_active": len(years),
            "first_year": years[0],
            "last_year": years[-1],
            "actual_races": 0,
            "actual_championships": int(actual_titles.get(driver_id, 0)),
        }
        for metric in ("wins", "quality_wins", "podiums", "poles", "points", "championships"):
            row.update(_summary_columns(metric, _career_summary(metric, career[metric])))
        row["championships_at_least"] = json.dumps(
            probability_at_least(career["championships"], TITLE_THRESHOLDS)
        )
        rows.append(row)

    # Actual and pro-rata career totals come straight from the season summaries,
    # where both are already exact.
    # Restricted to completed seasons, matching the draws retained above.
    totals = conn.execute(
        text(
            """
            SELECT sds.driver_id,
                   SUM(sds.actual_races) AS races,
                   SUM(sds.actual_wins) AS wins, SUM(sds.actual_podiums) AS podiums,
                   SUM(sds.actual_poles) AS poles, SUM(sds.actual_points_no_fl) AS points,
                   SUM(sds.actual_quality_wins) AS quality_wins,
                   SUM(sds.scaled_wins) AS s_wins, SUM(sds.scaled_podiums) AS s_podiums,
                   SUM(sds.scaled_poles) AS s_poles, SUM(sds.scaled_points_no_fl) AS s_points,
                   SUM(sds.scaled_quality_wins) AS s_quality_wins
            FROM season_driver_sim sds
            JOIN seasons s ON s.year = sds.year AND s.is_complete = 1
            WHERE sds.run_id = :run
            GROUP BY sds.driver_id
            """
        ),
        {"run": run_id},
    ).all()
    by_driver = {int(r.driver_id): r for r in totals}
    for row in rows:
        actual = by_driver[row["driver_id"]]
        row.update(
            {
                "actual_races": int(actual.races),
                "actual_wins": float(actual.wins),
                "actual_quality_wins": float(actual.quality_wins),
                "actual_podiums": float(actual.podiums),
                "actual_poles": float(actual.poles),
                "actual_points": float(actual.points),
                "scaled_wins": float(actual.s_wins),
                "scaled_quality_wins": float(actual.s_quality_wins),
                "scaled_podiums": float(actual.s_podiums),
                "scaled_poles": float(actual.s_poles),
                "scaled_points": float(actual.s_points),
            }
        )

    insert_many(conn, "career_driver_sim", rows)
    return len(rows)


def _actual_and_scaled_totals(conn, run_id: int) -> dict[tuple[str, int, str], tuple[float, float]]:
    """Career actual and pro-rata totals per entity, keyed by (type, id, metric).

    Groups need these to sit beside their simulated figures, and to have a real
    baseline to measure rank movement against.
    """
    totals: dict[tuple[str, int, str], tuple[float, float]] = {}

    for row in conn.execute(
        text(
            """
            SELECT sds.driver_id AS id,
                   SUM(sds.actual_wins) AS a_wins, SUM(sds.scaled_wins) AS s_wins,
                   SUM(sds.actual_quality_wins) AS a_qw, SUM(sds.scaled_quality_wins) AS s_qw,
                   SUM(sds.actual_podiums) AS a_pod, SUM(sds.scaled_podiums) AS s_pod,
                   SUM(sds.actual_poles) AS a_pol, SUM(sds.scaled_poles) AS s_pol,
                   SUM(sds.actual_points_no_fl) AS a_pts,
                   SUM(sds.scaled_points_no_fl) AS s_pts
            FROM season_driver_sim sds
            JOIN seasons se ON se.year = sds.year AND se.is_complete = 1
            WHERE sds.run_id = :run GROUP BY sds.driver_id
            """
        ),
        {"run": run_id},
    ).all():
        totals[("driver", int(row.id), "wins")] = (row.a_wins, row.s_wins)
        totals[("driver", int(row.id), "quality_wins")] = (row.a_qw, row.s_qw)
        totals[("driver", int(row.id), "podiums")] = (row.a_pod, row.s_pod)
        totals[("driver", int(row.id), "poles")] = (row.a_pol, row.s_pol)
        totals[("driver", int(row.id), "points")] = (row.a_pts, row.s_pts)
        totals[("driver", int(row.id), "points_no_fl")] = (row.a_pts, row.s_pts)

    for row in conn.execute(
        text(
            """
            SELECT scs.constructor_id AS id,
                   SUM(scs.actual_wins) AS a_wins, SUM(scs.scaled_wins) AS s_wins,
                   SUM(scs.actual_quality_wins) AS a_qw, SUM(scs.scaled_quality_wins) AS s_qw,
                   SUM(scs.actual_podiums) AS a_pod, SUM(scs.scaled_podiums) AS s_pod,
                   SUM(scs.actual_points) AS a_pts, SUM(scs.scaled_points) AS s_pts
            FROM season_constructor_sim scs
            JOIN seasons se ON se.year = scs.year AND se.is_complete = 1
            WHERE scs.run_id = :run GROUP BY scs.constructor_id
            """
        ),
        {"run": run_id},
    ).all():
        totals[("constructor", int(row.id), "wins")] = (row.a_wins, row.s_wins)
        totals[("constructor", int(row.id), "quality_wins")] = (row.a_qw, row.s_qw)
        totals[("constructor", int(row.id), "podiums")] = (row.a_pod, row.s_pod)
        totals[("constructor", int(row.id), "points")] = (row.a_pts, row.s_pts)
        totals[("constructor", int(row.id), "points_no_fl")] = (row.a_pts, row.s_pts)

    # Titles per driver, from the real record.
    for row in conn.execute(
        text(
            """
            SELECT actual_champion_driver_id AS id, COUNT(*) AS titles
            FROM seasons WHERE actual_champion_driver_id IS NOT NULL
            GROUP BY actual_champion_driver_id
            """
        )
    ).all():
        totals[("driver", int(row.id), "championships")] = (float(row.titles), float(row.titles))

    return totals


def write_groups(conn, run_id: int, retained: dict, args) -> int:
    """Aggregate careers by constructor and by nationality."""
    entity_totals = _actual_and_scaled_totals(conn, run_id)
    driver_nationality = dict(
        conn.execute(text("SELECT driver_id, nationality FROM drivers")).all()
    )
    constructor_meta = {
        int(r.constructor_id): (r.name, r.nationality)
        for r in conn.execute(
            text("SELECT constructor_id, name, nationality FROM constructors")
        ).all()
    }

    memberships: dict[str, dict[str, list]] = {dim: defaultdict(list) for dim in GROUP_DIMENSIONS}
    labels: dict[tuple[str, str], str] = {}

    # Members carry their entity identity so actual totals can be looked up.
    for constructor_id, metrics in retained["constructor"].items():
        name, nationality = constructor_meta.get(constructor_id, (str(constructor_id), None))
        member = ("constructor", constructor_id, metrics)
        memberships["constructor"][str(constructor_id)].append(member)
        labels[("constructor", str(constructor_id))] = name
        if nationality:
            memberships["constructor_nationality"][nationality].append(member)
            labels[("constructor_nationality", nationality)] = nationality

    for driver_id, metrics in retained["driver"].items():
        nationality = driver_nationality.get(driver_id)
        if nationality:
            memberships["driver_nationality"][nationality].append(
                ("driver", driver_id, metrics)
            )
            labels[("driver_nationality", nationality)] = nationality

    rows = []
    for dimension, groups in memberships.items():
        # Constructors have no pole or entry columns of their own.
        metrics = (
            ("wins", "quality_wins", "podiums", "points", "points_no_fl", "championships")
            if dimension != "driver_nationality"
            else CAREER_METRICS
        )
        for group_key, members in groups.items():
            for metric in metrics:
                vectors = []
                actual_total = 0.0
                scaled_total = 0.0
                for entity_type, entity_id, member in members:
                    if metric not in member:
                        continue
                    total = np.zeros(args.iterations, dtype=np.int64)
                    for _, vector in member[metric]:
                        total += vector.astype(np.int64)
                    vectors.append(total)

                    actual, scaled = entity_totals.get((entity_type, entity_id, metric), (0.0, 0.0))
                    actual_total += actual
                    scaled_total += scaled
                if not vectors:
                    continue
                summary, _ = aggregate_group(vectors)
                summary = summary.divided_by(scale_of(metric))
                rows.append(
                    {
                        "run_id": run_id,
                        "dimension": dimension,
                        "group_key": group_key,
                        "metric": metric,
                        "group_label": labels[(dimension, group_key)],
                        "n_entities": len(members),
                        "actual": actual_total,
                        "scaled": scaled_total,
                        "mean": summary.mean,
                        "median": summary.median,
                        "p2_5": summary.p2_5,
                        "p97_5": summary.p97_5,
                    }
                )

    insert_many(conn, "group_sim", rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=settings.db_path)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--target-races", type=int, default=DEFAULT_TARGET_RACES)
    parser.add_argument("--seed", type=int, default=20240424)
    parser.add_argument("--years", nargs="*", type=int, help="limit to these seasons")
    parser.add_argument(
        "--replace", action="store_true", help="delete previous runs before writing"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.db.exists():
        logger.error("No database at %s. Run scripts/build_db.py first.", args.db)
        return 1

    engine = create_engine(f"sqlite:///{args.db.as_posix()}", future=True)
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        if args.replace:
            for table in (
                "sim_iterations", "season_driver_sim", "season_constructor_sim",
                "season_continuation_sim",
                "career_driver_sim", "group_sim", "sim_runs",
            ):
                conn.execute(text(f"DELETE FROM {table}"))
            logger.info("Cleared previous runs")

        run_id = conn.execute(
            text(
                """
                INSERT INTO sim_runs
                    (created_at, n_iterations, target_races, master_seed, is_complete,
                     seasons_simulated)
                VALUES (:created, :iterations, :target, :seed, 0, 0)
                RETURNING run_id
                """
            ),
            {
                "created": _now(),
                "iterations": args.iterations,
                "target": args.target_races,
                "seed": args.seed,
            },
        ).scalar_one()

        years = args.years or list_seasons(conn)
        logger.info(
            "Run %d: %d seasons (%d-%d), %d iterations, target %d races, seed %d",
            run_id, len(years), years[0], years[-1], args.iterations,
            args.target_races, args.seed,
        )

        retained: dict = {
            "driver": defaultdict(lambda: defaultdict(list)),
            "constructor": defaultdict(lambda: defaultdict(list)),
        }

        in_progress = {
            row.year
            for row in conn.execute(
                text("SELECT year FROM seasons WHERE is_complete = 0")
            ).all()
        }

        for year in years:
            retain = year not in in_progress
            drivers, constructors = run_season(
                conn, run_id, year, args, retained, retain=retain
            )
            note = "" if retain else "  (in progress: excluded from career totals)"
            logger.info(
                "  %d  %3d drivers  %2d constructors%s", year, drivers, constructors, note
            )

        career_rows = write_careers(conn, run_id, retained, args)
        logger.info("careers   %6d drivers", career_rows)

        group_rows = write_groups(conn, run_id, retained, args)
        logger.info("groups    %6d rows", group_rows)

        conn.execute(
            text(
                "UPDATE sim_runs SET is_complete = 1, seasons_simulated = :n WHERE run_id = :run"
            ),
            {"n": len(years), "run": run_id},
        )

    with engine.connect() as conn:
        size = args.db.stat().st_size / 1_048_576
        blobs = conn.execute(
            text("SELECT COUNT(*) FROM sim_iterations WHERE run_id = :run"), {"run": run_id}
        ).scalar_one()
    logger.info("wrote %d iteration blobs; database now %.1f MB", blobs, size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
