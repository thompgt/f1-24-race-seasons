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

import numpy as np
import pandas as pd

from app.sim import scoring

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


def _mark_shared_drives(results: pd.DataFrame, races: pd.DataFrame) -> pd.DataFrame:
    """Flag co-drivers of a shared car so each position is credited once.

    Two drivers sharing one car are both classified in the same position, which
    would otherwise award two wins for a single race. One of them has to be
    treated as canonical, and picking arbitrarily gets famous results wrong:
    source order credits Fagioli rather than Fangio with the 1951 French GP,
    leaving Fangio on 22 career wins instead of his actual 24.

    The tiebreak is therefore the driver's strength that season, measured as
    modern points from their unshared results. That recovers the historically
    credited driver in every shared win — Fangio in 1951 and 1956, Moss in 1957 —
    without hardcoding any names. Co-drivers lose the shared result, which is a
    deviation from the official record (where both are credited) forced by the
    requirement that a race have exactly one winner.
    """
    results = results.sort_values("resultId").copy()
    classified = results["position"].notna()

    # Rough per-season strength, computed from every row so it does not depend on
    # the flag being derived here.
    year_by_race = races.set_index("raceId")["year"]
    strength = (
        results.assign(
            year=results["raceId"].map(year_by_race),
            _pts=scoring.race_points(results["position"].fillna(0).to_numpy(dtype=np.intp)),
        )
        .groupby(["year", "driverId"])["_pts"]
        .sum()
    )
    results["_strength"] = pd.MultiIndex.from_arrays(
        [results["raceId"].map(year_by_race), results["driverId"]]
    ).map(strength).fillna(0.0)

    ordered = results[classified].sort_values(
        ["raceId", "position", "_strength", "resultId"], ascending=[True, True, False, True]
    )
    dupe_rank = ordered.groupby(["raceId", "position"]).cumcount()

    results["is_shared_secondary"] = False
    results.loc[dupe_rank.index, "is_shared_secondary"] = dupe_rank > 0
    results = results.drop(columns="_strength")

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


def _actual_champions(csv_dir: Path, races: pd.DataFrame) -> pd.Series:
    """The real title winner per season, from the final round's standings.

    Taken from Ergast's own standings rather than recomputed, so it reflects the
    rules actually in force that year — including the "best N results count"
    rules this project otherwise ignores. Indexed by year.
    """
    standings = _read(csv_dir, "driver_standings")
    final_round = races.loc[races.groupby("year")["round"].idxmax(), ["raceId", "year"]]
    leaders = standings[standings["position"] == 1]
    merged = final_round.merge(leaders, on="raceId", how="left")
    champions = merged.set_index("year")["driverId"]
    missing = int(champions.isna().sum())
    if missing:
        logger.warning("%d seasons have no champion in driver_standings.csv", missing)
    return champions


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

    results = _mark_shared_drives(_collapse_car_swaps(raw_results), raw_races)

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
    seasons["actual_champion_driver_id"] = (
        seasons["year"].map(_actual_champions(csv_dir, raw_races)).astype("Int64")
    )

    # Score off the numeric finishing position, never off positionOrder — that is
    # a dense rank including retirements, and using it awards points to 338
    # retired, withdrawn and disqualified entries.
    scorable = results["position"].notna() & ~results["is_shared_secondary"]
    positions = np.where(scorable, results["position"].fillna(0), 0).astype(np.intp)
    set_fl = (results["rank"] == 1).fillna(False).to_numpy(dtype=bool)

    base_points = scoring.race_points(positions)
    fl_points = scoring.fastest_lap_points(positions, set_fl)

    race_results = pd.DataFrame(
        {
            "race_id": results["raceId"],
            "driver_id": results["driverId"],
            "constructor_id": results["constructorId"],
            "grid": results["grid"],
            "position": results["position"].astype("Int64"),
            "position_text": results["positionText"].astype(str),
            "position_order": results["positionOrder"].astype("Int64"),
            "set_fastest_lap": set_fl,
            "is_shared_secondary": results["is_shared_secondary"],
            "points": base_points + fl_points,
            "points_no_fl": base_points,
            "is_win": scoring.is_win(positions),
            "is_podium": scoring.is_podium(positions),
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
