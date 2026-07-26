"""The modern points system, applied to every era.

Pure functions over arrays — no database, no pandas. The scale below is the one
in use since 2010; applying it uniformly is the whole point of the exercise, so
historical scales and "best N results count" rules are deliberately absent.
"""

from __future__ import annotations

import numpy as np

#: Points for finishing positions 1-10 (2010-present).
MODERN_POINTS: tuple[int, ...] = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)

#: Sprint race points for positions 1-8 (2022-present scale).
SPRINT_POINTS: tuple[int, ...] = (8, 7, 6, 5, 4, 3, 2, 1)

#: A point for the fastest lap, awarded only to a driver finishing in the top 10.
FASTEST_LAP_POINT = 1
FASTEST_LAP_MAX_POSITION = 10

PODIUM_POSITION = 3


def _table_lookup(positions: np.ndarray, table: tuple[int, ...]) -> np.ndarray:
    """Map 1-indexed finishing positions onto a points table, 0 outside it.

    `positions` may contain 0 or negative sentinels for unclassified entries;
    those score nothing.
    """
    positions = np.asarray(positions)
    points = np.zeros(positions.shape, dtype=np.float32)
    scale = np.asarray(table, dtype=np.float32)

    in_points = (positions >= 1) & (positions <= len(table))
    points[in_points] = scale[positions[in_points].astype(np.intp) - 1]
    return points


def race_points(positions: np.ndarray) -> np.ndarray:
    """Modern points for classified finishing positions."""
    return _table_lookup(positions, MODERN_POINTS)


def sprint_points(positions: np.ndarray) -> np.ndarray:
    """Sprint points for classified sprint finishing positions."""
    return _table_lookup(positions, SPRINT_POINTS)


def fastest_lap_points(positions: np.ndarray, set_fastest_lap: np.ndarray) -> np.ndarray:
    """The fastest-lap bonus, which requires a top-10 finish.

    Caller beware: the source data only records fastest laps from 2004. Adding
    this to every era is impossible, and adding it only where data exists hands
    2004+ drivers roughly half a point per race that earlier drivers could never
    earn — which is the era bias this project exists to remove. Season standings
    may use it; all-time leaderboards should not.
    """
    positions = np.asarray(positions)
    eligible = (
        np.asarray(set_fastest_lap, dtype=bool)
        & (positions >= 1)
        & (positions <= FASTEST_LAP_MAX_POSITION)
    )
    return eligible.astype(np.float32) * FASTEST_LAP_POINT


def is_win(positions: np.ndarray) -> np.ndarray:
    return np.asarray(positions) == 1


def is_podium(positions: np.ndarray) -> np.ndarray:
    positions = np.asarray(positions)
    return (positions >= 1) & (positions <= PODIUM_POSITION)
