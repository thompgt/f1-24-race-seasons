"""Career and group totals, summed across seasons.

The one decision here that materially changes the leaderboards: a career total is
built by summing the *per-iteration draws* across a driver's seasons and taking
percentiles of that, never by summing per-season medians.

Season bootstraps are mutually independent — each resamples only its own races,
from its own RNG stream — so pairing iteration k of 1950 with iteration k of 1951
is a valid draw from the joint distribution. That makes the summed vector a
legitimate sample of the career total.

Summing medians is wrong, and not harmlessly so:

  * median(sum) != sum(median). Per-season win counts are small, right-skewed
    integer distributions. Summing fifteen rounded medians accumulates bias that
    can reach several wins over a long career, and it systematically favours
    drivers with many low-count seasons over drivers with few high-count ones —
    which is precisely the comparison the leaderboard exists to make.
  * Summing per-season intervals is worse still: variances add, half-widths do
    not, and a normal approximation does not hold for a sum of skewed counts.
  * mean(sum) == sum(mean) does hold exactly, by linearity. That gives a free
    correctness invariant rather than a substitute for the interval.

Championships only work this way at all. A career title count is a sum of
Bernoulli draws across seasons; summing per-season P(champion) yields an expected
number of titles but no distribution, and so cannot answer "how often does
Schumacher still end up with seven or more?"
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np

#: Iteration draws compress well — most are small integers and many are all-zero.
_COMPRESSION_LEVEL = 6


@dataclass(frozen=True)
class Summary:
    """Empirical distribution of a total across iterations."""

    mean: float
    median: float
    p2_5: float
    p97_5: float
    std: float

    @classmethod
    def of(cls, draws: np.ndarray) -> Summary:
        p2_5, median, p97_5 = np.percentile(draws, [2.5, 50.0, 97.5])
        return cls(
            mean=float(draws.mean()),
            median=float(median),
            p2_5=float(p2_5),
            p97_5=float(p97_5),
            std=float(draws.std()),
        )


def encode_draws(draws: np.ndarray) -> bytes:
    """Compress a 1-D iteration vector for storage."""
    return zlib.compress(np.ascontiguousarray(draws).tobytes(), _COMPRESSION_LEVEL)


def decode_draws(blob: bytes, dtype: str, n_iterations: int) -> np.ndarray:
    array = np.frombuffer(zlib.decompress(blob), dtype=np.dtype(dtype))
    if len(array) != n_iterations:
        raise ValueError(f"Expected {n_iterations} draws, decoded {len(array)}")
    return array


def sum_across_seasons(season_draws: Iterable[np.ndarray]) -> np.ndarray:
    """Add per-season iteration vectors elementwise into a career vector.

    All vectors must share a length: iteration k of every season is one joint
    sample, so misaligned lengths would silently pair unrelated draws.
    """
    vectors = [np.asarray(v) for v in season_draws]
    if not vectors:
        raise ValueError("No seasons to aggregate")

    lengths = {len(v) for v in vectors}
    if len(lengths) != 1:
        raise ValueError(f"Season draw vectors have differing lengths: {sorted(lengths)}")

    # int64 so a long career cannot overflow the uint8/uint16 storage types.
    total = np.zeros(len(vectors[0]), dtype=np.int64)
    for vector in vectors:
        total += vector.astype(np.int64)
    return total


def aggregate_career(
    season_draws: Mapping[int, np.ndarray],
) -> tuple[Summary, np.ndarray]:
    """Summarise a career from its per-season iteration vectors.

    Returns the summary and the career vector itself, so the caller can reuse it
    for group rollups without decoding twice.
    """
    career = sum_across_seasons(season_draws.values())
    return Summary.of(career), career


def aggregate_group(member_vectors: Iterable[np.ndarray]) -> tuple[Summary, np.ndarray]:
    """Roll several entities' career vectors into one group total.

    Same elementwise sum one level up. Constructor groups use constructor-level
    vectors, which attribute each race to whoever the driver actually drove for,
    so a mid-season switch lands in both teams correctly. Nationality and decade
    groups sum driver vectors.
    """
    total = sum_across_seasons(member_vectors)
    return Summary.of(total), total


def probability_at_least(draws: np.ndarray, thresholds: Iterable[int]) -> dict[int, float]:
    """P(total >= n) for each threshold — how the title distribution is reported."""
    draws = np.asarray(draws)
    return {int(n): float((draws >= n).mean()) for n in thresholds}
