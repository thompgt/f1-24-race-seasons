"""Career aggregation, and the reason it cannot be done from summaries."""

from __future__ import annotations

import numpy as np
import pytest

from app.sim.bootstrap import simulate_season
from app.sim.career import (
    Summary,
    aggregate_career,
    aggregate_group,
    decode_draws,
    encode_draws,
    probability_at_least,
    sum_across_seasons,
)
from tests.test_bootstrap import SEED, make_season, rotating_season


def test_blobs_round_trip():
    draws = np.array([0, 1, 2, 250, 7], dtype=np.uint8)
    restored = decode_draws(encode_draws(draws), "uint8", len(draws))
    assert np.array_equal(restored, draws)


def test_decoding_the_wrong_length_is_rejected():
    blob = encode_draws(np.zeros(5, dtype=np.uint8))
    with pytest.raises(ValueError, match="Expected 9 draws"):
        decode_draws(blob, "uint8", 9)


def test_career_totals_add_elementwise():
    a = np.array([1, 2, 3])
    b = np.array([10, 20, 30])
    assert sum_across_seasons([a, b]).tolist() == [11, 22, 33]


def test_misaligned_seasons_are_rejected():
    """Iteration k of every season must be the same joint sample."""
    with pytest.raises(ValueError, match="differing lengths"):
        sum_across_seasons([np.zeros(10), np.zeros(9)])


def test_career_sums_do_not_overflow_compact_storage():
    """Draws are stored as uint8; a long career would wrap without a wider sum."""
    seasons = {year: np.full(100, 200, dtype=np.uint8) for year in range(20)}
    _, career = aggregate_career(seasons)
    assert career.dtype == np.int64
    assert np.all(career == 4000)


# --- Why medians cannot be summed --------------------------------------------


def test_mean_is_additive_but_median_is_not():
    """The invariant that holds, and the one that does not.

    Both are asserted together because the first is what the batch job checks
    itself against, and the second is why it cannot take the cheaper route.
    """
    rng = np.random.default_rng(0)
    # Right-skewed counts, like per-season win totals for a midfield driver.
    seasons = {year: rng.poisson(0.7, size=20_000) for year in range(15)}
    summary, career = aggregate_career(seasons)

    sum_of_means = sum(float(v.mean()) for v in seasons.values())
    assert summary.mean == pytest.approx(sum_of_means, rel=1e-9)

    sum_of_medians = sum(float(np.median(v)) for v in seasons.values())
    # Every season's median is 1 here, so the naive route reports 15 careers wins
    # against a true median around 10 — the bias this module exists to avoid.
    assert abs(summary.median - sum_of_medians) >= 3


def test_summed_intervals_are_wider_than_the_true_interval():
    """Variances add; interval half-widths do not."""
    rng = np.random.default_rng(1)
    seasons = {year: rng.poisson(3.0, size=20_000) for year in range(10)}
    summary, _ = aggregate_career(seasons)

    true_width = summary.p97_5 - summary.p2_5
    naive_width = sum(
        float(np.percentile(v, 97.5) - np.percentile(v, 2.5)) for v in seasons.values()
    )
    assert naive_width > true_width * 1.8


# --- Against the real simulation ---------------------------------------------


def test_career_mean_matches_the_sum_of_season_means():
    """Linearity holds exactly, so this catches misaligned career vectors."""
    draws = {}
    season_means = []
    for year in (1955, 1956, 1957):
        events = make_season(year=year, finishing_orders=rotating_season(8 + year % 5))
        result = simulate_season(events, master_seed=SEED, n_iterations=2000)
        wins = result.driver.totals["wins"][:, 0]
        draws[year] = wins
        season_means.append(float(wins.mean()))

    summary, _ = aggregate_career(draws)
    # Tolerance is float32 epsilon, not the identity's: the simulation's totals
    # are float32, while the career vector accumulates in int64 and is exact.
    assert summary.mean == pytest.approx(sum(season_means), rel=1e-6)


def test_group_totals_roll_up_careers():
    rng = np.random.default_rng(2)
    first = rng.poisson(2.0, size=5000)
    second = rng.poisson(5.0, size=5000)
    summary, total = aggregate_group([first, second])

    assert np.array_equal(total, first.astype(np.int64) + second.astype(np.int64))
    assert summary.mean == pytest.approx(float(first.mean() + second.mean()), rel=1e-9)


def test_championship_thresholds_are_monotonic():
    """P(>= n) can only fall as n rises."""
    rng = np.random.default_rng(3)
    titles = rng.binomial(1, 0.4, size=(10_000, 12)).sum(axis=1)
    probabilities = probability_at_least(titles, range(1, 9))

    values = [probabilities[n] for n in range(1, 9)]
    assert values == sorted(values, reverse=True)
    assert probabilities[1] > probabilities[8]


def test_championship_probability_reflects_the_draws():
    titles = np.array([0, 1, 1, 2, 3])
    assert probability_at_least(titles, [1]) == {1: 0.8}
    assert probability_at_least(titles, [3]) == {3: 0.2}


def test_summary_interval_is_ordered():
    summary = Summary.of(np.random.default_rng(4).poisson(4.0, size=5000))
    assert summary.p2_5 <= summary.median <= summary.p97_5
    assert summary.std > 0


def test_an_empty_career_is_rejected():
    with pytest.raises(ValueError, match="No seasons"):
        sum_across_seasons([])
