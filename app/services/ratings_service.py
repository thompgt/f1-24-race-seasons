"""Driver ratings and win difficulty.

Served from `driver_elo` and `driver_race_ratings`, both written by
`scripts/build_elo.py`. These carry no `run_id`: ratings are a deterministic
function of the ingested results, independent of any Monte Carlo run.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.ratings import (
    DriverRating,
    NotableWin,
    RatingBoard,
    RatingPoint,
    RatingRow,
    RatingSort,
)

#: A rating needs a body of results behind it before it means anything, and a
#: single lucky win otherwise tops the difficulty table outright.
DEFAULT_MIN_RACES = 20

#: Ranking a driver's average win difficulty on one or two wins is noise.
MIN_WINS_FOR_DIFFICULTY = 5

_ORDER_BY = {
    RatingSort.PEAK: "e.peak_rating DESC",
    RatingSort.TEAMMATE: "e.peak_teammate_rating DESC",
    RatingSort.VS_FIELD: "e.peak_vs_field DESC",
    RatingSort.QUALITY_WINS: "e.quality_wins DESC",
    RatingSort.DIFFICULTY: "e.mean_win_difficulty DESC",
}


async def leaderboard(
    db: AsyncSession,
    *,
    sort: RatingSort = RatingSort.TEAMMATE,
    min_races: int = DEFAULT_MIN_RACES,
    limit: int = 50,
    offset: int = 0,
) -> RatingBoard:
    # Sorting by average difficulty additionally requires enough wins to average.
    win_filter = (
        f"AND e.wins >= {MIN_WINS_FOR_DIFFICULTY}" if sort is RatingSort.DIFFICULTY else ""
    )

    rows = (
        await db.execute(
            text(
                f"""
                SELECT e.driver_id, d.forename || ' ' || d.surname AS name,
                       d.nationality, e.first_year, e.last_year, e.races,
                       e.peak_rating, e.peak_teammate_rating, e.peak_vs_field,
                       e.final_rating, e.wins, e.quality_wins, e.mean_win_difficulty,
                       e.teammate_races, e.teammate_wins
                FROM driver_elo e
                JOIN drivers d ON d.driver_id = e.driver_id
                WHERE e.races >= :min_races {win_filter}
                ORDER BY {_ORDER_BY[sort]}
                """
            ),
            {"min_races": min_races},
        )
    ).all()

    ranked = [
        RatingRow(
            rank=position,
            driver_id=row.driver_id,
            name=row.name,
            nationality=row.nationality,
            first_year=row.first_year,
            last_year=row.last_year,
            races=row.races,
            peak_rating=row.peak_rating,
            peak_teammate_rating=row.peak_teammate_rating,
            peak_vs_field=row.peak_vs_field,
            final_rating=row.final_rating,
            wins=row.wins,
            quality_wins=row.quality_wins,
            mean_win_difficulty=row.mean_win_difficulty,
            teammate_races=row.teammate_races,
            teammate_wins=row.teammate_wins,
        )
        for position, row in enumerate(rows, start=1)
    ]

    return RatingBoard(
        sort=sort,
        min_races=min_races,
        total=len(ranked),
        rows=ranked[offset : offset + limit],
    )


async def notable_wins(
    db: AsyncSession, *, hardest: bool = True, limit: int = 15
) -> list[NotableWin]:
    """The most and least contested wins in the record.

    A chaotic race counts as contested, which is the honest reading rather than a
    flaw: a driver who was expected to finish eighth and won did beat a field
    that had every reason to beat them, whatever the weather was doing.
    """
    order = "DESC" if hardest else "ASC"
    rows = (
        await db.execute(
            text(
                f"""
                SELECT rr.race_id, r.year, r.name AS race_name,
                       rr.driver_id, d.forename || ' ' || d.surname AS driver_name,
                       c.name AS constructor_name,
                       rr.quality_win AS difficulty,
                       rt.expected_position,
                       (SELECT COUNT(*) FROM race_results x WHERE x.race_id = rr.race_id
                        AND x.is_shared_secondary = 0) AS starters
                FROM race_results rr
                JOIN races r ON r.race_id = rr.race_id
                JOIN drivers d ON d.driver_id = rr.driver_id
                LEFT JOIN constructors c ON c.constructor_id = rr.constructor_id
                JOIN driver_race_ratings rt
                  ON rt.race_id = rr.race_id AND rt.driver_id = rr.driver_id
                WHERE rr.quality_win > 0
                ORDER BY rr.quality_win {order}
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).all()

    return [
        NotableWin(
            race_id=row.race_id,
            year=row.year,
            race_name=row.race_name,
            driver_id=row.driver_id,
            driver_name=row.driver_name,
            constructor_name=row.constructor_name,
            difficulty=row.difficulty,
            expected_position=row.expected_position,
            starters=row.starters,
        )
        for row in rows
    ]


async def driver_rating(db: AsyncSession, driver_id: int) -> DriverRating | None:
    """One driver's rating summary and full race-by-race trace."""
    summary = (
        await db.execute(
            text(
                """
                SELECT peak_rating, peak_teammate_rating, peak_vs_field, final_rating,
                       final_teammate_rating, wins, quality_wins, mean_win_difficulty,
                       teammate_races, teammate_wins, races
                FROM driver_elo WHERE driver_id = :driver
                """
            ),
            {"driver": driver_id},
        )
    ).one_or_none()
    if summary is None:
        return None

    # Rank among drivers with a comparable body of work, so a two-race career
    # cannot outrank a twenty-season one on a single team-mate comparison.
    teammate_rank = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) + 1 FROM driver_elo
                WHERE races >= :min_races AND peak_teammate_rating > :rating
                """
            ),
            {"min_races": DEFAULT_MIN_RACES, "rating": summary.peak_teammate_rating},
        )
    ).scalar_one()

    trace = (
        await db.execute(
            text(
                """
                SELECT rt.race_id, rt.year, rt.rating_after, rt.teammate_rating_after,
                       rt.position, rr.quality_win
                FROM driver_race_ratings rt
                JOIN races r ON r.race_id = rt.race_id
                LEFT JOIN race_results rr
                  ON rr.race_id = rt.race_id AND rr.driver_id = rt.driver_id
                WHERE rt.driver_id = :driver
                ORDER BY rt.year, r.round
                """
            ),
            {"driver": driver_id},
        )
    ).all()

    return DriverRating(
        peak_rating=summary.peak_rating,
        peak_teammate_rating=summary.peak_teammate_rating,
        peak_vs_field=summary.peak_vs_field,
        final_rating=summary.final_rating,
        final_teammate_rating=summary.final_teammate_rating,
        wins=summary.wins,
        quality_wins=summary.quality_wins,
        mean_win_difficulty=summary.mean_win_difficulty,
        teammate_races=summary.teammate_races,
        teammate_wins=summary.teammate_wins,
        teammate_rank=(
            int(teammate_rank) if summary.races >= DEFAULT_MIN_RACES else None
        ),
        trace=[
            RatingPoint(
                race_id=row.race_id,
                year=row.year,
                rating=row.rating_after,
                teammate_rating=row.teammate_rating_after,
                position=row.position,
                win_difficulty=row.quality_win if row.quality_win else None,
            )
            for row in trace
        ],
    )
