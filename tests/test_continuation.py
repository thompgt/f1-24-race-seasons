"""Invariants of the season-continuation model.

The Plackett-Luce fit is the part that can be plausibly wrong: a maximum-
likelihood routine that has an off-by-one in its denominator still returns
positive strengths in roughly the right order, and only shows up as slightly
mis-shaped probabilities. The tests here pin it against cases with a known
answer.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.sim.continuation import (
    DEFAULT_HALF_LIFE,
    STATIC_FORM,
    FormDynamics,
    SeasonForm,
    champion_probability,
    fit_strengths,
    recency_weights,
    simulate_continuation,
)


def form(**overrides) -> SeasonForm:
    n = overrides.pop("n_drivers", 3)
    defaults = dict(
        year=2000,
        n_races=16,
        driver_ids=np.arange(n),
        points=np.zeros(n),
        wins=np.zeros(n),
        podiums=np.zeros(n),
        strength=np.ones(n),
        entry_rate=np.ones(n),
        dnf_rate=np.zeros(n),
    )
    defaults.update(overrides)
    return SeasonForm(**defaults)


class TestRecencyWeights:
    def test_the_latest_race_weighs_most(self):
        weights = recency_weights(10)
        assert weights[-1] > weights[0]
        assert np.all(np.diff(weights) > 0)

    def test_the_half_life_means_what_it_says(self):
        weights = recency_weights(21, half_life=5.0)
        assert weights[-6] == pytest.approx(weights[-1] / 2)

    def test_weights_average_one_whatever_the_season_length(self):
        """Keeps the shrinkage prior's strength comparable across eras."""
        for n in (6, 16, 24):
            assert recency_weights(n).mean() == pytest.approx(1.0)

    def test_an_empty_season_has_no_weights(self):
        assert len(recency_weights(0)) == 0


class TestFitStrengths:
    def test_a_consistent_winner_rates_highest(self):
        orders = [np.array([0, 1, 2]) for _ in range(10)]
        strength = fit_strengths(orders, np.ones(10), 3)
        assert strength[0] > strength[1] > strength[2]

    def test_an_evenly_matched_field_fits_equal_strengths(self):
        """Every driver wins as often as every other, so nothing separates them."""
        orders = [
            np.array([0, 1, 2]),
            np.array([1, 2, 0]),
            np.array([2, 0, 1]),
        ] * 4
        strength = fit_strengths(orders, np.ones(12), 3)
        assert strength == pytest.approx(np.full(3, strength[0]), rel=1e-6)

    def test_recency_outweighs_the_early_season(self):
        """The whole point of the model: who was quick at the end wins the
        extra races, not who averaged best across the year."""
        early = [np.array([0, 1]) for _ in range(8)]
        late = [np.array([1, 0]) for _ in range(4)]
        orders = early + late

        flat = fit_strengths(orders, np.ones(12), 2)
        weighted = fit_strengths(orders, recency_weights(12), 2)

        # On the raw record driver 0 is ahead; weighted by form, driver 1 is.
        assert flat[0] > flat[1]
        assert weighted[1] > weighted[0]

    def test_an_undefeated_driver_stays_finite(self):
        """Without the shrinkage prior this diverges — 1955 Mercedes would be
        assigned unbounded strength."""
        orders = [np.array([0, 1, 2]) for _ in range(20)]
        strength = fit_strengths(orders, np.ones(20), 3)
        assert np.all(np.isfinite(strength))
        assert strength[0] < 1e6

    def test_a_single_start_cannot_outrank_a_full_season(self):
        orders = [np.array([1, 2]) for _ in range(20)]
        orders.append(np.array([0, 1]))  # driver 0: one start, one win over 1
        strength = fit_strengths(orders, np.ones(len(orders)), 3)
        assert strength[0] < strength[1]

    def test_strengths_are_positive(self):
        orders = [np.array([0, 1, 2]), np.array([2, 1, 0])]
        assert np.all(fit_strengths(orders, np.ones(2), 3) > 0)

    def test_a_driver_who_never_raced_is_not_credited(self):
        """Only the prior speaks for them, so they sit at reference level."""
        orders = [np.array([0, 1]) for _ in range(10)]
        strength = fit_strengths(orders, np.ones(10), 3)
        assert strength[2] < strength[0]


class TestContinuation:
    def test_a_full_length_season_has_nothing_left_to_race(self):
        result = simulate_continuation(
            form(n_races=24, points=np.array([100.0, 50.0, 10.0])),
            rng=np.random.default_rng(1),
            n_iterations=50,
            target_races=24,
        )
        assert np.all(result["extra_races"] == 0)
        assert np.all(result["points"] == np.array([100.0, 50.0, 10.0]))

    def test_banked_points_are_carried_forward(self):
        result = simulate_continuation(
            form(n_races=20, points=np.array([80.0, 60.0, 5.0])),
            rng=np.random.default_rng(2),
            n_iterations=200,
            target_races=24,
        )
        # Nobody can end below what they had already scored.
        assert np.all(result["points"] >= np.array([80.0, 60.0, 5.0]))

    def test_exactly_one_winner_per_extra_race(self):
        result = simulate_continuation(
            form(n_drivers=6, n_races=18),
            rng=np.random.default_rng(3),
            n_iterations=300,
            target_races=24,
        )
        assert np.all(result["wins"].sum(axis=1) == 6)

    def test_a_stronger_driver_wins_more_of_the_extra_races(self):
        result = simulate_continuation(
            form(strength=np.array([8.0, 1.0, 1.0]), n_races=16),
            rng=np.random.default_rng(4),
            n_iterations=2000,
            target_races=24,
        )
        wins = result["wins"].mean(axis=0)
        assert wins[0] > wins[1] * 3

    def test_retirements_cost_points(self):
        reliable = simulate_continuation(
            form(strength=np.array([4.0, 1.0, 1.0]), n_races=16),
            rng=np.random.default_rng(5),
            n_iterations=1500,
            target_races=24,
        )
        fragile = simulate_continuation(
            form(
                strength=np.array([4.0, 1.0, 1.0]),
                dnf_rate=np.array([0.8, 0.0, 0.0]),
                n_races=16,
            ),
            rng=np.random.default_rng(5),
            n_iterations=1500,
            target_races=24,
        )
        assert fragile["points"].mean(axis=0)[0] < reliable["points"].mean(axis=0)[0]

    def test_a_part_season_driver_does_not_enter_every_extra_race(self):
        result = simulate_continuation(
            form(entry_rate=np.array([1.0, 1.0, 0.25]), n_races=16),
            rng=np.random.default_rng(6),
            n_iterations=2000,
            target_races=24,
        )
        # Eight extra races at a quarter entry rate: they cannot podium often.
        assert result["podiums"].mean(axis=0)[2] < result["podiums"].mean(axis=0)[0]

    def test_a_big_enough_lead_survives(self):
        """The model must not manufacture drama — a runaway season stays won."""
        result = simulate_continuation(
            form(
                points=np.array([400.0, 100.0, 50.0]),
                strength=np.array([3.0, 1.0, 1.0]),
                n_races=20,
            ),
            rng=np.random.default_rng(7),
            n_iterations=1000,
            target_races=24,
        )
        assert champion_probability(
            result["points"], result["wins"], result["podiums"]
        )[0] == pytest.approx(1.0)

    def test_a_close_finish_is_genuinely_open(self):
        result = simulate_continuation(
            form(
                points=np.array([210.0, 208.0, 100.0]),
                strength=np.array([1.0, 1.0, 0.5]),
                n_races=17,
            ),
            rng=np.random.default_rng(8),
            n_iterations=3000,
            target_races=24,
        )
        odds = champion_probability(result["points"], result["wins"], result["podiums"])
        assert 0.3 < odds[0] < 0.7
        assert 0.3 < odds[1] < 0.7

    def test_late_form_can_overturn_a_points_lead(self):
        """The behaviour the bootstrap cannot produce: the leader is caught
        because the chaser was the quicker car by the end."""
        result = simulate_continuation(
            form(
                points=np.array([200.0, 180.0, 60.0]),
                strength=np.array([1.0, 12.0, 0.5]),
                n_races=16,
            ),
            rng=np.random.default_rng(9),
            n_iterations=2000,
            target_races=24,
        )
        odds = champion_probability(result["points"], result["wins"], result["podiums"])
        assert odds[1] > odds[0]


class TestFormDynamics:
    """The extra races are a sequence, not a set of independent draws."""

    def test_static_form_is_the_default_and_changes_nothing(self):
        implicit = simulate_continuation(
            form(n_races=18),
            rng=np.random.default_rng(20),
            n_iterations=400,
            target_races=24,
        )
        explicit = simulate_continuation(
            form(n_races=18),
            rng=np.random.default_rng(20),
            n_iterations=400,
            target_races=24,
            dynamics=STATIC_FORM,
        )
        assert np.array_equal(implicit["points"], explicit["points"])

    def test_persistence_alone_is_still_static(self):
        """With nothing to persist, carrying it forward is a no-op."""
        assert FormDynamics(persistence=0.9).is_static

    def test_volatility_widens_the_spread_of_outcomes(self):
        """Pace that wanders makes the season less predictable, which is the
        whole reason a chaser has a route back into it."""
        fixed = simulate_continuation(
            form(strength=np.array([4.0, 2.0, 1.0]), n_races=16),
            rng=np.random.default_rng(21),
            n_iterations=3000,
            target_races=24,
        )
        drifting = simulate_continuation(
            form(strength=np.array([4.0, 2.0, 1.0]), n_races=16),
            rng=np.random.default_rng(21),
            n_iterations=3000,
            target_races=24,
            dynamics=FormDynamics(persistence=0.8, volatility=0.6),
        )
        assert drifting["points"].std(axis=0)[0] > fixed["points"].std(axis=0)[0]

    def test_momentum_makes_results_cluster(self):
        """A driver who wins one extra race should win the next more often than
        their overall rate — which is what a streak means, and what a model of
        independent races cannot produce."""
        streaky = simulate_continuation(
            form(n_drivers=4, strength=np.ones(4), n_races=16),
            rng=np.random.default_rng(22),
            n_iterations=6000,
            target_races=24,
            dynamics=FormDynamics(persistence=0.9, momentum=2.5),
        )
        flat = simulate_continuation(
            form(n_drivers=4, strength=np.ones(4), n_races=16),
            rng=np.random.default_rng(22),
            n_iterations=6000,
            target_races=24,
        )
        # In an even field nobody gains on average, so a wider spread of win
        # counts is exactly the clustering and not a change in who is quick.
        assert streaky["wins"].std() > flat["wins"].std() * 1.1
        assert streaky["wins"].mean() == pytest.approx(flat["wins"].mean(), rel=0.05)

    def test_an_even_field_stays_even_under_momentum(self):
        """Momentum must redistribute results, never invent an advantage."""
        result = simulate_continuation(
            form(n_drivers=4, strength=np.ones(4), n_races=16),
            rng=np.random.default_rng(23),
            n_iterations=4000,
            target_races=24,
            dynamics=FormDynamics(persistence=0.85, momentum=2.0),
        )
        wins = result["wins"].mean(axis=0)
        assert wins.max() - wins.min() < 0.25

    def test_the_band_caps_a_runaway_streak(self):
        gentle = simulate_continuation(
            form(n_drivers=4, n_races=12),
            rng=np.random.default_rng(24),
            n_iterations=2000,
            target_races=24,
            dynamics=FormDynamics(persistence=1.0, momentum=4.0, band=0.5),
        )
        # Nobody can run away with every remaining race on form alone.
        assert gentle["wins"].max() < 12

    def test_drift_helps_the_quicker_chaser_more_than_the_leader(self):
        """The behaviour the whole change exists for: a driver fitted faster but
        behind on points gains from the season staying live."""
        setup = dict(
            points=np.array([260.0, 210.0, 90.0]),
            strength=np.array([1.0, 2.2, 0.4]),
            n_races=16,
        )
        fixed = simulate_continuation(
            form(**setup),
            rng=np.random.default_rng(25),
            n_iterations=6000,
            target_races=24,
        )
        drifting = simulate_continuation(
            form(**setup),
            rng=np.random.default_rng(25),
            n_iterations=6000,
            target_races=24,
            dynamics=FormDynamics(persistence=0.8, volatility=0.5, momentum=1.0),
        )
        chaser = lambda r: champion_probability(r["points"], r["wins"], r["podiums"])[1]
        assert chaser(drifting) > chaser(fixed)

    def test_a_settled_season_stays_settled_under_drift(self):
        """Drift must not manufacture drama where the points do not allow it."""
        result = simulate_continuation(
            form(
                points=np.array([420.0, 120.0, 60.0]),
                strength=np.array([3.0, 1.0, 1.0]),
                n_races=20,
            ),
            rng=np.random.default_rng(26),
            n_iterations=2000,
            target_races=24,
            dynamics=FormDynamics(persistence=0.8, volatility=0.6, momentum=1.5),
        )
        odds = champion_probability(result["points"], result["wins"], result["podiums"])
        assert odds[0] == pytest.approx(1.0)


class TestLeadShare:
    def test_it_covers_the_banked_standings_and_every_extra_race(self):
        result = simulate_continuation(
            form(points=np.array([50.0, 40.0, 5.0]), n_races=20),
            rng=np.random.default_rng(30),
            n_iterations=500,
            target_races=24,
        )
        assert result["lead_share"].shape == (5, 3)  # 4 extra races plus the start

    def test_it_starts_from_who_was_actually_leading(self):
        result = simulate_continuation(
            form(points=np.array([50.0, 40.0, 5.0]), n_races=20),
            rng=np.random.default_rng(31),
            n_iterations=500,
            target_races=24,
        )
        assert result["lead_share"][0] == pytest.approx(np.array([1.0, 0.0, 0.0]))

    def test_it_ends_on_the_title_odds(self):
        result = simulate_continuation(
            form(points=np.array([50.0, 40.0, 5.0]), strength=np.array([1.0, 3.0, 0.2])),
            rng=np.random.default_rng(32),
            n_iterations=800,
            target_races=24,
        )
        final = champion_probability(
            result["points"], result["wins"], result["podiums"]
        )
        assert result["lead_share"][-1] == pytest.approx(final)

    def test_every_race_shares_one_leader_between_them(self):
        result = simulate_continuation(
            form(n_drivers=5, n_races=18),
            rng=np.random.default_rng(33),
            n_iterations=400,
            target_races=24,
        )
        assert result["lead_share"].sum(axis=1) == pytest.approx(np.ones(7))

    def test_a_completed_season_reports_only_its_final_standings(self):
        result = simulate_continuation(
            form(n_races=24, points=np.array([9.0, 4.0, 1.0])),
            rng=np.random.default_rng(34),
            n_iterations=100,
            target_races=24,
        )
        assert result["lead_share"].shape == (1, 3)


class TestChampionProbability:
    def test_probabilities_sum_to_one(self):
        rng = np.random.default_rng(11)
        points = rng.random((500, 4)) * 100
        wins = rng.integers(0, 5, (500, 4))
        podiums = rng.integers(0, 9, (500, 4))
        assert champion_probability(points, wins, podiums).sum() == pytest.approx(1.0)

    def test_ties_on_points_fall_to_the_win_countback(self):
        points = np.array([[100.0, 100.0]])
        wins = np.array([[2, 5]])
        podiums = np.array([[9, 9]])
        assert champion_probability(points, wins, podiums) == pytest.approx([0.0, 1.0])

    def test_ties_on_points_and_wins_fall_to_podiums(self):
        points = np.array([[100.0, 100.0]])
        wins = np.array([[3, 3]])
        podiums = np.array([[4, 8]])
        assert champion_probability(points, wins, podiums) == pytest.approx([0.0, 1.0])
