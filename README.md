# F1 24-Race Normalized Seasons

Formula 1 season length has grown from **7 races in 1950 to 24 in 2024**. Every
all-time leaderboard — wins, podiums, poles, championships — is therefore biased
toward modern drivers, who simply had three times the opportunities.

This project removes that bias. It re-simulates **every season from 1950 to 2025
as if it ran 24 races**, then re-derives both per-season standings and all-time
leaderboards from those simulations.

## What it shows

- **Seasons tab** — pick any year and see what it would have looked like over 24
  races. Each row shows the actual result, the naive 24/X pro-rata figure, and
  the simulated median with a 95% confidence interval, plus each driver's
  probability of taking the title.
- **Historical Stats tab** — all-time leaders for wins, podiums, poles, points
  and championships, re-derived from the simulations. Group by driver,
  constructor, driver nationality, constructor nationality, decade or era. The
  headline column is rank movement against the real leaderboard.

## Method

For a season with `R` actual races, draw 24 race weekends with replacement from
that season and total each driver's results — repeated 10,000 times with a seeded
RNG. Drawing 24 of `R` with replacement is exactly `Multinomial(24, uniform(R))`,
and every metric is additive over races, so the whole bootstrap reduces to one
matrix multiply rather than a loop.

Points use the modern system (25-18-15-12-10-8-6-4-2-1) across all eras, with
sprints scored separately (8-7-6-5-4-3-2-1) but resampled bundled with their
weekend. Historical "best N results count" rules are not applied.

### Known caveats

These are shipped to the UI via `/api/meta` so the methodology panel can't drift
from the code:

- **Fastest-lap point**: the underlying data only exists from 2004. Awarding it
  only where data exists would give 2004+ drivers ~0.5 pts/race that earlier
  drivers cannot earn — reintroducing the exact bias this project removes. Both
  `points` and `points_no_fl` are stored, and all-time leaderboards default to
  excluding it.
- **Poles** are derived from the starting grid (`grid == 1`), which has 100%
  coverage for every season 1950–2024. Since the grid is recorded post-penalty, a
  handful of modern races attribute pole to P2.
- **Indy 500 rounds 1950–60** counted for the World Championship but had no F1
  regulars; they are excluded (11 races).
- **Shared drives and car swaps** (1950s) have no equivalent in the modern points
  system. Where a driver retired one car and took over another, the better of
  their two results is kept — Fangio is credited with the 1951 French GP win he
  took in Fagioli's car. Where two drivers *shared* one car and were classified
  together, only one is credited, so each race still has exactly one winner and
  at most three podium finishers. This affects 3 wins and 18 podiums across 1,125
  races.

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Linux/macOS: .venv/bin/pip
cd frontend && npm install && cd ..
```

## Building the database

Source data is the Ergast CSV dump (1950–2024), topped up from the
[Jolpica](https://api.jolpi.ca/ergast/f1) API for 2025 and for sprint results.
Nothing under `data/` is committed — it is rebuilt by these scripts.

```bash
python scripts/build_db.py --csv-dir "C:/Users/thoma/F1_points_application"
python scripts/fetch_jolpica.py --seasons 2025 --sprints 2021-2025
python scripts/run_simulations.py --iterations 10000 --seed 20240424
python scripts/verify_data.py          # data-quality report
```

## Running

```bash
uvicorn app.main:app --reload    # API on :8000
cd frontend && npm run dev       # UI on :5173, proxies /api to :8000
```

## Tests

```bash
pytest                           # backend + simulation invariants
cd frontend && npx vitest run    # frontend
cd frontend && npx tsc --noEmit  # typecheck
```

## Stack

FastAPI · SQLAlchemy 2 (async) + SQLite · **numpy** (the simulation engine) ·
pydantic 2 · httpx — and React 19 · TypeScript · Vite · React Router 7 · vitest.
No charting library (the two charts are hand-rolled SVG), no migrations tool (the
database is rebuilt from scratch by script), no cache layer (everything is
precomputed).
