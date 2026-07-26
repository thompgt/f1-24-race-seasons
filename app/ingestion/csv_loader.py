"""Load the Ergast CSV dump (1950-2024) into the source tables.

The dump lives outside this repo (see `settings.csv_dir`). Only the columns this
project needs are carried over; `lap_times.csv`, standings tables and URLs are
ignored, since standings are recomputed from scratch under modern points.

Note: the sibling `database.db` in that directory is NOT a valid source — its
drivers table holds 1,722 rows against 862 in `drivers.csv`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

#: Ergast encodes missing values as a literal backslash-N.
NA_VALUES = [r"\N"]

#: The Indianapolis 500 counted toward the World Championship from 1950 to 1960
#: but ran to different regulations and drew almost no F1 regulars. Later races
#: at the same circuit (the 2000-2007 United States GP) are genuine F1 races and
#: must not be caught by this rule — hence the year bound.
INDY_CIRCUIT_REF = "indianapolis"
INDY_LAST_YEAR = 1960
INDY_EXCLUSION_REASON = "Indianapolis 500 (1950-60): championship round, not an F1 race"


@dataclass(frozen=True)
class SourceFrames:
    """The ingested dump, shaped for the source tables."""

    seasons: pd.DataFrame
    drivers: pd.DataFrame
    constructors: pd.DataFrame
    circuits: pd.DataFrame
    races: pd.DataFrame
    race_results: pd.DataFrame


def _read(csv_dir: Path, name: str) -> pd.DataFrame:
    path = csv_dir / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Expected {name}.csv in {csv_dir}")
    return pd.read_csv(path, na_values=NA_VALUES)


def _mark_excluded(races: pd.DataFrame, circuits: pd.DataFrame) -> pd.DataFrame:
    """Flag the Indy 500 rounds of 1950-60."""
    ref = circuits.set_index("circuitId")["circuitRef"]
    is_indy = (races["circuitId"].map(ref) == INDY_CIRCUIT_REF) & (
        races["year"] <= INDY_LAST_YEAR
    )
    races = races.copy()
    races["excluded"] = is_indy
    races["exclusion_reason"] = pd.Series(
        [INDY_EXCLUSION_REASON if flag else None for flag in is_indy],
        index=races.index,
        dtype="object",
    )
    logger.info("Excluded %d Indianapolis 500 rounds", int(is_indy.sum()))
    return races


def _collapse_car_swaps(results: pd.DataFrame) -> pd.DataFrame:
    """Reduce a driver to one result per race, keeping their best finish.

    In the 1950s a driver could retire their own car and take over a teammate's,
    producing two rows for one race — 85 such pairs. Keeping the better
    `positionOrder` credits the driver with the result they are historically
    recognised for: at the 1951 French GP, Fangio retired his own car, took over
    Fagioli's and won, so the winning row is the one that survives.

    Must run *after* pole derivation, which needs the original starting grid —
    Fangio started that race from pole in the car he retired.
    """
    before = len(results)
    results = (
        results.sort_values(["raceId", "driverId", "positionOrder", "resultId"])
        .drop_duplicates(subset=["raceId", "driverId"], keep="first")
        .copy()
    )
    logger.info("Collapsed %d car-swap duplicate rows", before - len(results))
    return results


def _mark_shared_drives(results: pd.DataFrame) -> pd.DataFrame:
    """Flag co-drivers of a shared car so each position is credited once.

    Two drivers sharing one car are both classified in the same position, which
    would otherwise award two wins for a single race. The lowest-`resultId` row
    in each (race, position) group is treated as canonical; the rest score
    nothing. This affects 3 wins and 18 podiums across 1,125 races and is
    disclosed through /api/meta.
    """
    results = results.sort_values("resultId").copy()
    classified = results["position"].notna()
    dupe_rank = results[classified].groupby(["raceId", "position"]).cumcount()
    results["is_shared_secondary"] = False
    results.loc[classified, "is_shared_secondary"] = dupe_rank > 0
    logger.info(
        "Flagged %d shared-drive co-driver rows",
        int(results["is_shared_secondary"].sum()),
    )
    return results


def _derive_poles(races: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """Attribute pole position from the starting grid.

    `grid == 1` has complete coverage for every season 1950-2024, which is why
    the (sparse, 1994+) qualifying data is not needed. Nine races list more than
    one driver on grid 1 — again shared drives — so the best-classified of them
    wins the tie, falling back to the lowest driver id for determinism.
    """
    front_row = results[results["grid"] == 1].copy()
    front_row["_order"] = front_row["positionOrder"].fillna(9_999)
    front_row = front_row.sort_values(["raceId", "_order", "driverId"])
    poles = front_row.groupby("raceId")["driverId"].first()

    races = races.copy()
    races["pole_driver_id"] = races["raceId"].map(poles).astype("Int64")
    races["pole_source"] = races["pole_driver_id"].notna().map({True: "grid", False: None})

    missing = int(races.loc[~races["excluded"], "pole_driver_id"].isna().sum())
    if missing:
        logger.warning("%d non-excluded races have no grid-1 driver", missing)
    return races


def load_source_frames(csv_dir: Path) -> SourceFrames:
    """Read the dump and reshape it into the source-table column layout."""
    raw_races = _read(csv_dir, "races")
    raw_results = _read(csv_dir, "results")
    raw_drivers = _read(csv_dir, "drivers")
    raw_constructors = _read(csv_dir, "constructors")
    raw_circuits = _read(csv_dir, "circuits")

    races = _mark_excluded(raw_races, raw_circuits)
    # Poles come from the original starting grid, so this must precede the
    # car-swap collapse, which discards the row a driver started from.
    races = _derive_poles(races, raw_results)
    races["has_sprint"] = raw_races["sprint_date"].notna()

    results = _mark_shared_drives(_collapse_car_swaps(raw_results))

    # Season totals count only races that survive exclusion.
    counted = races[~races["excluded"]]
    seasons = (
        counted.groupby("year")
        .agg(n_races=("raceId", "nunique"), n_sprints=("has_sprint", "sum"))
        .reset_index()
    )
    seasons["n_sprints"] = seasons["n_sprints"].astype(int)
    seasons["is_complete"] = True
    seasons["source"] = "ergast_csv"

    classified = results["position"].notna() & ~results["is_shared_secondary"]
    race_results = pd.DataFrame(
        {
            "race_id": results["raceId"],
            "driver_id": results["driverId"],
            "constructor_id": results["constructorId"],
            "grid": results["grid"],
            "position": results["position"].astype("Int64"),
            "position_text": results["positionText"].astype(str),
            "position_order": results["positionOrder"].astype("Int64"),
            "set_fastest_lap": (results["rank"] == 1).fillna(False),
            "is_shared_secondary": results["is_shared_secondary"],
            # Points are materialised in a later step, once the modern scale is
            # applied; see `app.sim.scoring`.
            "points": 0.0,
            "points_no_fl": 0.0,
            "is_win": classified & (results["position"] == 1),
            "is_podium": classified & (results["position"] <= 3),
        }
    )

    return SourceFrames(
        seasons=seasons,
        drivers=raw_drivers.rename(
            columns={
                "driverId": "driver_id",
                "driverRef": "driver_ref",
            }
        )[["driver_id", "driver_ref", "code", "forename", "surname", "dob", "nationality"]],
        constructors=raw_constructors.rename(
            columns={
                "constructorId": "constructor_id",
                "constructorRef": "constructor_ref",
            }
        )[["constructor_id", "constructor_ref", "name", "nationality"]],
        circuits=raw_circuits.rename(
            columns={"circuitId": "circuit_id", "circuitRef": "circuit_ref"}
        )[["circuit_id", "circuit_ref", "name", "location", "country"]],
        races=races.rename(columns={"raceId": "race_id", "circuitId": "circuit_id"})[
            [
                "race_id",
                "year",
                "round",
                "circuit_id",
                "name",
                "date",
                "has_sprint",
                "excluded",
                "exclusion_reason",
                "pole_driver_id",
                "pole_source",
            ]
        ],
        race_results=race_results,
    )
