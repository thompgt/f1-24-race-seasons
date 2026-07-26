# F1 24-Race Normalized Seasons

Formula 1 season length has grown from **7 championship rounds in 1950 to 24 in
2024** — 6 to 24 once the Indianapolis 500, which counted for the title but was
not an F1 race, is set aside. Every all-time leaderboard — wins, podiums, poles, championships — is
therefore biased toward modern drivers, who simply had three times the
opportunities.

This project removes that bias. It re-simulates **every season from 1950 to 2026
as if it ran 24 races**, then re-derives both per-season standings and all-time
leaderboards from those simulations.

The result is a leaderboard that answers "who was the best?" rather than "who
was around when there were the most races?"

---

## Seasons

Pick any year and see what it would have looked like over 24 races. Every row
carries all three bases side by side — what actually happened, the naive `24/R`
pro-rata figure, and the simulated median with its 95% interval — so the
normalisation is never a black box.

![The 1958 season normalised to 24 races](docs/screenshots/seasons-1958.png)

1958 is the case the whole project exists for. Stirling Moss won four races to
Mike Hawthorn's one and still lost the title by a point, because only a driver's
best six results counted. Score every race on the modern system and Hawthorn's
consistency wins even harder — he takes the title in **78.3%** of simulated
24-race seasons. Lengthening the season doesn't rescue Moss; it confirms the
result. That is the honest answer, and it is worth more than a flattering one.

Each season also shows its scale factor, any excluded rounds and their reason,
and — for a year still under way — an in-progress marker instead of a champion.

## Historical stats

All-time leaders re-derived from the normalised seasons. Metric, grouping,
ranking basis, era and a minimum-starts filter are all independent controls, and
the headline column is **rank movement against the real record**.

![All-time wins, normalised](docs/screenshots/historical-drivers.png)

Fangio rises from **12th to 3rd** on wins (24 → 83, 95% CI 71–95) and from 10th
to 2nd on poles (29 → 100). Moss climbs 18th → 10th, Ascari 23rd → 12th, Jim
Clark 10th → 8th. Hamilton and Verstappen barely move — they already raced full
modern calendars, which is the point: the correction only moves people it should.

Group by team, driver nationality or team nationality and the same treatment
applies to constructors:

![All-time wins by team](docs/screenshots/historical-constructors.png)

Ferrari's 248 actual wins become 420 normalised. Talbot-Lago, which existed only
in the six- and seven-race era, climbs from #170 to #47.

Decade and era are deliberately *not* offered as groupings — summing every
driver's wins within a decade just returns `24 × the number of seasons`, which
is a tautology, not a finding. The year-range filter answers that question
properly instead.

## Driver pages

Career totals, the per-season trace, and the distribution of championships.

![Juan Fangio's driver page](docs/screenshots/driver-fangio.png)

Because career titles are a **sum of Bernoulli outcomes** across seasons rather
than a single number, the simulation yields a whole distribution — Fangio keeps
five or more titles in 64% of runs, and picks up a sixth in 13%. A summary
statistic could not express that; only the retained per-iteration draws can.

The chart plots seasons the driver actually contested, evenly spaced. Fangio sat
out 1952 with a broken neck, so the gap between 1951 and 1953 is one step wide
like any other.

## Method

Served from `/api/meta`, so the published methodology cannot drift from what the
pipeline does.

![The method page](docs/screenshots/method.png)

---

## How it works

For a season with `R` actual races, draw 24 race weekends with replacement from
that season and total each driver's results — repeated 10,000 times from a fixed
seed.

The implementation is not a loop. Drawing 24 races with replacement from `R` is
**exactly** `Multinomial(24, uniform(R))`, and every metric (points, wins,
podiums, poles, entries) is additive over races. So the entire bootstrap
collapses to a single matrix multiply:

```python
counts = rng.multinomial(24, np.full(R, 1 / R), size=10_000)   # (N, R)
totals = {m: counts @ metric_matrix[m] for m in METRICS}        # (N, D)
```

This is the same distribution, not an approximation. All 77 seasons × 10,000
iterations simulate in about **4 seconds**; the remaining runtime of the batch
job is compression and SQLite inserts.

The whole weekend is the unit drawn, so a sprint travels with the Grand Prix it
belongs to and the era's sprint-to-race ratio survives resampling.

### Points

Modern scoring (25-18-15-12-10-8-6-4-2-1) across all eras, with sprints scored
separately (8-7-6-5-4-3-2-1). Historical "best N results count" rules are **not**
applied — which is why eight titles change hands on the points system alone,
before any normalisation, and nine once the seasons are lengthened.

### Career totals sum draws, never medians

`median(Σ) ≠ Σ median(·)`. Per-season win counts are small, right-skewed
integers whose medians round; summing fifteen of them accumulates several wins of
bias and systematically favours drivers with many thin seasons — precisely the
comparison the leaderboard exists to make. So the per-iteration draws are
persisted (≈25 MB, zlib-compressed uint8/uint16) and career distributions are
built by summing them elementwise before taking percentiles.

`mean(Σ) = Σ mean(·)` holds exactly by linearity, and is kept as a free
correctness invariant in the test suite.

### Known caveats

These ship to the UI via `/api/meta`, so the Method page cannot fall out of step
with the code:

- **Fastest-lap point** — the underlying data only exists from 2004. Awarding it
  only where data exists would give 2004+ drivers ~0.5 pts/race that earlier
  drivers cannot earn, reintroducing the exact bias this project removes. Both
  `points` and `points_no_fl` are stored, and all-time leaderboards default to
  excluding it.
- **Poles** are derived from the starting grid (`grid == 1`), which has 100%
  coverage for every season 1950–2024, unlike qualifying data (1994+). The grid
  is recorded post-penalty, so a handful of modern races attribute pole to P2.
- **Indy 500 rounds 1950–60** counted for the World Championship but ran to
  different regulations and drew almost no F1 regulars; they are excluded (11
  races). The genuine United States Grands Prix held at the same circuit from
  2000 are kept.
- **Shared drives and car swaps** (1950s) have no modern equivalent. Where a
  driver retired one car and took over another, the better of their two results
  is kept — Fangio is credited with the 1951 French GP win he took in Fagioli's
  car. Where two drivers *shared* one car and were classified together, only one
  is credited, so each race still has exactly one winner and at most three
  podium finishers.
- **A season in progress** is ingested as a projection: marked in the Seasons
  tab, given no champion, and left out of all-time leaderboards.

### Data integrity

Anchors verified against the official record, not assumed: Hamilton 105 wins /
202 podiums, M. Schumacher 91/155, Fangio 24/35, Moss 16/24, Ascari 13/17,
Verstappen 63 wins (through 2024).

Points are scored off numeric `position` only. `positionOrder` is a dense rank
that *includes* retirements — scoring on it pays 332 retired, withdrawn or
disqualified entries. `scripts/verify_data.py` asserts this and a dozen other
invariants, and reports soft findings (grid-vs-qualifying pole disagreements,
champion changes per season) without failing the build.

---

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Linux/macOS: .venv/bin/pip
cd frontend && npm install && cd ..
```

## Building the database

Source data is the Ergast CSV dump (1950–2024), topped up from the
[Jolpica](https://api.jolpi.ca/ergast/f1) API for 2025 onward and for all sprint
results. Nothing under `data/` is committed — it is rebuilt by these scripts.

```bash
python scripts/fetch_jolpica.py        # caches 2025-26 + sprints under data/raw/
python scripts/build_db.py             # CSV dump + cached Jolpica -> data/f1.db
python scripts/run_simulations.py --iterations 10000 --seed 20240424
python scripts/verify_data.py          # data-quality report
```

`fetch_jolpica.py` is the only step that needs network access; once cached, the
database rebuilds offline. Pass `--refresh` to re-pull a season still in
progress, and `--skip-jolpica` to `build_db.py` to build from the CSV dump alone.

The full pipeline takes about four minutes and produces a ~80 MB database.
`--jobs N` is bit-identical to `--jobs 1`: each season draws from
`SeedSequence([namespace, master_seed, year])`, so results do not depend on the
order seasons complete in. Re-running mints a new `run_id` and the API always
serves the latest *complete* run, so a rebuild never exposes partial data.

## Running

```bash
uvicorn app.main:app --reload    # API on :8000
cd frontend && npm run dev       # UI on :5173, proxies /api to :8000
```

## Tests

```bash
pytest                           # 112 backend + simulation invariant tests
cd frontend && npx vitest run    # 25 frontend tests
cd frontend && npx tsc --noEmit  # typecheck
```

The simulation tests are the load-bearing ones. They assert that
`mean(simulated) == actual × 24/R` for every driver-season (which validates the
multinomial reformulation, the matrix construction and the pro-rata display in a
single assertion), that career means equal the sum of season means, that a
24-race season reproduces itself exactly, that a synthetic one-race season has
zero variance, and that the same seed yields byte-identical blobs.

Screenshots in this README are regenerated by `scripts/capture_screenshots.py`
against the running dev servers (needs `playwright` and `playwright install
chromium`).

## API

All read-only, all served from precomputed tables — there is no request-time
simulation.

| Endpoint | Returns |
|---|---|
| `GET /api/seasons` | every year with race count and champion |
| `GET /api/seasons/{year}` | driver + constructor standings, three bases each |
| `GET /api/seasons/{year}/champion-odds` | `P(champion)` per driver |
| `GET /api/historical/leaders` | leaderboard; `metric`, `group_by`, `basis`, `min_races`, `year_from/to` |
| `GET /api/drivers/{id}` | per-season breakdown, career totals, `P(titles ≥ n)` |
| `GET /api/drivers/search?q=` | name lookup |
| `GET /api/meta` | run config and the machine-readable caveat list |

## Stack

FastAPI · SQLAlchemy 2 (async) + SQLite · **numpy** (the simulation engine) ·
pydantic 2 · httpx — and React 19 · TypeScript · Vite · React Router 7 · vitest.

No charting library (both charts are hand-rolled SVG), no migrations tool (the
database is rebuilt from scratch by script), no cache layer (everything is
precomputed). `app/sim/` imports nothing from the database layer, so the only
part with real algorithmic content stays unit-testable on its own.
