"""Seeded random streams, one per season.

Deriving each season's generator from a shared SeedSequence means a season's
results depend only on the master seed and the season's own ordinal — never on
how many seasons ran before it, or on whether the batch job ran in one process
or several. That is what makes `--jobs 4` produce bit-identical output to
`--jobs 1`.
"""

from __future__ import annotations

import numpy as np

#: Arbitrary but fixed: keeps season streams from colliding with any other use
#: of the same master seed.
_STREAM_NAMESPACE = 0x46312D3234  # "F1-24"


def season_generator(master_seed: int, year: int) -> np.random.Generator:
    """A generator unique to (master_seed, year) and independent of run order."""
    sequence = np.random.SeedSequence([_STREAM_NAMESPACE, master_seed, year])
    return np.random.default_rng(sequence)
