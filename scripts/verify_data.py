"""Data-quality report for data/f1.db.

Prints the checks that matter for interpreting the results, and exits non-zero if
a hard invariant is broken. Soft findings (championships that change under modern
points, poles that shift because of grid penalties) are reported, not failed —
they are the app's subject matter, not defects.

    python scripts/verify_data.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402

failures: list[str] = []


def rule(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {actual}" + ("" if ok else f" (expected {expected})"))
    if not ok:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=settings.db_path)
    args = parser.parse_args()

    if not args.db.exists():
        print(f"No database at {args.db}. Run scripts/build_db.py first.")
        return 1

    engine = create_engine(f"sqlite:///{args.db.as_posix()}", future=True)
    with engine.connect() as conn:
        q = lambda sql, **p: conn.execute(text(sql), p)  # noqa: E731
        one = lambda sql, **p: q(sql, **p).scalar_one()  # noqa: E731

        section("Coverage")
        span = q("SELECT MIN(year), MAX(year), COUNT(*) FROM seasons").one()
        print(f"  seasons {span[0]}-{span[1]} ({span[2]} total)")
        rule(
            "seasons with no races",
            one("SELECT COUNT(*) FROM seasons WHERE n_races < 1"),
            0,
        )
        rule(
            "non-excluded races without a pole",
            one("SELECT COUNT(*) FROM races WHERE excluded = 0 AND pole_driver_id IS NULL"),
            0,
        )
        print("  pole sources:", dict(q(
            "SELECT COALESCE(pole_source,'none'), COUNT(*) FROM races GROUP BY 1"
        ).all()))

        section("Exclusions")
        rule(
            "Indianapolis 500 rounds excluded",
            one("SELECT COUNT(*) FROM races WHERE excluded = 1"),
            11,
        )
        for year, name in q(
            "SELECT year, name FROM races WHERE excluded = 1 ORDER BY year"
        ).all():
            print(f"      {year} {name}")

        section("Scoring integrity")
        rule(
            "points awarded to unclassified entries",
            one("SELECT COUNT(*) FROM race_results WHERE position IS NULL AND points > 0"),
            0,
        )
        rule(
            "points awarded to shared-drive co-drivers",
            one("SELECT COUNT(*) FROM race_results WHERE is_shared_secondary = 1 AND points > 0"),
            0,
        )
        rule(
            "races with more than one winner",
            one(
                """SELECT COUNT(*) FROM (
                     SELECT race_id FROM race_results r
                     WHERE race_id IN (SELECT race_id FROM races WHERE excluded = 0)
                     GROUP BY race_id HAVING SUM(is_win) != 1)"""
            ),
            0,
        )
        rule(
            "first year with a fastest-lap point",
            one(
                """SELECT MIN(r.year) FROM races r JOIN race_results rr
                   ON rr.race_id = r.race_id WHERE rr.points > rr.points_no_fl"""
            ),
            2004,
        )
        fl_seasons = one(
            """SELECT COUNT(DISTINCT r.year) FROM races r JOIN race_results rr
               ON rr.race_id = r.race_id WHERE rr.points > rr.points_no_fl"""
        )
        print(
            f"  note: fastest-lap points exist in {fl_seasons} of {span[2]} seasons — "
            "all-time leaderboards default to points_no_fl for this reason"
        )

        section("Shared drives (reported, not failed)")
        print("  co-driver rows flagged:", one(
            "SELECT COUNT(*) FROM race_results WHERE is_shared_secondary = 1"
        ))
        for row in q(
            """SELECT r.year, r.name, d.forename || ' ' || d.surname AS driver, rr.position
               FROM race_results rr
               JOIN races r ON r.race_id = rr.race_id
               JOIN drivers d ON d.driver_id = rr.driver_id
               WHERE rr.is_shared_secondary = 1 AND rr.position <= 3
               ORDER BY r.year, r.round"""
        ).all():
            print(f"      {row.year} {row.name}: {row.driver} (P{row.position}) not credited")

        section("Champions")
        rule(
            "completed seasons missing an actual champion",
            one(
                """SELECT COUNT(*) FROM seasons
                   WHERE is_complete = 1 AND actual_champion_driver_id IS NULL"""
            ),
            0,
        )
        for row in q(
            "SELECT year, n_races FROM seasons WHERE is_complete = 0 ORDER BY year"
        ).all():
            print(
                f"  note: {row.year} is still in progress ({row.n_races} races run) — "
                "shown as a projection, and excluded from all-time leaderboards"
            )
        print("  seasons where the modern scale alone changes the title:")
        changed = 0
        for row in q(
            "SELECT year, actual_champion_driver_id AS champ FROM seasons ORDER BY year"
        ).all():
            standings = q(
                """SELECT rr.driver_id, d.forename || ' ' || d.surname AS driver,
                          SUM(rr.points_no_fl) AS pts, SUM(rr.is_win) AS wins
                   FROM race_results rr
                   JOIN races r ON r.race_id = rr.race_id AND r.excluded = 0
                   JOIN drivers d ON d.driver_id = rr.driver_id
                   WHERE r.year = :y
                   GROUP BY rr.driver_id
                   ORDER BY pts DESC, wins DESC
                   LIMIT 1""",
                y=row.year,
            ).all()
            if not standings or row.champ is None:
                continue
            top = standings[0]
            if top.driver_id != row.champ:
                changed += 1
                actual = one(
                    "SELECT forename || ' ' || surname FROM drivers WHERE driver_id = :d",
                    d=row.champ,
                )
                print(f"      {row.year}: {top.driver} instead of {actual}")
        print(
            f"  {changed} of {span[2]} titles change on the points scale alone, before "
            "any 24-race normalisation"
        )

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All hard invariants hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
