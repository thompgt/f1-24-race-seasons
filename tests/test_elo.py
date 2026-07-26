"""Invariants of the Elo engine and the win-difficulty measure.

Elo is easy to implement plausibly and wrongly — a flipped sign or a missing
normalisation still produces numbers that rise and fall in roughly the right
direction. The assertions here pin the properties that a wrong implementation
would break.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.sim.elo import (
    INITIAL_RATING,
    Race,
    RaceEntry,
    expected_positions,
    expected_score,
    peak_ratings,
    rate,
    rate_with_priors,
    win_difficulty,
)


def race(race_id: int, year: int, round_: int, finishers, *, teams=None, dnf=()):
    """A race where `finishers` is driver ids in finishing order."""
    entries = [
        RaceEntry(
            driver_id=driver,
            constructor_id=(teams or {}).get(driver, driver),
            position=i + 1,
        )
        for i, driver in enumerate(finishers)
    ]
    entries += [
        RaceEntry(driver_id=driver, constructor_id=(teams or {}).get(driver, driver), position=None)
        for driver in dnf
    ]
    return Race(race_id=race_id, year=year, round=round_, entries=tuple(entries))


def season(year: int, finishers, n: int = 10, **kwargs):
    return [race(year * 100 + i, year, i, finishers, **kwargs) for i in range(1, n + 1)]


class TestExpectedScore:
    def test_equal_ratings_are_a_coin_flip(self):
        assert expected_score(np.array([1500.0]), np.array([1500.0])) == pytest.approx(0.5)

    def test_the_scale_means_what_it_says(self):
        # A 400-point edge is the chess convention for winning ~10 times in 11.
        edge = expected_score(np.array([1900.0]), np.array([1500.0]))
        assert edge == pytest.approx(10 / 11, abs=1e-3)

    def test_probabilities_are_complementary(self):
        a, b = np.array([1700.0]), np.array([1450.0])
        assert expected_score(a, b) + expected_score(b, a) == pytest.approx(1.0)


class TestExpectedPositions:
    def test_expected_positions_sum_to_the_positions_available(self):
        """Sum of expected finishes == 1 + 2 + ... + n, for any ratings.

        Each pair contributes exactly 1.0 between its two members, so the total
        is fixed however the ratings are arranged. This catches a transposed
        comparison matrix, which otherwise produces entirely plausible numbers.
        """
        ratings = np.array([1820.0, 1500.0, 1610.0, 1290.0, 1500.0])
        n = len(ratings)
        assert expected_positions(ratings).sum() == pytest.approx(n * (n + 1) / 2)

    def test_an_evenly_matched_field_expects_the_midpoint(self):
        ratings = np.full(9, 1500.0)
        assert expected_positions(ratings) == pytest.approx(np.full(9, 5.0))

    def test_the_strongest_car_has_the_lowest_expected_position(self):
        expected = expected_positions(np.array([1500.0, 2000.0, 1200.0]))
        assert expected.argmin() == 1
        assert expected.argmax() == 2


class TestRating:
    def test_beating_an_equal_field_raises_the_rating(self):
        result = rate([race(1, 2000, 1, [10, 20, 30])])
        winner = next(s for s in result.snapshots if s.driver_id == 10)
        assert winner.rating_after > winner.rating_before

    def test_a_race_is_zero_sum_across_its_classified_finishers(self):
        """Ratings are redistributed, not created — within a single race."""
        result = rate([race(1, 2000, 1, [10, 20, 30, 40, 50])])
        movement = sum(s.rating_after - s.rating_before for s in result.snapshots)
        assert movement == pytest.approx(0.0, abs=1e-9)

    def test_an_expected_win_is_worth_less_than_an_upset(self):
        favourite = rate([race(1, 2000, 1, [10, 20])], priors={10: 1900, 20: 1500})
        underdog = rate([race(1, 2000, 1, [10, 20])], priors={10: 1500, 20: 1900})
        gain = lambda r: next(  # noqa: E731
            s.rating_after - s.rating_before for s in r.snapshots if s.driver_id == 10
        )
        assert gain(underdog) > gain(favourite)

    def test_a_race_moves_a_rating_by_at_most_k(self):
        """Field size must not scale the update, or a 24-car grid would move
        ratings three times faster than an 8-car one for no sporting reason."""
        small = rate([race(1, 2000, 1, [10, 20, 30])], k_factor=24, provisional_races=0)
        large = rate([race(1, 2000, 1, list(range(10, 34)))], k_factor=24, provisional_races=0)
        for result in (small, large):
            for snapshot in result.snapshots:
                assert abs(snapshot.rating_after - snapshot.rating_before) <= 24 + 1e-9

    def test_retirements_neither_gain_nor_lose(self):
        result = rate([race(1, 2000, 1, [10, 20, 30], dnf=[40])])
        retired = next(s for s in result.snapshots if s.driver_id == 40)
        assert retired.rating_after == pytest.approx(retired.rating_before)

    def test_a_retirement_does_not_alter_the_others(self):
        without = rate([race(1, 2000, 1, [10, 20, 30])])
        with_dnf = rate([race(1, 2000, 1, [10, 20, 30], dnf=[40, 50])])
        for driver in (10, 20, 30):
            a = next(s.rating_after for s in without.snapshots if s.driver_id == driver)
            b = next(s.rating_after for s in with_dnf.snapshots if s.driver_id == driver)
            assert a == pytest.approx(b)

    def test_provisional_drivers_move_faster(self):
        settled = rate(
            [race(1, 2000, 1, [10, 20])], k_factor=24, provisional_k=48, provisional_races=0
        )
        rookie = rate(
            [race(1, 2000, 1, [10, 20])], k_factor=24, provisional_k=48, provisional_races=5
        )
        gain = lambda r: next(  # noqa: E731
            s.rating_after - s.rating_before for s in r.snapshots if s.driver_id == 10
        )
        assert gain(rookie) == pytest.approx(2 * gain(settled))

    def test_rating_vs_field_is_measured_against_the_grid_present(self):
        result = rate([race(1, 2000, 1, [10, 20, 30])], priors={10: 1800, 20: 1500, 30: 1200})
        margins = {s.driver_id: s.rating_vs_field for s in result.snapshots}
        assert margins[10] == pytest.approx(300.0)
        assert margins[20] == pytest.approx(0.0)
        assert margins[30] == pytest.approx(-300.0)


class TestTeammateRating:
    def test_beating_a_teammate_raises_the_teammate_rating(self):
        teams = {10: 1, 20: 1, 30: 2, 40: 2}
        result = rate([race(1, 2000, 1, [10, 30, 20, 40], teams=teams)])
        by_driver = {s.driver_id: s for s in result.snapshots}
        assert by_driver[10].teammate_rating_after > by_driver[10].teammate_rating_before
        assert by_driver[20].teammate_rating_after < by_driver[20].teammate_rating_before

    def test_a_driver_with_no_teammate_is_unrated(self):
        teams = {10: 1, 20: 2, 30: 3}
        result = rate([race(1, 2000, 1, [10, 20, 30], teams=teams)])
        for snapshot in result.snapshots:
            assert snapshot.teammate_rating_after == pytest.approx(INITIAL_RATING)

    def test_finishing_order_beyond_the_teammate_is_irrelevant(self):
        """Team-mate rating must not leak information about the wider field —
        that is the whole reason it exists."""
        teams = {10: 1, 20: 1, 30: 2, 40: 2}
        ahead = rate([race(1, 2000, 1, [10, 20, 30, 40], teams=teams)])
        split = rate([race(1, 2000, 1, [10, 30, 40, 20], teams=teams)])
        first = next(s.teammate_rating_after for s in ahead.snapshots if s.driver_id == 10)
        second = next(s.teammate_rating_after for s in split.snapshots if s.driver_id == 10)
        assert first == pytest.approx(second)


class TestPriors:
    def test_priors_are_the_starting_point(self):
        result = rate([race(1, 2000, 1, [10, 20])], priors={10: 1700.0, 20: 1300.0})
        before = {s.driver_id: s.rating_before for s in result.snapshots}
        assert before == pytest.approx({10: 1700.0, 20: 1300.0})

    def test_a_second_pass_differentiates_the_opening_season(self):
        """A single pass rates everyone at 1500 for race one, so the earliest
        races carry no information about who was actually quick. Seeding from a
        prior pass is what removes that artefact."""
        races = season(1950, [10, 20, 30]) + season(1951, [10, 20, 30])
        one = rate(races)
        two = rate_with_priors(races, passes=2)

        opener = lambda r: {  # noqa: E731
            s.driver_id: s.rating_before for s in r.snapshots if s.race_id == 195001
        }
        assert len(set(opener(one).values())) == 1  # everyone identical
        assert opener(two)[10] > opener(two)[30]  # the quick one starts ahead

    def test_a_second_pass_moves_early_races_more_than_late_ones(self):
        """The correction is meant to be front-loaded: it fixes what the first
        pass could not know in 1950 and leaves a settled rating alone."""
        races = season(1950, [10, 20, 30]) + season(1951, [10, 20, 30])
        one, two = rate(races), rate_with_priors(races, passes=2)

        def rating_at(result, race_id, driver):
            return next(
                s.rating_before
                for s in result.snapshots
                if s.race_id == race_id and s.driver_id == driver
            )

        first = abs(rating_at(one, 195001, 10) - rating_at(two, 195001, 10))
        last = abs(rating_at(one, 195110, 10) - rating_at(two, 195110, 10))
        assert first > last

    def test_a_decisive_ordering_survives_a_second_pass(self):
        races = season(1950, [10, 20, 30]) + season(1951, [10, 20, 30])
        one, two = rate(races), rate_with_priors(races, passes=2)
        assert one.final[10] > one.final[20] > one.final[30]
        assert two.final[10] > two.final[20] > two.final[30]


class TestWinDifficulty:
    def test_the_average_win_in_history_is_worth_one(self):
        """The normalisation is what makes quality-adjusted wins comparable with
        raw wins on the same axis."""
        races = season(1950, [10, 20, 30]) + season(1951, [20, 30, 10])
        credit = win_difficulty(rate_with_priors(races).snapshots)
        assert np.mean(list(credit.values())) == pytest.approx(1.0)

    def test_only_winners_are_credited(self):
        credit = win_difficulty(rate([race(1, 2000, 1, [10, 20, 30])]).snapshots)
        assert set(credit) == {(1, 10)}

    def test_a_dominant_driver_earns_less_per_win(self):
        """The point of the whole feature: 20 wins against no opposition should
        not score the same as 20 wins against a field that could beat you."""
        walkover = rate(season(2000, [10, 20, 30, 40], n=40)).snapshots
        contested = rate(
            [
                race(2001_00 + i, 2001, i, [10, 20, 30, 40] if i % 2 else [20, 10, 30, 40])
                for i in range(1, 41)
            ]
        ).snapshots
        easy = np.mean([s.expected_position for s in walkover[-20:] if s.position == 1])
        hard = np.mean([s.expected_position for s in contested[-20:] if s.position == 1])
        assert hard > easy

    def test_no_wins_yields_no_credit(self):
        assert win_difficulty([]) == {}


class TestPeaks:
    def test_the_peak_is_sustained_rather_than_instantaneous(self):
        """One outlier race must not define a career peak."""
        races = season(2000, [10, 20, 30], n=30)
        snapshots = rate(races).snapshots
        peaks = peak_ratings(snapshots, min_races=0, window=10)
        best_single = max(s.rating_after for s in snapshots if s.driver_id == 10)
        assert peaks[10]["peak"] <= best_single

    def test_race_counts_are_reported(self):
        peaks = peak_ratings(rate(season(2000, [10, 20], n=7)).snapshots, min_races=0)
        assert peaks[10]["races"] == 7
