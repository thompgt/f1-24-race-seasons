"""Driver-detail queries."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import ConstructorRef, DriverRef, RunInfo, SimStat
from app.schemas.driver import CareerTotals, DriverDetail, DriverSeason


def _stat(row, prefix: str) -> SimStat:
    return SimStat(
        mean=getattr(row, f"{prefix}_mean"),
        median=getattr(row, f"{prefix}_median"),
        p2_5=getattr(row, f"{prefix}_p2_5"),
        p97_5=getattr(row, f"{prefix}_p97_5"),
    )


async def get_driver(db: AsyncSession, driver_id: int, run: RunInfo) -> DriverDetail | None:
    career = (
        await db.execute(
            text(
                """
                SELECT c.*, d.forename, d.surname, d.code, d.nationality, d.dob
                FROM career_driver_sim c
                JOIN drivers d ON d.driver_id = c.driver_id
                WHERE c.run_id = :run AND c.driver_id = :driver
                """
            ),
            {"run": run.run_id, "driver": driver_id},
        )
    ).one_or_none()
    if career is None:
        return None

    season_rows = (
        await db.execute(
            text(
                """
                SELECT sds.*, c.name AS constructor_name, c.nationality AS constructor_nationality,
                       s.actual_champion_driver_id
                FROM season_driver_sim sds
                JOIN seasons s ON s.year = sds.year
                LEFT JOIN constructors c ON c.constructor_id = sds.constructor_id
                WHERE sds.run_id = :run AND sds.driver_id = :driver
                ORDER BY sds.year
                """
            ),
            {"run": run.run_id, "driver": driver_id},
        )
    ).all()

    seasons = [
        DriverSeason(
            year=row.year,
            constructor=(
                ConstructorRef(
                    constructor_id=row.constructor_id,
                    name=row.constructor_name,
                    nationality=row.constructor_nationality,
                )
                if row.constructor_id is not None
                else None
            ),
            races=row.actual_races,
            actual_wins=row.actual_wins,
            actual_podiums=row.actual_podiums,
            actual_poles=row.actual_poles,
            actual_points=row.actual_points_no_fl,
            scaled_wins=row.scaled_wins,
            wins=_stat(row, "wins"),
            podiums=_stat(row, "podiums"),
            poles=_stat(row, "poles"),
            points=_stat(row, "points"),
            p_champion=row.p_champion,
            is_actual_champion=row.actual_champion_driver_id == driver_id,
        )
        for row in season_rows
    ]

    thresholds = json.loads(career.championships_at_least or "{}")

    return DriverDetail(
        driver=DriverRef(
            driver_id=driver_id,
            name=f"{career.forename} {career.surname}",
            code=career.code,
            nationality=career.nationality,
        ),
        dob=career.dob,
        run=run,
        career=CareerTotals(
            seasons=career.seasons_active,
            first_year=career.first_year,
            last_year=career.last_year,
            races=career.actual_races,
            actual_wins=career.actual_wins,
            actual_podiums=career.actual_podiums,
            actual_poles=career.actual_poles,
            actual_points=career.actual_points,
            actual_championships=career.actual_championships,
            scaled_wins=career.scaled_wins,
            scaled_podiums=career.scaled_podiums,
            scaled_poles=career.scaled_poles,
            wins=_stat(career, "wins"),
            podiums=_stat(career, "podiums"),
            poles=_stat(career, "poles"),
            points=_stat(career, "points"),
            championships=_stat(career, "championships"),
            championships_at_least={int(k): v for k, v in thresholds.items()},
        ),
        seasons=seasons,
    )


async def search_drivers(db: AsyncSession, query: str, run: RunInfo, limit: int = 20):
    rows = (
        await db.execute(
            text(
                """
                SELECT c.driver_id, d.forename || ' ' || d.surname AS name, d.code,
                       d.nationality, c.first_year, c.last_year
                FROM career_driver_sim c
                JOIN drivers d ON d.driver_id = c.driver_id
                WHERE c.run_id = :run
                  AND LOWER(d.forename || ' ' || d.surname) LIKE :pattern
                ORDER BY c.wins_median DESC, name
                LIMIT :limit
                """
            ),
            {"run": run.run_id, "pattern": f"%{query.lower()}%", "limit": limit},
        )
    ).all()
    return [
        DriverRef(
            driver_id=row.driver_id,
            name=row.name,
            code=row.code,
            nationality=row.nationality,
        )
        for row in rows
    ]
