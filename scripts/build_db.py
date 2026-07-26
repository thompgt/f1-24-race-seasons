"""Build data/f1.db from the Ergast CSV dump.

Destructive by design: the database is a build artifact, rebuilt from scratch
rather than migrated. Nothing under data/ is committed.

    python scripts/build_db.py --csv-dir "C:/Users/thoma/F1_points_application"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import bindparam, create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.ingestion.csv_loader import load_source_frames  # noqa: E402
from app.ingestion.normalize import IdRegistry, load_jolpica_frames  # noqa: E402
from app.models import source as _source  # noqa: E402,F401  (registers tables)
from scripts.build_elo import build as build_elo  # noqa: E402

logger = logging.getLogger("build_db")

#: Seasons the CSV dump does not cover at all.
JOLPICA_SEASONS = [2025, 2026]
#: Sprints began in 2021 and are absent from the CSV dump for every year.
JOLPICA_SPRINT_SEASONS = list(range(2021, 2027))

TABLE_ORDER = [
    ("seasons", "seasons"),
    ("drivers", "drivers"),
    ("constructors", "constructors"),
    ("circuits", "circuits"),
    ("races", "races"),
    ("race_results", "race_results"),
    ("sprint_results", "sprint_results"),
    ("qualifying", "qualifying"),
]


def write_frames(engine, frames) -> None:
    with engine.begin() as conn:
        for table, attr in TABLE_ORDER:
            frame = getattr(frames, attr, None)
            if frame is None or frame.empty:
                continue
            frame.to_sql(table, conn, if_exists="append", index=False)
            logger.info("%-16s %6d rows", table, len(frame))


def add_jolpica(engine, frames, raw_dir: Path, seasons: list[int], sprint_seasons: list[int]) -> None:
    """Top up the CSV-era data with everything Jolpica has that it does not."""
    drivers = IdRegistry(dict(zip(frames.drivers["driver_ref"], frames.drivers["driver_id"])))
    constructors = IdRegistry(
        dict(zip(frames.constructors["constructor_ref"], frames.constructors["constructor_id"]))
    )
    circuits = IdRegistry(
        dict(zip(frames.circuits["circuit_ref"], frames.circuits["circuit_id"]))
    )
    existing_races = {
        (int(year), int(rnd)): int(race_id)
        for year, rnd, race_id in zip(
            frames.races["year"], frames.races["round"], frames.races["race_id"]
        )
    }
    next_race_id = int(frames.races["race_id"].max()) + 1

    jolpica = load_jolpica_frames(
        raw_dir,
        seasons=seasons,
        sprint_seasons=sprint_seasons,
        drivers=drivers,
        constructors=constructors,
        circuits=circuits,
        existing_races=existing_races,
        next_race_id=next_race_id,
    )
    write_frames(engine, jolpica)

    # Sprints for 2021-2024 attach to races the CSV dump already wrote.
    with engine.begin() as conn:
        if jolpica.existing_races_with_sprints:
            conn.execute(
                text("UPDATE races SET has_sprint = 1 WHERE race_id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": jolpica.existing_races_with_sprints},
            )
            logger.info(
                "%-16s %6d races flagged", "has_sprint", len(jolpica.existing_races_with_sprints)
            )
        for year, count in jolpica.existing_season_sprint_counts.items():
            conn.execute(
                text("UPDATE seasons SET n_sprints = :n WHERE year = :y"),
                {"n": count, "y": year},
            )


def summarise(engine) -> None:
    queries = {
        "seasons": "SELECT COUNT(*) FROM seasons",
        "races (kept)": "SELECT COUNT(*) FROM races WHERE excluded = 0",
        "races (excluded)": "SELECT COUNT(*) FROM races WHERE excluded = 1",
        "results": "SELECT COUNT(*) FROM race_results",
        "shared-drive rows": "SELECT COUNT(*) FROM race_results WHERE is_shared_secondary = 1",
        "poles attributed": "SELECT COUNT(*) FROM races WHERE pole_driver_id IS NOT NULL",
        "sprint results": "SELECT COUNT(*) FROM sprint_results",
        "sprint weekends": "SELECT COUNT(*) FROM races WHERE has_sprint = 1",
        "in-progress seasons": "SELECT COUNT(*) FROM seasons WHERE is_complete = 0",
    }
    with engine.connect() as conn:
        for label, sql in queries.items():
            logger.info("%-20s %s", label, conn.execute(text(sql)).scalar_one())
        span = conn.execute(text("SELECT MIN(year), MAX(year) FROM seasons")).one()
        logger.info("%-20s %s-%s", "season span", *span)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir", type=Path, default=settings.csv_dir)
    parser.add_argument("--out", type=Path, default=settings.db_path)
    parser.add_argument("--raw-dir", type=Path, default=settings.raw_dir)
    parser.add_argument(
        "--skip-jolpica",
        action="store_true",
        help="build from the CSV dump alone, stopping at 2024",
    )
    parser.add_argument(
        "--skip-elo",
        action="store_true",
        help="skip rating drivers; quality-adjusted wins will all be zero",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        logger.info("Removing existing %s", args.out)
        args.out.unlink()

    logger.info("Reading CSV dump from %s", args.csv_dir)
    frames = load_source_frames(args.csv_dir)

    engine = create_engine(f"sqlite:///{args.out.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    write_frames(engine, frames)

    if args.skip_jolpica:
        logger.info("Skipping Jolpica top-up; data stops at 2024")
    elif not args.raw_dir.exists() or not any(args.raw_dir.glob("*.json")):
        logger.warning(
            "No cached Jolpica data in %s — run scripts/fetch_jolpica.py to include "
            "2025+ and sprint results",
            args.raw_dir,
        )
    else:
        logger.info("Merging Jolpica data from %s", args.raw_dir)
        add_jolpica(
            engine,
            frames,
            args.raw_dir,
            seasons=JOLPICA_SEASONS,
            sprint_seasons=JOLPICA_SPRINT_SEASONS,
        )

    if args.skip_elo:
        logger.info("Skipping Elo build; quality_win stays zero for every result")
    else:
        # Ratings depend only on the ingested results, and run_simulations.py
        # reads quality_win off them, so this has to happen before any run.
        logger.info("Rating drivers and scoring win difficulty")
        build_elo(engine)

    summarise(engine)

    logger.info("Wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
