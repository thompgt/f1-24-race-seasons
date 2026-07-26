from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)

requires_run = pytest.mark.skipif(
    not settings.db_path.exists(),
    reason="data/f1.db not built — run scripts/build_db.py and run_simulations.py",
)


def test_health_reports_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["database_present"], bool)


@requires_run
def test_seasons_list_spans_the_whole_history():
    response = client.get("/api/seasons")
    assert response.status_code == 200

    seasons = response.json()
    years = [s["year"] for s in seasons]
    assert years[0] == 1950
    assert years == sorted(years)
    assert len(years) == len(set(years))


@requires_run
def test_seasons_list_flags_where_the_title_changes():
    seasons = client.get("/api/seasons").json()
    changed = [s for s in seasons if s["champion_changes"]]
    assert changed, "normalisation should move at least one title"

    for season in changed:
        assert season["actual_champion"]["driver_id"] != season["likeliest_champion"]["driver_id"]

    # 1988 is the canonical case: Prost outscored Senna but lost on drop scores.
    assert 1988 in {s["year"] for s in changed}


@requires_run
def test_season_detail_carries_all_three_bases():
    response = client.get("/api/seasons/1958")
    assert response.status_code == 200

    season = response.json()
    assert season["year"] == 1958
    assert season["n_races"] == 10
    assert season["target_races"] == 24
    assert season["drivers"] and season["constructors"]

    row = season["drivers"][0]
    for key in ("actual", "scaled", "wins", "podiums", "poles", "points"):
        assert key in row
    assert row["wins"]["p2_5"] <= row["wins"]["median"] <= row["wins"]["p97_5"]


@requires_run
def test_season_detail_reports_excluded_races():
    season = client.get("/api/seasons/1950").json()
    assert len(season["excluded_races"]) == 1
    assert "Indianapolis" in season["excluded_races"][0]["name"]
    assert season["n_races"] == 6


@requires_run
def test_simulated_means_match_the_pro_rata_column():
    """The pipeline's core identity, checked through the API surface."""
    season = client.get("/api/seasons/1961").json()
    for row in season["drivers"]:
        assert abs(row["wins"]["mean"] - row["scaled"]["wins"]) < 0.15


@requires_run
def test_part_season_drivers_are_flagged():
    season = client.get("/api/seasons/1950").json()
    flagged = [r for r in season["drivers"] if r["is_part_season"]]
    assert flagged, "1950 had many one-off entrants"
    for row in flagged:
        assert row["actual"]["races"] < season["n_races"]


@requires_run
def test_champion_odds_form_a_distribution():
    odds = client.get("/api/seasons/2008/champion-odds").json()
    assert odds == sorted(odds, key=lambda o: -o["p_champion"])
    assert sum(o["p_champion"] for o in odds) == pytest.approx(1.0, abs=1e-6)
    assert any(o["is_actual_champion"] for o in odds)


@requires_run
def test_unknown_season_returns_404():
    assert client.get("/api/seasons/1899").status_code == 404
    assert client.get("/api/seasons/1899/champion-odds").status_code == 404


# --- Historical stats --------------------------------------------------------


@requires_run
def test_leaderboard_lifts_short_era_drivers():
    """The correction, checked through the API.

    Fangio sits outside the top ten on raw wins because he raced 7-9 race
    seasons; normalised to 24 he belongs near the front.
    """
    board = client.get("/api/historical/leaders?metric=wins&limit=10").json()
    rows = {row["label"]: row for row in board["rows"]}

    fangio = rows["Juan Fangio"]
    assert fangio["rank"] <= 5
    assert fangio["rank_actual"] > 10
    assert fangio["rank_delta"] > 0
    assert fangio["actual"] == 24
    assert fangio["sim"]["median"] > 60


@requires_run
def test_leaderboard_ranks_by_the_requested_basis():
    actual = client.get("/api/historical/leaders?metric=wins&basis=actual&limit=5").json()
    assert [r["label"] for r in actual["rows"]][:2] == ["Lewis Hamilton", "Michael Schumacher"]
    assert actual["rows"] == sorted(actual["rows"], key=lambda r: -r["actual"])

    simulated = client.get("/api/historical/leaders?metric=wins&basis=sim&limit=5").json()
    assert simulated["rows"] != actual["rows"]


@requires_run
def test_rank_delta_is_omitted_without_a_real_baseline():
    """Constructors' titles have no unadjusted counterpart in the source data."""
    board = client.get(
        "/api/historical/leaders?metric=championships&group_by=constructor&limit=5"
    ).json()
    assert all(row["rank_delta"] is None for row in board["rows"])


@requires_run
def test_group_totals_carry_real_actuals():
    board = client.get("/api/historical/leaders?metric=wins&group_by=constructor&limit=5").json()
    top = board["rows"][0]
    assert top["label"] == "Ferrari"
    assert top["actual"] > 200
    assert top["sim"]["median"] > top["actual"]


@requires_run
def test_nationality_grouping_aggregates_drivers():
    board = client.get(
        "/api/historical/leaders?metric=wins&group_by=driver_nationality&limit=5"
    ).json()
    assert board["rows"][0]["label"] == "British"
    assert board["rows"][0]["n_entities"] > 1


@requires_run
def test_the_year_range_restricts_the_field():
    board = client.get(
        "/api/historical/leaders?metric=wins&year_from=1950&year_to=1969&limit=5"
    ).json()
    labels = [row["label"] for row in board["rows"]]
    assert "Juan Fangio" in labels
    assert "Lewis Hamilton" not in labels

    for row in board["rows"]:
        assert row["sim"]["p2_5"] <= row["sim"]["median"] <= row["sim"]["p97_5"]


@requires_run
def test_min_races_excludes_one_off_entrants():
    strict = client.get("/api/historical/leaders?metric=wins&min_races=100").json()
    loose = client.get("/api/historical/leaders?metric=wins&min_races=1").json()
    assert strict["total"] < loose["total"]


@requires_run
def test_the_year_range_is_rejected_for_group_totals():
    response = client.get(
        "/api/historical/leaders?group_by=constructor&year_from=1990&year_to=2000"
    )
    assert response.status_code == 422
    assert "driver leaderboards only" in response.json()["detail"]


@requires_run
def test_an_inverted_year_range_is_rejected():
    response = client.get("/api/historical/leaders?year_from=2000&year_to=1990")
    assert response.status_code == 422


def test_unknown_metric_is_rejected():
    assert client.get("/api/historical/leaders?metric=fastest_pitstops").status_code == 422
