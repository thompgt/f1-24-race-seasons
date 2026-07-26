"""Historical-stats queries: the re-derived all-time leaderboards.

Two paths, because a year-filtered leaderboard cannot be read off the
precomputed career table:

  * **No year filter** — serve `career_driver_sim` / `group_sim` directly.
  * **Year filter** — rank by the sum of per-season means, which is exact by
    linearity, then decode the stored iteration draws for just the rows actually
    shown to recover their medians and intervals. Summing per-season medians
    would be wrong (see `app.sim.career`), and decoding every driver's draws to
    avoid that would be far too slow per request.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import RunInfo, SimStat
from app.schemas.historical import Basis, GroupBy, LeaderBoard, LeaderRow, Metric
from app.sim.career import Summary, decode_draws

#: Career leaderboards exclude one-race wonders by default; a single win from a
#: single start scales to a chart-topping 24 otherwise.
DEFAULT_MIN_RACES = 10

#: `points` means the fastest-lap-free total on all-time tables. The bonus only
#: exists from 2004, so including it would hand modern drivers points earlier
#: drivers could never score — the very bias being corrected.
_CAREER_METRIC_COLUMN = {
    Metric.WINS: "wins",
    Metric.PODIUMS: "podiums",
    Metric.POLES: "poles",
    Metric.POINTS: "points",
    Metric.CHAMPIONSHIPS: "championships",
}

_SEASON_METRIC_COLUMN = {
    Metric.WINS: "wins",
    Metric.PODIUMS: "podiums",
    Metric.POLES: "poles",
    Metric.POINTS: "points_no_fl",
}

_BLOB_METRIC = {
    Metric.WINS: "wins",
    Metric.PODIUMS: "podiums",
    Metric.POLES: "poles",
    Metric.POINTS: "points_no_fl",
    Metric.CHAMPIONSHIPS: "championships",
}


def _sim_stat(mean: float, median: float, p2_5: float, p97_5: float) -> SimStat:
    return SimStat(mean=mean, median=median, p2_5=p2_5, p97_5=p97_5)


def _sort_key(basis: Basis, row: LeaderRow) -> float:
    if basis is Basis.ACTUAL:
        return row.actual
    if basis is Basis.SCALED:
        return row.scaled
    return row.sim.median * 1e6 + row.sim.mean


def _apply_ranks(rows: list[LeaderRow], basis: Basis) -> list[LeaderRow]:
    """Rank by the chosen basis, and record movement against the real record.

    Rank movement is only meaningful against a real baseline. Where the metric
    has no unadjusted counterpart — constructors' championships, which the source
    data does not carry — every `actual` is zero, the "real" ordering would be
    arbitrary, and the delta is left unset rather than invented.
    """
    has_baseline = any(row.actual for row in rows)

    ordered = sorted(rows, key=lambda r: -_sort_key(basis, r))
    actual_rank: dict[str, int] = {}
    if has_baseline:
        by_actual = sorted(rows, key=lambda r: (-r.actual, r.label))
        actual_rank = {row.key: i for i, row in enumerate(by_actual, start=1)}

    for position, row in enumerate(ordered, start=1):
        row.rank = position
        if has_baseline:
            row.rank_actual = actual_rank[row.key]
            # Positive means the normalisation moved this entry up the table.
            row.rank_delta = row.rank_actual - position
    return ordered


async def _driver_careers(
    db: AsyncSession, run: RunInfo, metric: Metric, min_races: int
) -> list[LeaderRow]:
    column = _CAREER_METRIC_COLUMN[metric]
    scaled_column = "scaled_points" if metric is Metric.POINTS else f"scaled_{column}"
    actual_column = f"actual_{column}"
    # Titles have no pro-rata analogue — a championship is not a rate.
    if metric is Metric.CHAMPIONSHIPS:
        scaled_column = "actual_championships"

    rows = (
        await db.execute(
            text(
                f"""
                SELECT c.driver_id, d.forename || ' ' || d.surname AS name,
                       d.nationality, c.seasons_active, c.first_year, c.last_year,
                       c.actual_races,
                       c.{actual_column} AS actual, c.{scaled_column} AS scaled,
                       c.{column}_mean AS mean, c.{column}_median AS median,
                       c.{column}_p2_5 AS p2_5, c.{column}_p97_5 AS p97_5
                FROM career_driver_sim c
                JOIN drivers d ON d.driver_id = c.driver_id
                WHERE c.run_id = :run AND c.actual_races >= :min_races
                """
            ),
            {"run": run.run_id, "min_races": min_races},
        )
    ).all()

    return [
        LeaderRow(
            rank=0,
            key=str(row.driver_id),
            label=row.name,
            sublabel=f"{row.first_year}–{row.last_year}",
            actual=row.actual,
            scaled=row.scaled,
            sim=_sim_stat(row.mean, row.median, row.p2_5, row.p97_5),
            seasons_active=row.seasons_active,
            first_year=row.first_year,
            last_year=row.last_year,
        )
        for row in rows
    ]


async def _driver_careers_in_range(
    db: AsyncSession,
    run: RunInfo,
    metric: Metric,
    min_races: int,
    year_from: int,
    year_to: int,
    limit: int,
) -> list[LeaderRow]:
    """Leaderboard restricted to a span of seasons.

    Ranking uses summed per-season means, which is exact — mean(sum) == sum(mean)
    by linearity. Intervals are then recovered from the stored draws for the rows
    that will actually be displayed, since medians and percentiles are not
    additive and cannot be summed from the season summaries.
    """
    if metric is Metric.CHAMPIONSHIPS:
        column = "p_champion"
        actual_expression = (
            "SUM(CASE WHEN se.actual_champion_driver_id = sds.driver_id THEN 1 ELSE 0 END)"
        )
        scaled_expression = actual_expression
        mean_expression = "SUM(sds.p_champion)"
    else:
        column = _SEASON_METRIC_COLUMN[metric]
        actual_expression = f"SUM(sds.actual_{column})"
        scaled_expression = f"SUM(sds.scaled_{'points' if metric is Metric.POINTS else column})"
        mean_expression = f"SUM(sds.{'points' if metric is Metric.POINTS else column}_mean)"

    rows = (
        await db.execute(
            text(
                f"""
                SELECT sds.driver_id, d.forename || ' ' || d.surname AS name,
                       SUM(sds.actual_races) AS races,
                       MIN(sds.year) AS first_year, MAX(sds.year) AS last_year,
                       COUNT(*) AS seasons_active,
                       {actual_expression} AS actual,
                       {scaled_expression} AS scaled,
                       {mean_expression} AS mean
                FROM season_driver_sim sds
                JOIN seasons se ON se.year = sds.year AND se.is_complete = 1
                JOIN drivers d ON d.driver_id = sds.driver_id
                WHERE sds.run_id = :run AND sds.year BETWEEN :y0 AND :y1
                GROUP BY sds.driver_id
                HAVING races >= :min_races
                ORDER BY mean DESC
                LIMIT :limit
                """
            ),
            {
                "run": run.run_id,
                "y0": year_from,
                "y1": year_to,
                "min_races": min_races,
                "limit": limit,
            },
        )
    ).all()
    if not rows:
        return []

    draws = await _decode_range_draws(
        db, run, metric, [int(r.driver_id) for r in rows], year_from, year_to
    )

    leaders = []
    for row in rows:
        summary = draws.get(int(row.driver_id))
        leaders.append(
            LeaderRow(
                rank=0,
                key=str(row.driver_id),
                label=row.name,
                sublabel=f"{row.first_year}–{row.last_year}",
                actual=float(row.actual or 0),
                scaled=float(row.scaled or 0),
                sim=(
                    _sim_stat(summary.mean, summary.median, summary.p2_5, summary.p97_5)
                    if summary
                    else _sim_stat(row.mean, row.mean, row.mean, row.mean)
                ),
                seasons_active=row.seasons_active,
                first_year=row.first_year,
                last_year=row.last_year,
            )
        )
    return leaders


async def _decode_range_draws(
    db: AsyncSession,
    run: RunInfo,
    metric: Metric,
    driver_ids: list[int],
    year_from: int,
    year_to: int,
) -> dict[int, Summary]:
    """Sum stored per-iteration draws over a year range, per driver."""
    rows = (
        await db.execute(
            text(
                """
                SELECT entity_id, data, dtype, n_iterations
                FROM sim_iterations
                WHERE run_id = :run AND entity_type = 'driver' AND metric = :metric
                  AND year BETWEEN :y0 AND :y1
                  AND entity_id IN :ids
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {
                "run": run.run_id,
                "metric": _BLOB_METRIC[metric],
                "y0": year_from,
                "y1": year_to,
                "ids": driver_ids,
            },
        )
    ).all()

    totals: dict[int, np.ndarray] = {}
    for row in rows:
        vector = decode_draws(row.data, row.dtype, row.n_iterations).astype(np.int64)
        entity = int(row.entity_id)
        if entity in totals:
            totals[entity] += vector
        else:
            totals[entity] = vector

    return {entity: Summary.of(vector) for entity, vector in totals.items()}


async def _groups(
    db: AsyncSession, run: RunInfo, metric: Metric, dimension: GroupBy
) -> list[LeaderRow]:
    metric_name = "points_no_fl" if metric is Metric.POINTS else _CAREER_METRIC_COLUMN[metric]
    rows = (
        await db.execute(
            text(
                """
                SELECT group_key, group_label, n_entities, actual, scaled,
                       mean, median, p2_5, p97_5
                FROM group_sim
                WHERE run_id = :run AND dimension = :dimension AND metric = :metric
                """
            ),
            {"run": run.run_id, "dimension": dimension.value, "metric": metric_name},
        )
    ).all()

    return [
        LeaderRow(
            rank=0,
            key=row.group_key,
            label=row.group_label,
            sublabel=f"{row.n_entities} {'team' if dimension is GroupBy.CONSTRUCTOR else 'entrant'}"
            f"{'s' if row.n_entities != 1 else ''}",
            actual=row.actual,
            scaled=row.scaled,
            sim=_sim_stat(row.mean, row.median, row.p2_5, row.p97_5),
            n_entities=row.n_entities,
        )
        for row in rows
    ]


async def leaderboard(
    db: AsyncSession,
    run: RunInfo,
    *,
    metric: Metric,
    group_by: GroupBy,
    basis: Basis,
    min_races: int = DEFAULT_MIN_RACES,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LeaderBoard:
    if group_by is GroupBy.DRIVER:
        if year_from is not None or year_to is not None:
            rows = await _driver_careers_in_range(
                db, run, metric, min_races,
                year_from or 1950, year_to or 2100,
                limit=max(limit + offset, 100),
            )
        else:
            rows = await _driver_careers(db, run, metric, min_races)
    else:
        # Group aggregates cover full history; the year filter is a driver-level
        # control and does not apply to them.
        rows = await _groups(db, run, metric, group_by)

    ordered = _apply_ranks(rows, basis)
    return LeaderBoard(
        metric=metric,
        group_by=group_by,
        basis=basis,
        total=len(ordered),
        min_races=min_races,
        year_from=year_from,
        year_to=year_to,
        run=run,
        rows=ordered[offset : offset + limit],
    )
