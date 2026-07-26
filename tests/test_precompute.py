"""Invariants of the precomputed run in data/f1.db.

Skipped when no simulation has been run yet.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from sqlalchemy import text

from app.sim.career import decode_draws
from tests.conftest import scalar


@pytest.fixture(scope="module")
def run_id(db_engine):
    with db_engine.connect() as conn:
        try:
            value = conn.execute(
                text("SELECT MAX(run_id) FROM sim_runs WHERE is_complete = 1")
            ).scalar_one_or_none()
        except Exception:
            value = None
    if value is None:
        pytest.skip("no completed simulation run — run scripts/run_simulations.py")
    return value


def test_every_season_was_simulated(db, run_id):
    seasons = scalar(db, "SELECT COUNT(*) FROM seasons WHERE n_races > 0")
    simulated = scalar(
        db, "SELECT COUNT(DISTINCT year) FROM season_driver_sim WHERE run_id = :r", r=run_id
    )
    assert simulated == seasons


def test_champion_probabilities_sum_to_one_each_season(db, run_id):
    rows = db.execute(
        text(
            """
            SELECT year, SUM(p_champion) AS total
            FROM season_driver_sim WHERE run_id = :r GROUP BY year
            """
        ),
        {"r": run_id},
    ).all()
    for row in rows:
        assert row.total == pytest.approx(1.0, abs=1e-6), row.year


def test_simulated_mean_equals_the_pro_rata_projection(db, run_id):
    """The identity that validates the whole pipeline, on real data.

    Every race is equally likely and every metric is additive, so the bootstrap
    mean must land on actual x 24/R. Checked against the stored columns, which
    means it also catches a summary written into the wrong row.
    """
    rows = db.execute(
        text(
            """
            SELECT year, driver_id, wins_mean, scaled_wins, podiums_mean, scaled_podiums,
                   poles_mean, scaled_poles
            FROM season_driver_sim WHERE run_id = :r
            """
        ),
        {"r": run_id},
    ).all()
    assert rows

    for row in rows:
        for simulated, scaled in (
            (row.wins_mean, row.scaled_wins),
            (row.podiums_mean, row.scaled_podiums),
            (row.poles_mean, row.scaled_poles),
        ):
            # 10,000 iterations of a count bounded by 24 — Monte Carlo error is
            # well under a tenth of a win.
            assert abs(simulated - scaled) < 0.15, (row.year, row.driver_id)


def test_career_mean_equals_the_sum_of_season_means(db, run_id):
    """Linearity holds exactly, so a mismatch means misaligned career vectors."""
    rows = db.execute(
        text(
            """
            SELECT c.driver_id, c.wins_mean AS career_mean, s.total AS season_total
            FROM career_driver_sim c
            JOIN (
              SELECT sds.driver_id, SUM(sds.wins_mean) AS total
              FROM season_driver_sim sds
              JOIN seasons se ON se.year = sds.year AND se.is_complete = 1
              WHERE sds.run_id = :r GROUP BY sds.driver_id
            ) s ON s.driver_id = c.driver_id
            WHERE c.run_id = :r
            """
        ),
        {"r": run_id},
    ).all()
    assert rows

    for row in rows:
        # Relative, not absolute: season means are float32 and accumulate rounding
        # across a long career, while the career vector sums in int64 and is exact.
        assert row.career_mean == pytest.approx(row.season_total, rel=1e-5, abs=1e-6), (
            row.driver_id
        )


def test_career_intervals_are_narrower_than_summed_season_intervals(db, run_id):
    """Variances add, half-widths do not — the reason draws are stored at all."""
    row = db.execute(
        text(
            """
            SELECT c.wins_p2_5, c.wins_p97_5,
                   SUM(s.wins_p97_5 - s.wins_p2_5) AS naive_width
            FROM career_driver_sim c
            JOIN season_driver_sim s ON s.driver_id = c.driver_id AND s.run_id = c.run_id
            JOIN seasons se ON se.year = s.year AND se.is_complete = 1
            JOIN drivers d ON d.driver_id = c.driver_id
            WHERE c.run_id = :r AND d.driver_ref = 'hamilton'
            GROUP BY c.driver_id
            """
        ),
        {"r": run_id},
    ).one()

    true_width = row.wins_p97_5 - row.wins_p2_5
    assert row.naive_width > true_width


def test_in_progress_seasons_stay_out_of_careers(db, run_id):
    """A half-run season must not credit a driver with a full 24-race year."""
    in_progress = [
        r.year for r in db.execute(text("SELECT year FROM seasons WHERE is_complete = 0")).all()
    ]
    if not in_progress:
        pytest.skip("no in-progress season in this database")

    # Simulated for the Seasons tab...
    for year in in_progress:
        assert scalar(
            db, "SELECT COUNT(*) FROM season_driver_sim WHERE run_id = :r AND year = :y",
            r=run_id, y=year,
        ) > 0

    # ...but the career last_year never reaches it.
    assert scalar(
        db, "SELECT MAX(last_year) FROM career_driver_sim WHERE run_id = :r", r=run_id
    ) < min(in_progress)


def test_stored_draws_decode_to_the_stored_summary(db, run_id):
    """The blobs and the quantile columns must describe the same distribution."""
    rows = db.execute(
        text(
            """
            SELECT i.data, i.dtype, i.n_iterations, s.wins_mean, s.wins_median
            FROM sim_iterations i
            JOIN season_driver_sim s
              ON s.run_id = i.run_id AND s.year = i.year AND s.driver_id = i.entity_id
            WHERE i.run_id = :r AND i.entity_type = 'driver' AND i.metric = 'wins'
            LIMIT 40
            """
        ),
        {"r": run_id},
    ).all()
    assert rows

    for row in rows:
        draws = decode_draws(row.data, row.dtype, row.n_iterations)
        assert draws.mean() == pytest.approx(row.wins_mean, abs=1e-4)
        assert float(np.median(draws)) == pytest.approx(row.wins_median, abs=1e-9)


def test_wins_are_conserved_within_each_season(db, run_id):
    """24 races drawn means 24 wins handed out, every iteration."""
    year = scalar(db, "SELECT MAX(year) FROM season_driver_sim WHERE run_id = :r", r=run_id)
    rows = db.execute(
        text(
            """
            SELECT data, dtype, n_iterations FROM sim_iterations
            WHERE run_id = :r AND year = :y AND entity_type = 'driver' AND metric = 'wins'
            """
        ),
        {"r": run_id, "y": year},
    ).all()

    total = np.zeros(rows[0].n_iterations, dtype=np.int64)
    for row in rows:
        total += decode_draws(row.data, row.dtype, row.n_iterations).astype(np.int64)

    target = scalar(db, "SELECT target_races FROM sim_runs WHERE run_id = :r", r=run_id)
    assert np.all(total == target)


def test_title_probabilities_are_monotonic(db, run_id):
    rows = db.execute(
        text(
            """
            SELECT championships_at_least FROM career_driver_sim
            WHERE run_id = :r AND championships_mean > 0.5 LIMIT 50
            """
        ),
        {"r": run_id},
    ).all()
    assert rows

    for row in rows:
        probabilities = json.loads(row.championships_at_least)
        values = [probabilities[str(n)] for n in range(1, 11)]
        assert values == sorted(values, reverse=True)


def test_the_normalisation_lifts_short_era_drivers(db, run_id):
    """The point of the exercise, asserted.

    Fangio raced 7-9 race seasons and sits outside the top ten on raw wins.
    Normalised to 24 races he must rank far higher — if he does not, the
    correction is not being applied.
    """
    ranks = db.execute(
        text(
            """
            SELECT d.driver_ref,
                   RANK() OVER (ORDER BY c.actual_wins DESC) AS actual_rank,
                   RANK() OVER (ORDER BY c.wins_median DESC) AS sim_rank
            FROM career_driver_sim c JOIN drivers d ON d.driver_id = c.driver_id
            WHERE c.run_id = :r
            """
        ),
        {"r": run_id},
    ).all()
    by_ref = {row.driver_ref: row for row in ranks}

    fangio = by_ref["fangio"]
    assert fangio.actual_rank > 10
    assert fangio.sim_rank <= 5

    # And a modern driver with many races should not gain from it.
    hamilton = by_ref["hamilton"]
    assert hamilton.sim_rank <= hamilton.actual_rank + 1


def test_group_rows_exist_for_every_dimension(db, run_id):
    dimensions = dict(
        db.execute(
            text(
                "SELECT dimension, COUNT(*) FROM group_sim WHERE run_id = :r GROUP BY dimension"
            ),
            {"r": run_id},
        ).all()
    )
    assert set(dimensions) == {"constructor", "driver_nationality", "constructor_nationality"}
    assert all(count > 0 for count in dimensions.values())


def test_ferrari_leads_the_constructor_group(db, run_id):
    """A sanity anchor: no normalisation displaces Ferrari from most team wins."""
    top = db.execute(
        text(
            """
            SELECT group_label FROM group_sim
            WHERE run_id = :r AND dimension = 'constructor' AND metric = 'wins'
            ORDER BY median DESC LIMIT 1
            """
        ),
        {"r": run_id},
    ).scalar_one()
    assert top == "Ferrari"
