"""Invariants of the walk-forward scoring in `app.sim.backtest`.

The failure mode worth guarding against is a scorer that is quietly wrong in a
direction that flatters the model — a hit rate counting each pair twice, or a
drift term that never widens anything. Each of those still produces plausible
numbers, so the tests pin the pieces against cases with an answer known in
advance.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.sim.backtest import (
    drift_spread,
    pair_hit_rate,
    pair_log_loss,
    pair_margins,
    pair_win_probability,
    race_pairs,
    recent_surprise,
)
from app.sim.continuation import FormDynamics, expected_beat_fraction


class TestRacePairs:
    def test_every_pair_appears_once(self):
        ahead, behind = race_pairs(np.array([3, 1, 2, 0]))
        assert len(ahead) == 6  # 4 choose 2
        assert len(set(zip(ahead.tolist(), behind.tolist()))) == 6

    def test_the_winner_is_never_behind(self):
        ahead, behind = race_pairs(np.array([7, 4, 9]))
        assert 7 not in behind.tolist()

    def test_a_one_car_race_yields_nothing(self):
        ahead, behind = race_pairs(np.array([2]))
        assert len(ahead) == 0 and len(behind) == 0


class TestMargins:
    def test_a_correct_call_is_positive(self):
        log_strength = np.log(np.array([4.0, 1.0]))
        assert pair_margins(log_strength, np.array([0, 1]))[0] > 0

    def test_an_upset_is_negative(self):
        log_strength = np.log(np.array([4.0, 1.0]))
        assert pair_margins(log_strength, np.array([1, 0]))[0] < 0

    def test_a_perfect_ordering_scores_one(self):
        log_strength = np.log(np.array([3.0, 2.0, 1.0]))
        assert pair_hit_rate(pair_margins(log_strength, np.array([0, 1, 2]))) == 1.0

    def test_a_reversed_ordering_scores_zero(self):
        log_strength = np.log(np.array([3.0, 2.0, 1.0]))
        assert pair_hit_rate(pair_margins(log_strength, np.array([2, 1, 0]))) == 0.0

    def test_an_equal_field_scores_a_coin_flip(self):
        log_strength = np.zeros(4)
        assert pair_hit_rate(pair_margins(log_strength, np.array([0, 1, 2, 3]))) == 0.5


class TestWinProbability:
    def test_an_even_pair_is_a_coin_flip_at_any_drift(self):
        for spread in (0.0, 0.5, 3.0):
            assert pair_win_probability(np.array([0.0]), spread)[0] == pytest.approx(0.5)

    def test_no_drift_is_the_plackett_luce_pairwise_odds(self):
        """s_i / (s_i + s_j), the model the strengths were fitted under."""
        margin = np.log(np.array([3.0]))  # a 3:1 car
        assert pair_win_probability(margin, 0.0)[0] == pytest.approx(0.75)

    def test_drift_pulls_towards_a_coin_flip(self):
        margin = np.array([2.0])
        assert (
            0.5
            < pair_win_probability(margin, 2.0)[0]
            < pair_win_probability(margin, 0.5)[0]
            < pair_win_probability(margin, 0.0)[0]
        )

    def test_the_quadrature_matches_direct_integration(self):
        rng = np.random.default_rng(0)
        margins = np.array([-1.5, 0.3, 2.2])
        noise = rng.standard_normal(200_000)
        for spread in (0.6, 1.8):
            direct = np.array(
                [
                    (0.5 * (1 + np.tanh(0.5 * (m + spread * noise)))).mean()
                    for m in margins
                ]
            )
            assert pair_win_probability(margins, spread) == pytest.approx(
                direct, abs=2e-3
            )


class TestLogLoss:
    def test_a_coin_flip_costs_log_two(self):
        assert pair_log_loss(np.zeros(5)) == pytest.approx(np.log(2))

    def test_confident_and_right_beats_confident_and_wrong(self):
        assert pair_log_loss(np.array([2.0])) < pair_log_loss(np.array([-2.0]))

    def test_drift_is_insurance_against_being_confidently_wrong(self):
        """Which is why the half-life cannot be chosen on hit rate alone."""
        upsets = np.array([-3.0, -2.5, -3.5])
        assert pair_log_loss(upsets, spread=2.0) < pair_log_loss(upsets, spread=0.0)


class TestDriftSpread:
    def test_no_horizon_means_no_drift(self):
        assert drift_spread(FormDynamics(persistence=0.7, volatility=0.5), 0) == 0.0

    def test_a_static_model_never_drifts(self):
        assert drift_spread(FormDynamics(), 8) == 0.0

    def test_drift_grows_with_the_horizon(self):
        dynamics = FormDynamics(persistence=0.7, volatility=0.4)
        spreads = [drift_spread(dynamics, h) for h in range(1, 8)]
        assert np.all(np.diff(spreads) > 0)

    def test_mean_reversion_saturates_but_a_random_walk_does_not(self):
        reverting = FormDynamics(persistence=0.5, volatility=0.4)
        walking = FormDynamics(persistence=1.0, volatility=0.4)
        assert drift_spread(reverting, 40) == pytest.approx(
            drift_spread(reverting, 20), rel=1e-6
        )
        assert drift_spread(walking, 40) > drift_spread(walking, 20)

    def test_a_random_walk_grows_as_the_square_root_of_the_horizon(self):
        walking = FormDynamics(persistence=1.0, volatility=0.3)
        assert drift_spread(walking, 4) == pytest.approx(2 * drift_spread(walking, 1))

    def test_two_drivers_drift_independently(self):
        """The gap between them moves by sqrt(2) times either one's own drift."""
        one_step = FormDynamics(persistence=0.0, volatility=0.5)
        assert drift_spread(one_step, 1) == pytest.approx(0.5 * np.sqrt(2))


class TestRecentSurprise:
    def test_a_driver_who_meets_expectations_gains_nothing(self):
        """Two evenly matched drivers alternating wins is exactly par."""
        strength = np.ones(2)
        expected = expected_beat_fraction(strength)
        orderings = [np.array([0, 1]), np.array([1, 0])] * 4
        surprise = recent_surprise(orderings, expected, 2, persistence=1.0)
        assert surprise == pytest.approx(np.zeros(2), abs=1e-12)

    def test_over_performing_registers_positive(self):
        strength = np.array([4.0, 1.0])
        expected = expected_beat_fraction(strength)
        # The slower car wins every race: it is beating its own norm.
        surprise = recent_surprise(
            [np.array([1, 0])] * 3, expected, 2, persistence=1.0
        )
        assert surprise[1] > 0 > surprise[0]

    def test_decay_discounts_the_distant_past(self):
        strength = np.ones(2)
        expected = expected_beat_fraction(strength)
        early = [np.array([0, 1])] + [np.array([1, 0])] * 5
        assert recent_surprise(early, expected, 2, persistence=0.4)[0] > -0.9
        assert recent_surprise(early, expected, 2, persistence=1.0)[0] < -0.9

    def test_a_driver_who_sat_out_is_carried_unchanged(self):
        strength = np.ones(3)
        expected = expected_beat_fraction(strength)
        surprise = recent_surprise(
            [np.array([0, 1])] * 2, expected, 3, persistence=1.0
        )
        assert surprise[2] == 0.0


class TestExpectedBeatFraction:
    def test_an_even_field_expects_to_beat_half_of_it(self):
        assert expected_beat_fraction(np.ones(5)) == pytest.approx(np.full(5, 0.5))

    def test_the_quickest_expects_the_most(self):
        expected = expected_beat_fraction(np.array([9.0, 3.0, 1.0]))
        assert expected[0] > expected[1] > expected[2]

    def test_it_is_a_fraction(self):
        expected = expected_beat_fraction(np.array([100.0, 1.0, 0.01]))
        assert np.all((expected >= 0) & (expected <= 1))

    def test_an_ensemble_is_scored_row_by_row(self):
        ensemble = np.array([[4.0, 1.0], [1.0, 4.0]])
        expected = expected_beat_fraction(ensemble)
        assert expected.shape == (2, 2)
        assert expected[0, 0] == pytest.approx(expected[1, 1])

    def test_rarely_present_rivals_count_for_less(self):
        """Otherwise a regular is held to a standard set by absent part-timers."""
        strength = np.array([2.0, 2.0, 0.1])
        full = expected_beat_fraction(strength, np.array([1.0, 1.0, 1.0]))
        rare = expected_beat_fraction(strength, np.array([1.0, 1.0, 0.05]))
        assert full[0] > rare[0]
