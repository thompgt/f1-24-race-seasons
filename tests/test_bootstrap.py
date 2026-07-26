"""Invariants of the 24-race bootstrap.

Pure numpy, no database. The statistical assertions here are the ones that
actually catch mistakes: an off-by-one in the matrix layout or a wrong axis in
the multinomial still produces plausible-looking numbers, but breaks the identity
between the bootstrap mean and the pro-rata projection.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.sim.bootstrap import simulate_season, summarise
from app.sim.events import build_event_set

SEED = 20240424


def make_season(
    year: int = 1960,
    *,
    finishing_orders: list[list[int]],
    n_drivers: int = 6,
    sprint_rounds: dict[int, list[int]] | None = None,
):
    """Build an event set from explicit finishing orders.

    `finishing_orders[r]` lists driver ids in finishing order for race r, so
    `[[0, 1, 2], [1, 0, 2]]` is a two-race season where driver 0 wins the first.
    """
    from app.sim import scoring

    race_ids = np.arange(len(finishing_orders))
    driver_ids = np.arange(n_drivers)
    # One constructor per pair of drivers, so constructor totals are non-trivial.
    constructor_of = {d: d // 2 for d in range(n_drivers)}
    constructor_ids = np.arange((n_drivers + 1) // 2)

    race_id, driver_id, constructor_id, positions = [], [], [], []
    for r, order in enumerate(finishing_orders):
        for place, driver in enumerate(order, start=1):
            race_id.append(r)
            driver_id.append(driver)
            constructor_id.append(constructor_of[driver])
            positions.append(place)

    positions_arr = np.array(positions, dtype=np.intp)
    points = scoring.race_points(positions_arr)

    sprint_rows = None
    if sprint_rounds:
        s_race, s_driver, s_ctor, s_points = [], [], [], []
        for r, order in sprint_rounds.items():
            for place, driver in enumerate(order, start=1):
                s_race.append(r)
                s_driver.append(driver)
                s_ctor.append(constructor_of[driver])
                s_points.append(float(scoring.sprint_points(np.array([place]))[0]))
        sprint_rows = {
            "race_id": np.array(s_race),
            "driver_id": np.array(s_driver),
            "constructor_id": np.array(s_ctor, dtype=float),
            "points": np.array(s_points),
        }

    return build_event_set(
        year,
        race_ids=race_ids,
        driver_ids=driver_ids,
        constructor_ids=constructor_ids,
        rows={
            "race_id": np.array(race_id),
            "driver_id": np.array(driver_id),
            "constructor_id": np.array(constructor_id, dtype=float),
            "points": points,
            "points_no_fl": points,
            "is_win": (positions_arr == 1).astype(np.float32),
            "is_podium": (positions_arr <= 3).astype(np.float32),
        },
        pole_driver_ids=[order[0] for order in finishing_orders],
        sprint_rows=sprint_rows,
    )


def rotating_season(n_races: int, n_drivers: int = 6) -> list[list[int]]:
    """A season where the winner rotates, so no driver dominates."""
    return [[(d + r) % n_drivers for d in range(n_drivers)] for r in range(n_races)]


# --- The identity that validates the whole construction ----------------------


@pytest.mark.parametrize("n_races", [1, 3, 7, 16, 24, 30])
def test_bootstrap_mean_equals_the_pro_rata_projection(n_races):
    """mean(bootstrap) must converge on actual x 24/R.

    Each race is drawn with equal probability and every metric is additive, so
    the expected simulated total is exactly the naive scaled figure. This one
    assertion covers the multinomial reformulation, the matrix construction and
    the pro-rata column shown in the UI.
    """
    events = make_season(finishing_orders=rotating_season(n_races))
    result = simulate_season(events, master_seed=SEED, n_iterations=4000)

    for metric in ("points", "wins", "podiums", "poles", "entries"):
        draws = result.driver.totals[metric]
        expected = result.driver.scaled[metric]
        tolerance = 4 * draws.std(axis=0) / np.sqrt(draws.shape[0]) + 1e-6
        assert np.all(np.abs(draws.mean(axis=0) - expected) <= tolerance), metric


def test_a_single_race_season_has_no_spread():
    """With one race to draw from, every iteration is that race 24 times."""
    events = make_season(finishing_orders=[[0, 1, 2, 3, 4, 5]])
    result = simulate_season(events, master_seed=SEED, n_iterations=200)

    wins = result.driver.totals["wins"]
    # Across iterations, per driver — not across drivers, who legitimately differ.
    assert np.all(wins.std(axis=0) == 0.0)
    assert np.all(wins[:, 0] == 24)
    assert np.all(wins[:, 1] == 0)
    # 25 points a race, 24 races.
    assert np.all(result.driver.totals["points"][:, 0] == 600)


def test_a_full_length_season_is_still_resampled():
    """A 24-race season has spread, and its mean is its actual total."""
    events = make_season(finishing_orders=rotating_season(24))
    result = simulate_season(events, master_seed=SEED, n_iterations=4000)

    wins = result.driver.totals["wins"]
    assert wins.std() > 0, "resampling 24 of 24 with replacement is not the identity"
    assert np.allclose(wins.mean(axis=0), result.driver.actual["wins"], atol=0.15)


# --- Conservation ------------------------------------------------------------


def test_every_iteration_awards_exactly_one_win_per_race():
    events = make_season(finishing_orders=rotating_season(11))
    result = simulate_season(events, master_seed=SEED, n_iterations=500)
    assert np.all(result.driver.totals["wins"].sum(axis=1) == 24)


def test_every_iteration_awards_exactly_one_pole_per_race():
    events = make_season(finishing_orders=rotating_season(11))
    result = simulate_season(events, master_seed=SEED, n_iterations=500)
    assert np.all(result.driver.totals["poles"].sum(axis=1) == 24)


def test_driver_and_constructor_points_agree():
    events = make_season(finishing_orders=rotating_season(9))
    result = simulate_season(events, master_seed=SEED, n_iterations=500)
    assert np.allclose(
        result.driver.totals["points"].sum(axis=1),
        result.constructor.totals["points"].sum(axis=1),
    )


def test_sprints_travel_with_their_weekend():
    """A sprint is part of the weekend drawn, not an independent event.

    Over 24 drawn weekends from a 12-race season with 3 sprints, the expected
    number of sprints is 24 x 3/12 = 6.
    """
    events = make_season(
        finishing_orders=rotating_season(12),
        sprint_rounds={0: [0, 1, 2], 4: [1, 2, 0], 8: [2, 0, 1]},
    )
    result = simulate_season(events, master_seed=SEED, n_iterations=4000)

    total_sprint_points = result.driver.totals["sprint_points"].sum(axis=1)
    per_sprint = 8 + 7 + 6
    assert np.isclose(total_sprint_points.mean() / per_sprint, 6.0, atol=0.1)
    assert total_sprint_points.std() > 0


# --- Championships -----------------------------------------------------------


def test_champion_probabilities_form_a_distribution():
    events = make_season(finishing_orders=rotating_season(10))
    result = simulate_season(events, master_seed=SEED, n_iterations=2000)
    probabilities = result.driver.champion_probability()

    assert np.isclose(probabilities.sum(), 1.0)
    assert np.all(probabilities >= 0)


def test_a_dominant_driver_always_takes_the_title():
    """Driver 0 wins every race, so no resampling can dethrone them."""
    n_drivers = 6
    orders = [[0] + [(d + r) % (n_drivers - 1) + 1 for d in range(n_drivers - 1)]
              for r in range(10)]
    events = make_season(finishing_orders=orders, n_drivers=n_drivers)
    result = simulate_season(events, master_seed=SEED, n_iterations=500)

    assert result.driver.champion_probability()[0] == 1.0


def test_championship_ties_break_on_wins():
    """Two drivers level on points: the one with more wins takes the title.

    Driver 0 wins both races and finishes last twice; driver 1 is second twice
    and third twice. Constructed so a points tie is possible under resampling.
    """
    orders = [
        [0, 1, 2, 3],
        [0, 1, 2, 3],
        [3, 2, 1, 0],
        [3, 2, 1, 0],
    ]
    events = make_season(finishing_orders=orders, n_drivers=4)
    result = simulate_season(events, master_seed=SEED, n_iterations=2000)

    standings = result.driver.totals["points"] + result.driver.totals["sprint_points"]
    champion = result.driver.champion_index
    rows = np.arange(len(champion))

    # The declared champion is never beaten on points by anyone else.
    assert np.all(standings[rows, champion] == standings.max(axis=1))

    # Where the top score is shared, the champion holds the most wins among those tied.
    tied = standings == standings.max(axis=1, keepdims=True)
    champion_wins = result.driver.totals["wins"][rows, champion]
    best_tied_wins = np.where(tied, result.driver.totals["wins"], -1).max(axis=1)
    assert np.all(champion_wins == best_tied_wins)


def test_championship_draws_are_one_hot():
    events = make_season(finishing_orders=rotating_season(8))
    result = simulate_season(events, master_seed=SEED, n_iterations=300)
    draws = result.driver.championship_draws()

    assert draws.shape == (300, len(result.driver.ids))
    assert np.all(draws.sum(axis=1) == 1)


# --- Reproducibility ---------------------------------------------------------


def test_the_same_seed_reproduces_the_same_draws():
    events = make_season(finishing_orders=rotating_season(13))
    first = simulate_season(events, master_seed=SEED, n_iterations=500)
    second = simulate_season(events, master_seed=SEED, n_iterations=500)
    assert np.array_equal(first.driver.totals["points"], second.driver.totals["points"])


def test_a_different_seed_gives_different_draws():
    events = make_season(finishing_orders=rotating_season(13))
    first = simulate_season(events, master_seed=SEED, n_iterations=500)
    second = simulate_season(events, master_seed=SEED + 1, n_iterations=500)
    assert not np.array_equal(first.driver.totals["points"], second.driver.totals["points"])


def test_a_season_stream_does_not_depend_on_other_seasons():
    """Deriving each stream from (seed, year) is what makes --jobs N identical.

    If seasons shared one generator, the same year would draw differently
    depending on how many seasons ran before it.
    """
    events_a = make_season(year=1975, finishing_orders=rotating_season(14))
    events_b = make_season(year=1975, finishing_orders=rotating_season(14))

    # Simulating another season in between must not perturb 1975.
    first = simulate_season(events_a, master_seed=SEED, n_iterations=400)
    simulate_season(
        make_season(year=1999, finishing_orders=rotating_season(16)),
        master_seed=SEED,
        n_iterations=400,
    )
    second = simulate_season(events_b, master_seed=SEED, n_iterations=400)

    assert np.array_equal(first.driver.totals["wins"], second.driver.totals["wins"])


# --- Summaries ---------------------------------------------------------------


def test_summarise_reports_an_ordered_interval():
    events = make_season(finishing_orders=rotating_season(10))
    result = simulate_season(events, master_seed=SEED, n_iterations=2000)
    stats = summarise(result.driver.totals["wins"])

    assert np.all(stats["p2_5"] <= stats["median"])
    assert np.all(stats["median"] <= stats["p97_5"])
    assert np.all(stats["std"] >= 0)


def test_iteration_draws_round_trip_as_integers():
    events = make_season(finishing_orders=rotating_season(10))
    result = simulate_season(events, master_seed=SEED, n_iterations=200)

    for metric in ("wins", "podiums", "poles", "entries"):
        draws = result.driver.iteration_draws(metric)
        assert draws.dtype == np.uint8
        assert np.array_equal(draws, result.driver.totals[metric].astype(np.uint8))

    points = result.driver.iteration_draws("points")
    assert points.dtype == np.uint16
    assert np.array_equal(points, result.driver.totals["points"].astype(np.uint16))


def test_an_empty_season_is_rejected():
    events = make_season(finishing_orders=[])
    with pytest.raises(ValueError, match="no races"):
        simulate_season(events, master_seed=SEED)
