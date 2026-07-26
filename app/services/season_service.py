"""Season-tab queries. Reads precomputed rows only — nothing simulates here."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import ConstructorRef, DriverRef, RunInfo, SimStat
from app.schemas.season import (
    ActualTotals,
    ChampionOdds,
    ExcludedRace,
    ScaledTotals,
    SeasonConstructorRow,
    SeasonDetail,
    SeasonDriverRow,
    SeasonSummary,
)

#: A driver contesting less than this share of the season is flagged, so a one-off
#: winner is not mistaken for a front-runner.
PART_SEASON_THRESHOLD = 0.5


async def current_run(db: AsyncSession) -> RunInfo | None:
    """The newest complete run. Incomplete runs are never served."""
    row = (
        await db.execute(
            text(
                """
                SELECT run_id, created_at, n_iterations, target_races, master_seed,
                       seasons_simulated
                FROM sim_runs WHERE is_complete = 1
                ORDER BY run_id DESC LIMIT 1
                """
            )
        )
    ).one_or_none()
    return RunInfo(**row._mapping) if row else None


def _driver_ref(row) -> DriverRef:
    return DriverRef(
        driver_id=row.driver_id,
        name=f"{row.forename} {row.surname}",
        code=row.code,
        nationality=row.nationality,
    )


async def list_seasons(db: AsyncSession, run: RunInfo) -> list[SeasonSummary]:
    rows = (
        await db.execute(
            text(
                """
                SELECT s.year, s.n_races, s.n_sprints, s.is_complete, s.source,
                       ac.driver_id AS actual_id, ac.forename AS actual_forename,
                       ac.surname AS actual_surname, ac.code AS actual_code,
                       ac.nationality AS actual_nationality,
                       lc.driver_id, lc.forename, lc.surname, lc.code, lc.nationality,
                       best.p_champion
                FROM seasons s
                LEFT JOIN drivers ac ON ac.driver_id = s.actual_champion_driver_id
                LEFT JOIN (
                    SELECT year, driver_id, p_champion,
                           ROW_NUMBER() OVER (
                               PARTITION BY year ORDER BY p_champion DESC, driver_id
                           ) AS rank
                    FROM season_driver_sim WHERE run_id = :run
                ) best ON best.year = s.year AND best.rank = 1
                LEFT JOIN drivers lc ON lc.driver_id = best.driver_id
                WHERE s.n_races > 0
                ORDER BY s.year
                """
            ),
            {"run": run.run_id},
        )
    ).all()

    seasons = []
    for row in rows:
        actual = (
            DriverRef(
                driver_id=row.actual_id,
                name=f"{row.actual_forename} {row.actual_surname}",
                code=row.actual_code,
                nationality=row.actual_nationality,
            )
            if row.actual_id is not None
            else None
        )
        likeliest = _driver_ref(row) if row.driver_id is not None else None
        seasons.append(
            SeasonSummary(
                year=row.year,
                n_races=row.n_races,
                n_sprints=row.n_sprints,
                is_complete=bool(row.is_complete),
                source=row.source,
                actual_champion=actual,
                likeliest_champion=likeliest,
                likeliest_champion_probability=row.p_champion or 0.0,
                champion_changes=bool(
                    actual and likeliest and actual.driver_id != likeliest.driver_id
                ),
            )
        )
    return seasons


async def get_season(db: AsyncSession, year: int, run: RunInfo) -> SeasonDetail | None:
    season = (
        await db.execute(
            text(
                """
                SELECT s.year, s.n_races, s.n_sprints, s.is_complete,
                       d.driver_id, d.forename, d.surname, d.code, d.nationality
                FROM seasons s
                LEFT JOIN drivers d ON d.driver_id = s.actual_champion_driver_id
                WHERE s.year = :year
                """
            ),
            {"year": year},
        )
    ).one_or_none()
    if season is None:
        return None

    champion = _driver_ref(season) if season.driver_id is not None else None

    excluded = [
        ExcludedRace(name=row.name, reason=row.exclusion_reason)
        for row in (
            await db.execute(
                text(
                    """
                    SELECT name, exclusion_reason FROM races
                    WHERE year = :year AND excluded = 1 ORDER BY round
                    """
                ),
                {"year": year},
            )
        ).all()
    ]

    driver_rows = (
        await db.execute(
            text(
                """
                SELECT sds.*, d.forename, d.surname, d.code, d.nationality,
                       c.name AS constructor_name, c.nationality AS constructor_nationality,
                       cont.p_champion AS p_continued, cont.extra_races,
                       cont.form_strength
                FROM season_driver_sim sds
                JOIN drivers d ON d.driver_id = sds.driver_id
                LEFT JOIN constructors c ON c.constructor_id = sds.constructor_id
                LEFT JOIN season_continuation_sim cont
                  ON cont.run_id = sds.run_id AND cont.year = sds.year
                 AND cont.driver_id = sds.driver_id
                WHERE sds.run_id = :run AND sds.year = :year
                ORDER BY sds.points_median DESC, sds.wins_median DESC
                """
            ),
            {"run": run.run_id, "year": year},
        )
    ).all()

    drivers = [
        SeasonDriverRow(
            driver=_driver_ref(row),
            constructor=(
                ConstructorRef(
                    constructor_id=row.constructor_id,
                    name=row.constructor_name,
                    nationality=row.constructor_nationality,
                )
                if row.constructor_id is not None
                else None
            ),
            actual=ActualTotals(
                races=row.actual_races,
                points=row.actual_points,
                points_no_fl=row.actual_points_no_fl,
                wins=row.actual_wins,
                podiums=row.actual_podiums,
                poles=row.actual_poles,
                position=row.actual_position,
            ),
            scaled=ScaledTotals(
                points=row.scaled_points,
                wins=row.scaled_wins,
                podiums=row.scaled_podiums,
                poles=row.scaled_poles,
            ),
            points=SimStat(
                mean=row.points_mean, median=row.points_median,
                p2_5=row.points_p2_5, p97_5=row.points_p97_5,
            ),
            wins=SimStat(
                mean=row.wins_mean, median=row.wins_median,
                p2_5=row.wins_p2_5, p97_5=row.wins_p97_5,
            ),
            podiums=SimStat(
                mean=row.podiums_mean, median=row.podiums_median,
                p2_5=row.podiums_p2_5, p97_5=row.podiums_p97_5,
            ),
            poles=SimStat(
                mean=row.poles_mean, median=row.poles_median,
                p2_5=row.poles_p2_5, p97_5=row.poles_p97_5,
            ),
            entries_mean=row.entries_mean,
            entries_p2_5=row.entries_p2_5,
            entries_p97_5=row.entries_p97_5,
            p_champion=row.p_champion,
            p_champion_continued=(
                row.p_continued if (row.extra_races or 0) > 0 else None
            ),
            form_strength=row.form_strength or 0.0,
            p_top3=row.p_top3,
            is_actual_champion=bool(champion and champion.driver_id == row.driver_id),
            is_part_season=row.actual_races < PART_SEASON_THRESHOLD * season.n_races,
        )
        for row in driver_rows
    ]

    constructor_rows = (
        await db.execute(
            text(
                """
                SELECT scs.*, c.name, c.nationality
                FROM season_constructor_sim scs
                JOIN constructors c ON c.constructor_id = scs.constructor_id
                WHERE scs.run_id = :run AND scs.year = :year
                ORDER BY scs.points_median DESC, scs.wins_median DESC
                """
            ),
            {"run": run.run_id, "year": year},
        )
    ).all()

    constructors = [
        SeasonConstructorRow(
            constructor=ConstructorRef(
                constructor_id=row.constructor_id, name=row.name, nationality=row.nationality
            ),
            actual_points=row.actual_points,
            actual_wins=row.actual_wins,
            actual_podiums=row.actual_podiums,
            scaled_points=row.scaled_points,
            scaled_wins=row.scaled_wins,
            scaled_podiums=row.scaled_podiums,
            points=SimStat(
                mean=row.points_mean, median=row.points_median,
                p2_5=row.points_p2_5, p97_5=row.points_p97_5,
            ),
            wins=SimStat(
                mean=row.wins_mean, median=row.wins_median,
                p2_5=row.wins_p2_5, p97_5=row.wins_p97_5,
            ),
            podiums=SimStat(
                mean=row.podiums_mean, median=row.podiums_median,
                p2_5=row.podiums_p2_5, p97_5=row.podiums_p97_5,
            ),
            p_champion=row.p_champion,
        )
        for row in constructor_rows
    ]

    return SeasonDetail(
        year=season.year,
        n_races=season.n_races,
        n_sprints=season.n_sprints,
        target_races=run.target_races,
        is_complete=bool(season.is_complete),
        actual_champion=champion,
        excluded_races=excluded,
        run=run,
        drivers=drivers,
        constructors=constructors,
    )


async def champion_odds(db: AsyncSession, year: int, run: RunInfo) -> list[ChampionOdds]:
    rows = (
        await db.execute(
            text(
                """
                SELECT sds.driver_id, sds.p_champion, d.forename, d.surname, d.code,
                       d.nationality, s.actual_champion_driver_id,
                       c.p_champion AS p_continued, c.extra_races,
                       c.banked_points, c.form_strength
                FROM season_driver_sim sds
                JOIN drivers d ON d.driver_id = sds.driver_id
                JOIN seasons s ON s.year = sds.year
                LEFT JOIN season_continuation_sim c
                  ON c.run_id = sds.run_id AND c.year = sds.year
                 AND c.driver_id = sds.driver_id
                WHERE sds.run_id = :run AND sds.year = :year
                  AND (sds.p_champion > 0 OR c.p_champion > 0)
                ORDER BY sds.p_champion DESC
                """
            ),
            {"run": run.run_id, "year": year},
        )
    ).all()
    return [
        ChampionOdds(
            driver=_driver_ref(row),
            p_champion=row.p_champion,
            # A full-length season has no remainder to race, so the continuation
            # is degenerate rather than informative and is withheld.
            p_champion_continued=(
                row.p_continued if (row.extra_races or 0) > 0 else None
            ),
            banked_points=row.banked_points or 0.0,
            form_strength=row.form_strength or 0.0,
            is_actual_champion=row.driver_id == row.actual_champion_driver_id,
        )
        for row in rows
    ]
