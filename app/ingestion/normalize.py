"""Turn cached Jolpica JSON into rows matching the source-table layout.

Jolpica identifies entities by string ref (`max_verstappen`, `mclaren`), which is
the same vocabulary as the CSV dump's `driverRef` / `constructorRef` columns —
so existing entities are matched by ref and only genuinely new ones get fresh
integer ids, counting up from `JOLPICA_ID_BASE`.

Sprint results are grafted onto races the CSV dump already has (2021-2024),
which is why races are keyed by (year, round) rather than by id.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.models.source import JOLPICA_ID_BASE
from app.sim import scoring

logger = logging.getLogger(__name__)


@dataclass
class IdRegistry:
    """Maps entity refs to integer ids, minting new ones as needed.

    Refs already present from the CSV dump keep their original id, and are
    reported as not-new so the caller does not try to insert them a second time.
    """

    by_ref: dict[str, int]
    _next_id: int = JOLPICA_ID_BASE
    minted_refs: set[str] = field(default_factory=set)

    def resolve(self, ref: str) -> int:
        if ref not in self.by_ref:
            self.by_ref[ref] = self._next_id
            self.minted_refs.add(ref)
            self._next_id += 1
        return self.by_ref[ref]

    def is_new(self, ref: str) -> bool:
        return ref in self.minted_refs


@dataclass(frozen=True)
class JolpicaFrames:
    seasons: pd.DataFrame
    drivers: pd.DataFrame
    constructors: pd.DataFrame
    circuits: pd.DataFrame
    races: pd.DataFrame
    race_results: pd.DataFrame
    sprint_results: pd.DataFrame
    qualifying: pd.DataFrame
    #: Races already in the database (2021-2024) that gained a sprint. These need
    #: an UPDATE rather than an INSERT, since the CSV dump carried no sprint data.
    existing_races_with_sprints: list[int]
    #: Seasons already in the database whose sprint count changed, as {year: n}.
    existing_season_sprint_counts: dict[int, int]


def _read_cache(raw_dir: Path, name: str) -> list[dict[str, Any]] | None:
    path = raw_dir / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _classified_position(row: dict[str, Any]) -> int | None:
    """A finishing position only counts when positionText is numeric.

    Jolpica uses the same convention as Ergast: 'R' retired, 'D' disqualified,
    'W' withdrawn, 'E' excluded, 'N' not classified, 'F' failed to qualify.
    """
    text = str(row.get("positionText", ""))
    return int(text) if text.isdigit() else None


def load_jolpica_frames(
    raw_dir: Path,
    *,
    seasons: list[int],
    sprint_seasons: list[int],
    drivers: IdRegistry,
    constructors: IdRegistry,
    circuits: IdRegistry,
    existing_races: dict[tuple[int, int], int],
    next_race_id: int,
) -> JolpicaFrames:
    """Build source-table rows from the cached JSON.

    `existing_races` lets sprint results attach to CSV-era races; any race not
    already known gets an id from `next_race_id` upward.
    """
    season_rows: list[dict[str, Any]] = []
    race_rows: dict[int, dict[str, Any]] = {}
    result_rows: list[dict[str, Any]] = []
    sprint_rows: list[dict[str, Any]] = []
    quali_rows: list[dict[str, Any]] = []
    driver_rows: dict[int, dict[str, Any]] = {}
    constructor_rows: dict[int, dict[str, Any]] = {}
    circuit_rows: dict[int, dict[str, Any]] = {}

    race_ids = dict(existing_races)
    race_id_counter = next_race_id

    def register_driver(payload: dict[str, Any]) -> int:
        ref = payload["driverId"]
        driver_id = drivers.resolve(ref)
        if drivers.is_new(ref):
            driver_rows.setdefault(
                driver_id,
                {
                    "driver_id": driver_id,
                    "driver_ref": ref,
                    "code": payload.get("code"),
                    "forename": payload.get("givenName", ""),
                    "surname": payload.get("familyName", ""),
                    "dob": payload.get("dateOfBirth"),
                    "nationality": payload.get("nationality"),
                },
            )
        return driver_id

    def register_constructor(payload: dict[str, Any]) -> int:
        ref = payload["constructorId"]
        constructor_id = constructors.resolve(ref)
        if constructors.is_new(ref):
            constructor_rows.setdefault(
                constructor_id,
                {
                    "constructor_id": constructor_id,
                    "constructor_ref": ref,
                    # Jolpica returns HTML entities in some team names.
                    "name": html.unescape(payload.get("name", "")),
                    "nationality": payload.get("nationality"),
                },
            )
        return constructor_id

    def register_race(year: int, race: dict[str, Any]) -> int:
        nonlocal race_id_counter
        rnd = int(race["round"])
        key = (year, rnd)
        if key not in race_ids:
            race_ids[key] = race_id_counter
            race_id_counter += 1
        race_id = race_ids[key]

        circuit = race.get("Circuit")
        circuit_id = None
        if circuit:
            ref = circuit["circuitId"]
            circuit_id = circuits.resolve(ref)
            if circuits.is_new(ref):
                location = circuit.get("Location", {})
                circuit_rows.setdefault(
                    circuit_id,
                    {
                        "circuit_id": circuit_id,
                        "circuit_ref": ref,
                        "name": html.unescape(circuit.get("circuitName", "")),
                        "location": location.get("locality"),
                        "country": location.get("country"),
                    },
                )

        race_rows.setdefault(
            race_id,
            {
                "race_id": race_id,
                "year": year,
                "round": rnd,
                "circuit_id": circuit_id,
                "name": html.unescape(race.get("raceName", "")),
                "date": race.get("date"),
                "has_sprint": False,
                "excluded": False,
                "exclusion_reason": None,
                "pole_driver_id": None,
                "pole_source": None,
            },
        )
        return race_id

    # --- Race results for seasons the CSV dump does not cover ----------------
    for year in seasons:
        results = _read_cache(raw_dir, f"{year}/results".replace("/", "_"))
        if results is None:
            logger.warning("No cached results for %d; skipping", year)
            continue

        for race in results:
            race_id = register_race(year, race)
            for row in race.get("Results", []):
                driver_id = register_driver(row["Driver"])
                register_constructor(row["Constructor"])
                position = _classified_position(row)
                grid = _int_or_none(row.get("grid"))
                set_fl = str(row.get("FastestLap", {}).get("rank", "")) == "1"

                if grid == 1:
                    race_rows[race_id]["pole_driver_id"] = driver_id
                    race_rows[race_id]["pole_source"] = "grid"

                result_rows.append(
                    {
                        "race_id": race_id,
                        "driver_id": driver_id,
                        "constructor_id": constructors.by_ref[row["Constructor"]["constructorId"]],
                        "grid": grid,
                        "position": position,
                        "position_text": str(row.get("positionText", "")),
                        "position_order": _int_or_none(row.get("position")),
                        "set_fastest_lap": set_fl,
                        "is_shared_secondary": False,
                        "_position_for_scoring": position or 0,
                    }
                )

        standings = _read_cache(raw_dir, f"{year}_driverstandings")
        champion_id = None
        if standings:
            champion_id = register_driver(standings[0]["Driver"])

        race_count = sum(1 for r in race_rows.values() if r["year"] == year)
        scheduled = _read_cache(raw_dir, f"{year}_races") or []
        is_complete = race_count >= len(scheduled) and race_count > 0

        season_rows.append(
            {
                "year": year,
                "n_races": race_count,
                "n_sprints": 0,  # filled in once sprints are read
                "is_complete": is_complete,
                "source": "jolpica",
                "actual_champion_driver_id": champion_id if is_complete else None,
            }
        )
        if not is_complete:
            logger.info(
                "%d is in progress: %d of %d scheduled races have results",
                year, race_count, len(scheduled),
            )

        # --- Qualifying, used only to cross-check grid-derived poles ---------
        qualifying = _read_cache(raw_dir, f"{year}_qualifying") or []
        for race in qualifying:
            race_id = race_ids.get((year, int(race["round"])))
            if race_id is None:
                continue
            for row in race.get("QualifyingResults", []):
                quali_rows.append(
                    {
                        "race_id": race_id,
                        "driver_id": register_driver(row["Driver"]),
                        "position": _int_or_none(row.get("position")),
                    }
                )

    # --- Sprints, including for races the CSV dump already has ---------------
    sprint_counts: dict[int, int] = {}
    existing_with_sprints: list[int] = []
    for year in sprint_seasons:
        sprints = _read_cache(raw_dir, f"{year}_sprint")
        if not sprints:
            continue
        for race in sprints:
            key = (year, int(race["round"]))
            race_id = race_ids.get(key)
            if race_id is None:
                logger.warning("Sprint for unknown race %s; skipping", key)
                continue
            if race_id in race_rows:
                race_rows[race_id]["has_sprint"] = True
            else:
                existing_with_sprints.append(race_id)
            sprint_counts[year] = sprint_counts.get(year, 0) + 1

            for row in race.get("SprintResults", []):
                position = _classified_position(row)
                sprint_rows.append(
                    {
                        "race_id": race_id,
                        "driver_id": register_driver(row["Driver"]),
                        "constructor_id": register_constructor(row["Constructor"]),
                        "position": position,
                        "points": float(scoring.sprint_points(np.array([position or 0]))[0]),
                    }
                )

    new_years = {season["year"] for season in season_rows}
    for season in season_rows:
        season["n_sprints"] = sprint_counts.get(season["year"], 0)
    existing_season_sprints = {
        year: count for year, count in sprint_counts.items() if year not in new_years
    }

    results_frame = pd.DataFrame(result_rows)
    if not results_frame.empty:
        positions = results_frame.pop("_position_for_scoring").to_numpy(dtype=np.intp)
        set_fl = results_frame["set_fastest_lap"].to_numpy(dtype=bool)
        base = scoring.race_points(positions)
        results_frame["points"] = base + scoring.fastest_lap_points(positions, set_fl)
        results_frame["points_no_fl"] = base
        results_frame["is_win"] = scoring.is_win(positions)
        results_frame["is_podium"] = scoring.is_podium(positions)
        results_frame["position"] = results_frame["position"].astype("Int64")
        results_frame["position_order"] = results_frame["position_order"].astype("Int64")

    logger.info(
        "Jolpica: %d races, %d results, %d sprint results, %d new drivers",
        len(race_rows), len(result_rows), len(sprint_rows), len(drivers.minted_refs),
    )

    return JolpicaFrames(
        seasons=pd.DataFrame(season_rows),
        drivers=pd.DataFrame(list(driver_rows.values())),
        constructors=pd.DataFrame(list(constructor_rows.values())),
        circuits=pd.DataFrame(list(circuit_rows.values())),
        races=pd.DataFrame(list(race_rows.values())),
        race_results=results_frame,
        sprint_results=pd.DataFrame(sprint_rows),
        qualifying=pd.DataFrame(quali_rows).drop_duplicates(
            subset=["race_id", "driver_id"]
        )
        if quali_rows
        else pd.DataFrame(columns=["race_id", "driver_id", "position"]),
        existing_races_with_sprints=existing_with_sprints,
        existing_season_sprint_counts=existing_season_sprints,
    )
