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
