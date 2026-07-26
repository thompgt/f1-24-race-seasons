"""Unit tests for the points scale. Pure functions, no database."""

from __future__ import annotations

import numpy as np

from app.sim import scoring
from tests.conftest import scalar


def test_modern_scale_maps_the_top_ten():
    positions = np.arange(1, 11)
    assert scoring.race_points(positions).tolist() == [
        25.0, 18.0, 15.0, 12.0, 10.0, 8.0, 6.0, 4.0, 2.0, 1.0
    ]


def test_positions_outside_the_points_score_nothing():
    assert scoring.race_points(np.array([11, 12, 20])).tolist() == [0.0, 0.0, 0.0]


def test_unclassified_sentinels_score_nothing():
    """Retirements arrive as 0 after the position column is filled."""
    assert scoring.race_points(np.array([0, -1])).tolist() == [0.0, 0.0]


def test_sprint_scale_maps_the_top_eight():
    positions = np.arange(1, 10)
    assert scoring.sprint_points(positions).tolist() == [
        8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0
    ]


def test_fastest_lap_requires_a_top_ten_finish():
    positions = np.array([1, 10, 11, 0])
    flags = np.array([True, True, True, True])
    assert scoring.fastest_lap_points(positions, flags).tolist() == [1.0, 1.0, 0.0, 0.0]


def test_fastest_lap_without_the_flag_scores_nothing():
    positions = np.array([1, 2, 3])
    flags = np.array([False, False, False])
    assert scoring.fastest_lap_points(positions, flags).tolist() == [0.0, 0.0, 0.0]


def test_win_and_podium_classification():
    positions = np.array([1, 2, 3, 4, 0])
    assert scoring.is_win(positions).tolist() == [True, False, False, False, False]
    assert scoring.is_podium(positions).tolist() == [True, True, True, False, False]


# --- Materialised points in the built database -------------------------------


def test_no_points_awarded_to_unclassified_entries(db):
    """The positionOrder trap, checked against the real data.

    338 rows have positionOrder <= 10 while being retired, withdrawn or
    disqualified. Scoring off positionOrder — as the reference implementation at
    ~/F1_points_application/adjusted_points.py does — pays all of them.
    """
    leaked = scalar(
        db,
        """
        SELECT COUNT(*) FROM race_results
        WHERE position IS NULL AND (points > 0 OR points_no_fl > 0)
        """,
    )
    assert leaked == 0


def test_the_positionorder_trap_is_real(db):
    """Guards the test above: confirm the trap rows exist to be avoided.

    338 in the raw dump; 332 survive ingest, because the car-swap collapse drops
    six retirement rows in favour of the same driver's better result.
    """
    trap_rows = scalar(
        db,
        """
        SELECT COUNT(*) FROM race_results
        WHERE position IS NULL AND position_order <= 10
        """,
    )
    assert trap_rows == 332


def test_shared_drive_co_drivers_score_nothing(db):
    leaked = scalar(
        db,
        "SELECT COUNT(*) FROM race_results WHERE is_shared_secondary = 1 AND points > 0",
    )
    assert leaked == 0


def test_every_race_awards_the_same_base_points(db):
    """Modern points are position-based, so each race pays a fixed total.

    Races with fewer than 10 classified finishers pay less — those are early
    seasons with heavy attrition, so the check is that no race pays *more* than
    the scale allows.
    """
    over = scalar(
        db,
        f"""
        SELECT COUNT(*) FROM (
          SELECT race_id, SUM(points_no_fl) AS total
          FROM race_results GROUP BY race_id
          HAVING total > {sum(scoring.MODERN_POINTS)}
        )
        """,
    )
    assert over == 0


def test_fastest_lap_point_only_appears_from_2004(db):
    first_year = scalar(
        db,
        """
        SELECT MIN(r.year) FROM races r
        JOIN race_results rr ON rr.race_id = r.race_id
        WHERE rr.points > rr.points_no_fl
        """,
    )
    assert first_year == 2004


def test_points_and_points_no_fl_differ_by_at_most_one(db):
    bad = scalar(
        db,
        "SELECT COUNT(*) FROM race_results WHERE points - points_no_fl NOT IN (0, 1)",
    )
    assert bad == 0
