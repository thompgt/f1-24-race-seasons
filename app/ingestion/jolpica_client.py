"""Client for the Jolpica API, the maintained successor to Ergast.

Ergast stopped updating after 2024, so everything from 2025 on — plus sprint
results, which the CSV dump never contained — comes from here. Responses are
cached under `data/raw/` so rebuilds and tests run offline and the API is only
hit once per resource.

No API key is required. Jolpica publishes a burst limit of 4 requests/second, so
requests are spaced deliberately.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.jolpi.ca/ergast/f1"
PAGE_SIZE = 100
REQUEST_SPACING_SECONDS = 0.4
MAX_ATTEMPTS = 4
TIMEOUT_SECONDS = 60.0


class JolpicaError(RuntimeError):
    pass


class JolpicaClient:
    """Fetches and caches Jolpica resources.

    `use_cache=True` (the default) makes a second run free; pass `refresh=True`
    to re-fetch a resource whose season is still in progress.
    """

    def __init__(self, cache_dir: Path, *, use_cache: bool = True) -> None:
        self.cache_dir = cache_dir
        self.use_cache = use_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)
        self._last_request = 0.0

    def __enter__(self) -> JolpicaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < REQUEST_SPACING_SECONDS:
            time.sleep(REQUEST_SPACING_SECONDS - elapsed)
        self._last_request = time.monotonic()

    def _get(self, path: str, *, limit: int, offset: int) -> dict[str, Any]:
        url = f"{BASE_URL}/{path}.json"
        params = {"limit": limit, "offset": offset}

        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._throttle()
            try:
                response = self._client.get(url, params=params)
                if response.status_code == 429:
                    wait = min(2**attempt, 30)
                    logger.warning("Rate limited on %s; waiting %ss", path, wait)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()["MRData"]
            except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
                if attempt == MAX_ATTEMPTS:
                    raise JolpicaError(f"Failed to fetch {path}: {exc}") from exc
                wait = min(2**attempt, 30)
                logger.warning("Attempt %d for %s failed (%s); retrying in %ss",
                               attempt, path, exc, wait)
                time.sleep(wait)
        raise JolpicaError(f"Exhausted retries for {path}")

    def fetch(self, path: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        """Fetch every page of a resource, returning the flattened Races list.

        Jolpica paginates over *rows*, not races, so a race's results can be
        split across two pages. Races are therefore merged by round after all
        pages are collected.
        """
        cache_path = self.cache_dir / f"{path.replace('/', '_')}.json"
        if self.use_cache and not refresh and cache_path.exists():
            logger.debug("cache hit %s", path)
            return json.loads(cache_path.read_text(encoding="utf-8"))

        merged: dict[str, dict[str, Any]] = {}
        offset = 0
        total = None

        while total is None or offset < total:
            data = self._get(path, limit=PAGE_SIZE, offset=offset)
            total = int(data["total"])
            for race in data["RaceTable"]["Races"]:
                key = race["round"]
                if key in merged:
                    _merge_race(merged[key], race)
                else:
                    merged[key] = race
            offset += PAGE_SIZE
            if total == 0:
                break

        races = sorted(merged.values(), key=lambda r: int(r["round"]))
        cache_path.write_text(json.dumps(races, indent=1), encoding="utf-8")
        logger.info("fetched %-28s %3d races (%s rows)", path, len(races), total)
        return races


    def fetch_standings(self, year: int, *, refresh: bool = False) -> list[dict[str, Any]]:
        """Final driver standings for a season, under the rules actually applied.

        Shaped differently from the race resources — StandingsTable rather than
        RaceTable — so it does not go through `fetch`.
        """
        path = f"{year}/driverstandings"
        cache_path = self.cache_dir / f"{path.replace('/', '_')}.json"
        if self.use_cache and not refresh and cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        data = self._get(path, limit=PAGE_SIZE, offset=0)
        lists = data["StandingsTable"]["StandingsLists"]
        standings = lists[0]["DriverStandings"] if lists else []
        cache_path.write_text(json.dumps(standings, indent=1), encoding="utf-8")
        logger.info("fetched %-28s %3d drivers", path, len(standings))
        return standings


#: The per-race list each resource type carries.
ROW_KEYS = ("Results", "SprintResults", "QualifyingResults")


def _merge_race(target: dict[str, Any], extra: dict[str, Any]) -> None:
    """Append rows from a later page onto the race already collected."""
    for key in ROW_KEYS:
        if key in extra:
            target.setdefault(key, []).extend(extra[key])
