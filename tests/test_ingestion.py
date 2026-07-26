"""Assertions about the ingested historical record.

These are data-integrity gates, not unit tests of pure functions: they check that
the database in `data/f1.db` really has the properties the simulation relies on.
"""

from __future__ import annotations

from tests.conftest import scalar


def test_every_season_from_1950_to_2024_is_present(db):
    years = [row[0] for row in db.exec_driver_sql("SELECT year FROM seasons ORDER BY year")]
    assert years == list(range(1950, 2025))


def test_indy_500_rounds_are_excluded(db):
    excluded = scalar(db, "SELECT COUNT(*) FROM races WHERE excluded = 1")
    assert excluded == 11

    span = db.exec_driver_sql(
        "SELECT MIN(year), MAX(year) FROM races WHERE excluded = 1"
    ).one()
    assert span == (1950, 1960)


def test_later_indianapolis_races_are_kept(db):
    """The 2000-2007 United States GP ran at Indianapolis and is a real F1 race."""
    kept = scalar(
        db,
        """
        SELECT COUNT(*) FROM races r
        JOIN circuits c ON c.circuit_id = r.circuit_id
        WHERE c.circuit_ref = 'indianapolis' AND r.excluded = 0
        """,
    )
    assert kept == 8


def test_season_race_counts_reflect_exclusions(db):
    """1950 ran 7 championship rounds, one of which was the Indy 500."""
    assert scalar(db, "SELECT n_races FROM seasons WHERE year = 1950") == 6
    assert scalar(db, "SELECT n_races FROM seasons WHERE year = 2024") == 24


def test_pole_coverage_is_complete(db):
    """Every non-excluded race has an attributed pole-sitter.

    This is what makes poles usable across all eras: `grid == 1` is populated
    back to 1950, unlike qualifying data, which only starts in 1994.
    """
    missing = scalar(
        db,
        "SELECT COUNT(*) FROM races WHERE excluded = 0 AND pole_driver_id IS NULL",
    )
    assert missing == 0


def test_poles_are_all_grid_derived(db):
    sources = dict(
        db.exec_driver_sql(
            "SELECT pole_source, COUNT(*) FROM races GROUP BY pole_source"
        ).all()
    )
    assert set(sources) == {"grid"}


def test_one_driver_per_race(db):
    """Car swaps are collapsed, so (race, driver) is unique."""
    dupes = scalar(
        db,
        """
        SELECT COUNT(*) FROM (
          SELECT race_id, driver_id FROM race_results
          GROUP BY race_id, driver_id HAVING COUNT(*) > 1
        )
        """,
    )
    assert dupes == 0


def test_exactly_one_winner_per_race(db):
    """Shared-drive co-drivers are flagged, so wins are not double counted."""
    off_by_one = scalar(
        db,
        """
        SELECT COUNT(*) FROM (
          SELECT r.race_id, SUM(rr.is_win) AS wins
          FROM races r
          JOIN race_results rr ON rr.race_id = r.race_id
          WHERE r.excluded = 0
          GROUP BY r.race_id
          HAVING wins != 1
        )
        """,
    )
    assert off_by_one == 0


def test_at_most_three_podiums_per_race(db):
    """Fewer than three is legitimate — some early races had few finishers."""
    too_many = scalar(
        db,
        """
        SELECT COUNT(*) FROM (
          SELECT r.race_id, SUM(rr.is_podium) AS podiums
          FROM races r
          JOIN race_results rr ON rr.race_id = r.race_id
          WHERE r.excluded = 0
          GROUP BY r.race_id
          HAVING podiums > 3
        )
        """,
    )
    assert too_many == 0


def test_shared_secondary_rows_never_count_as_wins_or_podiums(db):
    leaked = scalar(
        db,
        """
        SELECT COUNT(*) FROM race_results
        WHERE is_shared_secondary = 1 AND (is_win = 1 OR is_podium = 1)
        """,
    )
    assert leaked == 0


def test_unclassified_results_are_never_wins_or_podiums(db):
    """The positionOrder trap: a dense rank that includes retirements.

    Awarding credit on positionOrder rather than a numeric position gives points
    to 338 retired, withdrawn and disqualified entries.
    """
    leaked = scalar(
        db,
        """
        SELECT COUNT(*) FROM race_results
        WHERE position IS NULL AND (is_win = 1 OR is_podium = 1)
        """,
    )
    assert leaked == 0


def test_fastest_lap_data_only_exists_from_2004(db):
    first_year = scalar(
        db,
        """
        SELECT MIN(r.year) FROM races r
        JOIN race_results rr ON rr.race_id = r.race_id
        WHERE rr.set_fastest_lap = 1
        """,
    )
    assert first_year == 2004


def test_known_win_totals_match_the_real_record(db):
    """A sanity anchor against the actual historical record."""
    wins = dict(
        db.exec_driver_sql(
            """
            SELECT d.driver_ref, SUM(rr.is_win)
            FROM race_results rr
            JOIN drivers d ON d.driver_id = rr.driver_id
            JOIN races r ON r.race_id = rr.race_id
            WHERE r.excluded = 0
            GROUP BY d.driver_ref
            """
        ).all()
    )
    # driver_ref, not surname: Michael and Ralf Schumacher would otherwise merge.
    assert wins["hamilton"] == 105
    assert wins["michael_schumacher"] == 91
    assert wins["max_verstappen"] == 63


def test_shared_drive_wins_go_to_the_historically_credited_driver(db):
    """Fangio's 24 wins include two he took over mid-race in a teammate's car.

    Breaking the tie on source order instead of season strength leaves him on 22
    and hands the 1951 French GP to Fagioli.
    """
    totals = dict(
        db.exec_driver_sql(
            """
            SELECT d.driver_ref, SUM(rr.is_win)
            FROM race_results rr
            JOIN drivers d ON d.driver_id = rr.driver_id
            JOIN races r ON r.race_id = rr.race_id
            WHERE r.excluded = 0 AND d.driver_ref IN ('fangio', 'moss', 'ascari')
            GROUP BY d.driver_ref
            """
        ).all()
    )
    assert totals == {"fangio": 24, "moss": 16, "ascari": 13}


def test_known_podium_totals_match_the_real_record(db):
    podiums = dict(
        db.exec_driver_sql(
            """
            SELECT d.driver_ref, SUM(rr.is_podium)
            FROM race_results rr
            JOIN drivers d ON d.driver_id = rr.driver_id
            JOIN races r ON r.race_id = rr.race_id
            WHERE r.excluded = 0
              AND d.driver_ref IN ('hamilton', 'michael_schumacher', 'fangio', 'moss')
            GROUP BY d.driver_ref
            """
        ).all()
    )
    assert podiums == {
        "hamilton": 202,
        "michael_schumacher": 155,
        "fangio": 35,
        "moss": 24,
    }


def test_every_season_has_an_actual_champion(db):
    missing = scalar(
        db, "SELECT COUNT(*) FROM seasons WHERE actual_champion_driver_id IS NULL"
    )
    assert missing == 0


def test_actual_champions_are_the_real_ones(db):
    champions = dict(
        db.exec_driver_sql(
            """
            SELECT s.year, d.driver_ref
            FROM seasons s JOIN drivers d ON d.driver_id = s.actual_champion_driver_id
            WHERE s.year IN (1950, 1988, 2008, 2021, 2024)
            """
        ).all()
    )
    assert champions == {
        1950: "farina",
        1988: "senna",
        2008: "hamilton",
        2021: "max_verstappen",
        2024: "max_verstappen",
    }
