"""Checks on the Jolpica top-up: seasons past 2024, and sprints for every era.

Skipped when the database was built with --skip-jolpica.
"""

from __future__ import annotations

import pytest

from app.models.source import JOLPICA_ID_BASE
from tests.conftest import scalar


@pytest.fixture(autouse=True)
def _requires_jolpica(db):
    if scalar(db, "SELECT COUNT(*) FROM seasons WHERE source = 'jolpica'") == 0:
        pytest.skip("database built without the Jolpica top-up")


def test_2025_is_complete_with_the_real_champion(db):
    row = db.exec_driver_sql(
        """
        SELECT s.n_races, s.n_sprints, s.is_complete, d.driver_ref
        FROM seasons s LEFT JOIN drivers d ON d.driver_id = s.actual_champion_driver_id
        WHERE s.year = 2025
        """
    ).one()
    assert row == (24, 6, 1, "norris")


def test_in_progress_seasons_have_no_champion(db):
    """A title cannot be attributed before the season ends."""
    bad = scalar(
        db,
        """
        SELECT COUNT(*) FROM seasons
        WHERE is_complete = 0 AND actual_champion_driver_id IS NOT NULL
        """,
    )
    assert bad == 0


def test_completed_seasons_all_have_a_champion(db):
    missing = scalar(
        db,
        """
        SELECT COUNT(*) FROM seasons
        WHERE is_complete = 1 AND actual_champion_driver_id IS NULL
        """,
    )
    assert missing == 0


def test_sprint_results_exist_from_2021(db):
    span = db.exec_driver_sql(
        """
        SELECT MIN(r.year), MAX(r.year) FROM sprint_results sr
        JOIN races r ON r.race_id = sr.race_id
        """
    ).one()
    assert span[0] == 2021


def test_sprints_attach_to_csv_era_races(db):
    """2021-2024 sprints graft onto races the CSV dump already wrote.

    Those races predate the Jolpica id range, so a non-zero count here proves
    the (year, round) join worked rather than creating duplicate races.
    """
    grafted = scalar(
        db,
        f"""
        SELECT COUNT(DISTINCT sr.race_id) FROM sprint_results sr
        WHERE sr.race_id < {JOLPICA_ID_BASE}
          AND sr.race_id IN (SELECT race_id FROM races WHERE year <= 2024)
        """,
    )
    assert grafted == 18


def test_sprint_weekends_are_flagged_on_the_race(db):
    mismatch = scalar(
        db,
        """
        SELECT COUNT(*) FROM races r
        WHERE (r.has_sprint = 1) !=
              (EXISTS (SELECT 1 FROM sprint_results s WHERE s.race_id = r.race_id))
        """,
    )
    assert mismatch == 0


def test_sprint_points_use_the_sprint_scale(db):
    """Max 8 for a sprint win, against 25 for a Grand Prix."""
    assert scalar(db, "SELECT MAX(points) FROM sprint_results") == 8.0
    winners = scalar(
        db, "SELECT COUNT(*) FROM sprint_results WHERE position = 1 AND points != 8.0"
    )
    assert winners == 0


def test_new_drivers_get_ids_above_the_jolpica_base(db):
    """Drivers already in the CSV dump keep their original id."""
    verstappen = scalar(db, "SELECT driver_id FROM drivers WHERE driver_ref = 'max_verstappen'")
    assert verstappen < JOLPICA_ID_BASE

    rookies = scalar(db, f"SELECT COUNT(*) FROM drivers WHERE driver_id >= {JOLPICA_ID_BASE}")
    assert rookies > 0


def test_driver_refs_are_unique(db):
    """A Jolpica driver re-inserted under a new id would double their career."""
    dupes = scalar(
        db,
        "SELECT COUNT(*) FROM (SELECT driver_ref FROM drivers GROUP BY driver_ref HAVING COUNT(*) > 1)",
    )
    assert dupes == 0


def test_jolpica_races_have_poles_too(db):
    missing = scalar(
        db,
        """
        SELECT COUNT(*) FROM races
        WHERE year >= 2025 AND excluded = 0 AND pole_driver_id IS NULL
        """,
    )
    assert missing == 0


def test_no_points_awarded_to_unclassified_jolpica_entries(db):
    leaked = scalar(
        db,
        """
        SELECT COUNT(*) FROM race_results rr
        JOIN races r ON r.race_id = rr.race_id
        WHERE r.year >= 2025 AND rr.position IS NULL AND rr.points > 0
        """,
    )
    assert leaked == 0
