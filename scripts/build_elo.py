"""Rate every driver and score the difficulty of every win, into data/f1.db.

    python scripts/build_elo.py

Reads the ingested source tables, replays the whole history through
`app.sim.elo`, and writes three things back:

  * `driver_race_ratings` — ratings into and out of every race
  * `driver_elo`          — career peaks and win-difficulty summaries
  * `race_results.quality_win` — per-win credit, which the bootstrap then
    resamples as an ordinary additive metric

Ratings depend only on the source results, so this is deterministic and carries
no run_id. It must run *before* `run_simulations.py`, which reads `quality_win`
off the results; `build_db.py` invokes it automatically at the end of an ingest.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models import source as _source  # noqa: E402,F401  (registers tables)
from app.sim.elo import (  # noqa: E402
    Race,
    RaceEntry,
    peak_ratings,
    rate_with_priors,
    win_difficulty,
)

logger = logging.getLogger("build_elo")

_RESULTS = text(
    """
    SELECT r.race_id, r.year, r.round,
           rr.driver_id, rr.constructor_id, rr.position
    FROM races r
    JOIN race_results rr ON rr.race_id = r.race_id
    WHERE r.excluded = 0 AND rr.is_shared_secondary = 0
    ORDER BY r.year, r.round
    """
)


def load_races(conn) -> list[Race]:
    """Every rateable race in calendar order.

    Excluded rounds are left out for the same reason they are left out of the
    simulation — the Indy 500 shared almost no entrants with the championship, so
    rating its field against F1 regulars would connect two populations that never
    actually raced each other.

    Shared-drive co-drivers are dropped too: they finished in the same classified
    position as the driver they shared with, which is not a result either of them
    earned over the other.
    """
    entries: dict[int, list[RaceEntry]] = {}
    meta: dict[int, tuple[int, int]] = {}

    for row in conn.execute(_RESULTS).all():
        entries.setdefault(row.race_id, []).append(
            RaceEntry(
                driver_id=int(row.driver_id),
                constructor_id=None if row.constructor_id is None else int(row.constructor_id),
                position=None if row.position is None else int(row.position),
            )
        )
        meta[row.race_id] = (int(row.year), int(row.round))

    races = [
        Race(race_id=race_id, year=meta[race_id][0], round=meta[race_id][1], entries=tuple(items))
        for race_id, items in entries.items()
    ]
    races.sort(key=lambda r: (r.year, r.round, r.race_id))
    return races


def teammate_records(races: list[Race]) -> dict[int, tuple[int, int]]:
    """Head-to-head team-mate record per driver: (races compared, times ahead)."""
    record: dict[int, list[int]] = {}
    for race in races:
        classified = [e for e in race.entries if e.position is not None]
        for i, a in enumerate(classified):
            for b in classified[i + 1 :]:
                if a.constructor_id is None or a.constructor_id != b.constructor_id:
                    continue
                for driver, ahead in ((a.driver_id, a.position < b.position),
                                      (b.driver_id, b.position < a.position)):
                    slot = record.setdefault(driver, [0, 0])
                    slot[0] += 1
                    slot[1] += int(ahead)
    return {driver: (total, wins) for driver, (total, wins) in record.items()}


def build(engine, *, passes: int = 2) -> int:
    """Rate every driver and write the ratings back. Returns races rated."""
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        races = load_races(conn)
        if not races:
            raise ValueError("No rateable races found — ingest the source data first")
        logger.info(
            "rating %d races, %d entries, %d-%d",
            len(races),
            sum(len(r.entries) for r in races),
            races[0].year,
            races[-1].year,
        )

        result = rate_with_priors(races, passes=passes)
        difficulty = win_difficulty(result.snapshots)
        peaks = peak_ratings(result.snapshots)
        head_to_head = teammate_records(races)

        conn.execute(text("DELETE FROM driver_race_ratings"))
        conn.execute(text("DELETE FROM driver_elo"))

        conn.execute(
            text(
                """
                INSERT INTO driver_race_ratings
                    (race_id, driver_id, year, rating_before, rating_after,
                     teammate_rating_before, teammate_rating_after, rating_vs_field,
                     expected_position, position)
                VALUES (:race_id, :driver_id, :year, :rb, :ra, :tb, :ta, :vs, :ep, :pos)
                """
            ),
            [
                {
                    "race_id": s.race_id,
                    "driver_id": s.driver_id,
                    "year": s.year,
                    "rb": s.rating_before,
                    "ra": s.rating_after,
                    "tb": s.teammate_rating_before,
                    "ta": s.teammate_rating_after,
                    "vs": s.rating_vs_field,
                    "ep": s.expected_position,
                    "pos": s.position,
                }
                for s in result.snapshots
            ],
        )
        logger.info("driver_race_ratings  %6d rows", len(result.snapshots))

        # Win credit back onto the results, so the bootstrap can resample it.
        conn.execute(text("UPDATE race_results SET quality_win = 0.0"))
        conn.execute(
            text(
                """
                UPDATE race_results SET quality_win = :credit
                WHERE race_id = :race_id AND driver_id = :driver_id
                """
            ),
            [
                {"race_id": race_id, "driver_id": driver_id, "credit": credit}
                for (race_id, driver_id), credit in difficulty.items()
            ],
        )
        logger.info("quality_win          %6d wins scored", len(difficulty))

        years: dict[int, list[int]] = {}
        wins: dict[int, int] = {}
        quality: dict[int, float] = {}
        for snapshot in result.snapshots:
            years.setdefault(snapshot.driver_id, []).append(snapshot.year)
        for (race_id, driver_id), credit in difficulty.items():
            wins[driver_id] = wins.get(driver_id, 0) + 1
            quality[driver_id] = quality.get(driver_id, 0.0) + credit

        conn.execute(
            text(
                """
                INSERT INTO driver_elo
                    (driver_id, races, first_year, last_year, peak_rating,
                     peak_teammate_rating, peak_vs_field, final_rating,
                     final_teammate_rating, wins, quality_wins, mean_win_difficulty,
                     teammate_races, teammate_wins)
                VALUES (:driver_id, :races, :first, :last, :peak, :peak_tm, :peak_vs,
                        :final, :final_tm, :wins, :quality, :mean_diff, :tm_races, :tm_wins)
                """
            ),
            [
                {
                    "driver_id": driver_id,
                    "races": int(peak["races"]),
                    "first": min(years[driver_id]),
                    "last": max(years[driver_id]),
                    "peak": peak["peak"],
                    "peak_tm": peak["peak_teammate"],
                    "peak_vs": peak["peak_vs_field"],
                    "final": peak["final"],
                    "final_tm": peak["final_teammate"],
                    "wins": wins.get(driver_id, 0),
                    "quality": quality.get(driver_id, 0.0),
                    "mean_diff": (
                        quality[driver_id] / wins[driver_id] if wins.get(driver_id) else None
                    ),
                    "tm_races": head_to_head.get(driver_id, (0, 0))[0],
                    "tm_wins": head_to_head.get(driver_id, (0, 0))[1],
                }
                for driver_id, peak in peaks.items()
            ],
        )
        logger.info("driver_elo           %6d drivers", len(peaks))

    return len(races)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=settings.db_path)
    parser.add_argument(
        "--passes",
        type=int,
        default=2,
        help="rating passes; the second seeds 1950 from data rather than a flat default",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.db.exists():
        logger.error("No database at %s. Run scripts/build_db.py first.", args.db)
        return 1

    engine = create_engine(f"sqlite:///{args.db.as_posix()}", future=True)
    build(engine, passes=args.passes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
