# f1-24-race-seasons

Normalizes every F1 season (1950–2025) to a standard 24 races via Monte Carlo
bootstrap, so all-time leaderboards aren't biased toward drivers who simply had
more races available.

## Architecture

- `app/sim/` — **pure numpy, no DB imports.** The simulation engine. Keep it that
  way; it's the only part with real algorithmic content and it must stay
  unit-testable without a database.
- `app/ingestion/` — CSV loader (Ergast dump) + Jolpica API client.
- `app/api/endpoints.py` — single router, all read-only, served entirely from
  precomputed tables. No request-time simulation, ever.
- `frontend/src/services/api.ts` — sole HTTP client. Components never call
  `fetch` directly.

## Non-negotiable domain rules

1. **Score off numeric `position` only.** `positionOrder` is a dense rank that
   includes retirements (`positionText` in `R/W/D/N/F/E`). Awarding points on
   `positionOrder` is a real bug in the reference implementation at
   `~/F1_points_application/adjusted_points.py` — 338 rows score wrongly there.
2. **Fastest-lap data only exists from 2004.** Awarding the FL point where data
   exists gives 2004+ drivers ~0.5 pts/race that earlier drivers cannot get —
   re-injecting the exact bias this project removes. Store `points` *and*
   `points_no_fl`; all-time leaderboards default to `points_no_fl`.
3. **Poles come from `results.grid == 1`**, which has 100% coverage for every
   season 1950–2024. `grid` is post-penalty, so a few modern races attribute
   pole to P2 — disclosed via `/api/meta.caveats`.
4. **Career totals sum per-iteration draws, never per-season medians.**
   `median(Σ) ≠ Σ median(·)`. See `app/sim/career.py`.
5. **Indy 500 rounds 1950–60 are excluded** (`circuits.circuit_ref == 'indianapolis'`).
6. Ignore `~/F1_points_application/database.db` — its `drivers` table is polluted
   (1,722 rows vs 862 in the CSV). Ingest from the CSVs.

## Commands

```bash
python scripts/build_db.py --csv-dir "C:/Users/thoma/F1_points_application"
python scripts/fetch_jolpica.py --seasons 2025 --sprints 2021-2025
python scripts/run_simulations.py --iterations 10000 --seed 20240424
python scripts/verify_data.py
pytest
uvicorn app.main:app --reload        # :8000
cd frontend && npm run dev           # :5173
```

## Conventions

- Commit after each small logical unit and push immediately — not batched.
- pytest with `asyncio_mode = auto`; tests colocated by module.
- Frontend: React 19 + TS + Vite, `pages/` vs `components/` split, vitest +
  Testing Library, `Component.test.tsx` colocated.
