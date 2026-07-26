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

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.ingestion.csv_loader import SourceFrames, load_source_frames  # noqa: E402
from app.models import source as _source  # noqa: E402,F401  (registers tables)

logger = logging.getLogger("build_db")

TABLE_ORDER = [
    ("seasons", "seasons"),
    ("drivers", "drivers"),
    ("constructors", "constructors"),
    ("circuits", "circuits"),
    ("races", "races"),
    ("race_results", "race_results"),
]


def write_frames(engine, frames: SourceFrames) -> None:
    with engine.begin() as conn:
        for table, attr in TABLE_ORDER:
            frame = getattr(frames, attr)
            frame.to_sql(table, conn, if_exists="append", index=False)
            logger.info("%-14s %6d rows", table, len(frame))


def summarise(engine) -> None:
    queries = {
        "seasons": "SELECT COUNT(*) FROM seasons",
        "races (kept)": "SELECT COUNT(*) FROM races WHERE excluded = 0",
        "races (excluded)": "SELECT COUNT(*) FROM races WHERE excluded = 1",
        "results": "SELECT COUNT(*) FROM race_results",
        "shared-drive rows": "SELECT COUNT(*) FROM race_results WHERE is_shared_secondary = 1",
        "poles attributed": "SELECT COUNT(*) FROM races WHERE pole_driver_id IS NOT NULL",
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
    summarise(engine)

    logger.info("Wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
