"""Download and cache Jolpica data into data/raw/.

Separated from build_db.py so the network step is explicit and re-runnable: once
cached, rebuilding the database needs no connectivity.

    python scripts/fetch_jolpica.py --seasons 2025 2026 --sprint-seasons 2021-2026
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.ingestion.jolpica_client import JolpicaClient  # noqa: E402

logger = logging.getLogger("fetch_jolpica")

#: Seasons the CSV dump does not cover.
DEFAULT_SEASONS = (2025, 2026)
#: Sprints began in 2021 and are absent from the CSV dump entirely.
DEFAULT_SPRINT_SEASONS = tuple(range(2021, 2027))


def parse_years(values: list[str]) -> list[int]:
    """Accept individual years and `start-end` ranges."""
    years: list[int] = []
    for value in values:
        if "-" in value:
            start, end = value.split("-", 1)
            years.extend(range(int(start), int(end) + 1))
        else:
            years.append(int(value))
    return sorted(set(years))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="*", default=[str(y) for y in DEFAULT_SEASONS])
    parser.add_argument(
        "--sprint-seasons", nargs="*", default=[str(y) for y in DEFAULT_SPRINT_SEASONS]
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-fetch even if cached — needed for a season still in progress",
    )
    parser.add_argument("--raw-dir", type=Path, default=settings.raw_dir)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    seasons = parse_years(args.seasons)
    sprint_seasons = parse_years(args.sprint_seasons)

    with JolpicaClient(args.raw_dir) as client:
        for year in seasons:
            client.fetch(f"{year}/races", refresh=args.refresh)
            client.fetch(f"{year}/results", refresh=args.refresh)
            client.fetch(f"{year}/qualifying", refresh=args.refresh)
            client.fetch_standings(year, refresh=args.refresh)
        for year in sprint_seasons:
            client.fetch(f"{year}/sprint", refresh=args.refresh)

    logger.info("Cached under %s", args.raw_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
