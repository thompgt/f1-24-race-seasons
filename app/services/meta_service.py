"""Run metadata and the methodology caveats.

The caveats live here, next to the code that causes them, and are served to the
UI rather than written into the page — so the methodology panel cannot drift out
of step with what the pipeline actually does. Counts are measured from the
database, not hardcoded.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import RunInfo
from app.schemas.meta import Caveat, Meta, MethodStep
from app.sim.scoring import MODERN_POINTS, SPRINT_POINTS


def _scale(points: tuple[int, ...]) -> str:
    return "-".join(str(p) for p in points)


async def build_meta(db: AsyncSession, run: RunInfo) -> Meta:
    async def count(sql: str) -> int:
        return int((await db.execute(text(sql))).scalar_one() or 0)

    span = (await db.execute(text("SELECT MIN(year), MAX(year) FROM seasons"))).one()
    shortest = (
        await db.execute(
            text("SELECT year, n_races FROM seasons ORDER BY n_races ASC, year ASC LIMIT 1")
        )
    ).one()
    longest = (
        await db.execute(
            text("SELECT year, n_races FROM seasons ORDER BY n_races DESC, year DESC LIMIT 1")
        )
    ).one()

    excluded = await count("SELECT COUNT(*) FROM races WHERE excluded = 1")
    shared = await count("SELECT COUNT(*) FROM race_results WHERE is_shared_secondary = 1")
    fl_seasons = await count(
        """SELECT COUNT(DISTINCT r.year) FROM races r
           JOIN race_results rr ON rr.race_id = r.race_id
           WHERE rr.points > rr.points_no_fl"""
    )
    total_seasons = await count("SELECT COUNT(*) FROM seasons")
    in_progress = [
        row.year
        for row in (
            await db.execute(text("SELECT year FROM seasons WHERE is_complete = 0 ORDER BY year"))
        ).all()
    ]

    method = [
        MethodStep(
            title="Resample the season",
            detail=(
                f"For a season that ran R races, draw {run.target_races} race weekends "
                f"with replacement from that season and total each driver's results. "
                f"Repeated {run.n_iterations:,} times from a fixed seed, so the figures "
                f"are reproducible."
            ),
        ),
        MethodStep(
            title="Keep weekends intact",
            detail=(
                "The unit drawn is the whole weekend, so a sprint travels with the "
                "Grand Prix it belongs to and the era's sprint-to-race ratio survives."
            ),
        ),
        MethodStep(
            title="Score every era the same way",
            detail=(
                f"Modern points ({_scale(MODERN_POINTS)}) for the Grand Prix and "
                f"{_scale(SPRINT_POINTS)} for sprints, applied to all seasons. "
                "Historical 'best N results count' rules are not applied — which is "
                "why some titles move before any normalisation."
            ),
        ),
        MethodStep(
            title="Build careers from the draws, not the medians",
            detail=(
                "A career total sums each season's per-iteration draws and takes "
                "percentiles of the result. Summing per-season medians would bias a "
                "long career by several wins, because the median of a sum is not the "
                "sum of the medians."
            ),
        ),
    ]

    caveats = [
        Caveat(
            key="fastest_lap",
            title="The fastest-lap point only exists from 2004",
            detail=(
                f"The source data records fastest laps in {fl_seasons} of {total_seasons} "
                "seasons. Awarding the bonus only where data exists would hand modern "
                "drivers roughly half a point per race that earlier drivers could never "
                "score — the very bias this project corrects. Both totals are stored, and "
                "all-time leaderboards use the fastest-lap-free one."
            ),
        ),
        Caveat(
            key="poles_from_grid",
            title="Poles are taken from the starting grid",
            detail=(
                "Grid position 1 has complete coverage back to 1950, unlike qualifying "
                "data, which begins in 1994. Because the grid is recorded after "
                "penalties, a handful of modern races credit pole to the driver who "
                "actually started first rather than the one who set the fastest lap."
            ),
        ),
        Caveat(
            key="indianapolis",
            title=f"The Indianapolis 500 is excluded ({excluded} races)",
            detail=(
                "It counted toward the World Championship from 1950 to 1960 but ran to "
                "different regulations and drew almost no Formula 1 regulars. The "
                "genuine United States Grands Prix held at the same circuit from 2000 "
                "are kept."
            ),
        ),
        Caveat(
            key="shared_drives",
            title=f"Shared drives credit one driver ({shared} entries affected)",
            detail=(
                "In the 1950s two drivers could share a car and both be classified in "
                "the same position. The modern points system has no equivalent, and a "
                "race must have exactly one winner, so the result goes to the driver "
                "with the stronger season — which recovers Fangio's 24 wins, including "
                "the two he took over mid-race."
            ),
        ),
        Caveat(
            key="drop_scores",
            title="Historical drop-score rules are not applied",
            detail=(
                "Several championships were decided on a driver's best N results rather "
                "than their full total. Scoring every race means eight titles change "
                "hands on the points system alone, before any normalisation — 1988 being "
                "the clearest case, where Prost outscored Senna across the season."
            ),
        ),
    ]

    if in_progress:
        years = ", ".join(str(year) for year in in_progress)
        caveats.append(
            Caveat(
                key="in_progress",
                title=f"{years} is still under way",
                detail=(
                    "A season in progress is shown as a projection from the races run so "
                    "far. It carries no champion and is left out of all-time leaderboards, "
                    "since counting a part-season would credit drivers with a full "
                    f"{run.target_races}-race year they have not had."
                ),
            )
        )

    return Meta(
        run=run,
        first_year=span[0],
        last_year=span[1],
        target_races=run.target_races,
        shortest_season_year=shortest.year,
        shortest_season_races=shortest.n_races,
        longest_season_year=longest.year,
        longest_season_races=longest.n_races,
        data_sources=[
            "Ergast Formula 1 database (1950–2024), via a local CSV export",
            "Jolpica API (api.jolpi.ca) for 2025 onward, and for all sprint results",
        ],
        method=method,
        caveats=caveats,
    )
