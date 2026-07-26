import { useCallback, useMemo, useState } from 'react'

import LeaderboardTable from '../components/LeaderboardTable'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useAsync } from '../hooks/useAsync'
import { getLeaders } from '../services/api'
import type { Basis, GroupBy, Metric } from '../types'
import './HistoricalPage.css'

const METRICS: { key: Metric; label: string }[] = [
  { key: 'wins', label: 'Wins' },
  { key: 'podiums', label: 'Podiums' },
  { key: 'poles', label: 'Poles' },
  { key: 'points', label: 'Points' },
  { key: 'championships', label: 'Championships' },
]

const GROUPS: { key: GroupBy; label: string }[] = [
  { key: 'driver', label: 'Driver' },
  { key: 'constructor', label: 'Team' },
  { key: 'driver_nationality', label: 'Driver nationality' },
  { key: 'constructor_nationality', label: 'Team nationality' },
]

const BASES: { key: Basis; label: string; hint: string }[] = [
  { key: 'sim', label: 'Simulated', hint: 'Ranked by the 24-race simulation' },
  { key: 'scaled', label: 'Pro-rata', hint: 'Ranked by the naive 24/R projection' },
  { key: 'actual', label: 'Actual', hint: 'The unadjusted record' },
]

const ERAS: { label: string; from?: number; to?: number }[] = [
  { label: 'All time' },
  { label: '1950s–60s', from: 1950, to: 1969 },
  { label: '1970s–80s', from: 1970, to: 1989 },
  { label: '1990s–2000s', from: 1990, to: 2009 },
  { label: '2010 on', from: 2010, to: 2100 },
]

export default function HistoricalPage() {
  const [metric, setMetric] = useState<Metric>('wins')
  const [groupBy, setGroupBy] = useState<GroupBy>('driver')
  const [basis, setBasis] = useState<Basis>('sim')
  const [minRaces, setMinRaces] = useState(10)
  const [era, setEra] = useState(0)

  const isDriver = groupBy === 'driver'
  const range = ERAS[era]

  const board = useAsync(
    () =>
      getLeaders({
        metric,
        group_by: groupBy,
        basis,
        // The year range and race minimum are driver-level controls; group
        // totals cover full history, and the API rejects the combination.
        ...(isDriver
          ? { min_races: minRaces, year_from: range.from, year_to: range.to }
          : {}),
        limit: 50,
      }),
    [metric, groupBy, basis, minRaces, isDriver ? era : -1],
  )

  const onGroupChange = useCallback((next: GroupBy) => {
    setGroupBy(next)
    if (next !== 'driver') setEra(0)
  }, [])

  const movers = useMemo(() => {
    if (!board.data) return null
    const climbed = board.data.rows
      .filter((r) => (r.rank_delta ?? 0) > 0)
      .sort((a, b) => (b.rank_delta ?? 0) - (a.rank_delta ?? 0))[0]
    return climbed ?? null
  }, [board.data])

  return (
    <>
      <header className="hist-header">
        <h1>Historical stats</h1>
        <p className="secondary">
          All-time leaders re-derived from seasons normalised to 24 races, so an era
          that raced seven times a year is compared with one that races twenty-four.
        </p>
      </header>

      <div className="hist-controls">
        <div className="control">
          <span className="control-label">Metric</span>
          <div className="segmented" role="tablist" aria-label="Metric">
            {METRICS.map((m) => (
              <button
                key={m.key}
                role="tab"
                aria-selected={m.key === metric}
                className={m.key === metric ? 'active' : ''}
                onClick={() => setMetric(m.key)}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <div className="control">
          <label className="control-label" htmlFor="group-by">
            Group by
          </label>
          <select
            id="group-by"
            value={groupBy}
            onChange={(e) => onGroupChange(e.target.value as GroupBy)}
          >
            {GROUPS.map((g) => (
              <option key={g.key} value={g.key}>
                {g.label}
              </option>
            ))}
          </select>
        </div>

        <div className="control">
          <span className="control-label">Ranked by</span>
          <div className="segmented" role="tablist" aria-label="Basis">
            {BASES.map((b) => (
              <button
                key={b.key}
                role="tab"
                aria-selected={b.key === basis}
                title={b.hint}
                className={b.key === basis ? 'active' : ''}
                onClick={() => setBasis(b.key)}
              >
                {b.label}
              </button>
            ))}
          </div>
        </div>

        {isDriver && (
          <>
            <div className="control">
              <label className="control-label" htmlFor="era">
                Era
              </label>
              <select id="era" value={era} onChange={(e) => setEra(Number(e.target.value))}>
                {ERAS.map((e, i) => (
                  <option key={e.label} value={i}>
                    {e.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="control">
              <label className="control-label" htmlFor="min-races">
                Min. starts
              </label>
              <input
                id="min-races"
                type="number"
                min={0}
                max={400}
                step={5}
                value={minRaces}
                onChange={(e) => setMinRaces(Math.max(0, Number(e.target.value)))}
              />
            </div>
          </>
        )}
      </div>

      {board.error && <ErrorState message={board.error} onRetry={board.reload} />}
      {board.loading && <LoadingState label="Ranking" />}

      {board.data && !board.loading && (
        <>
          {movers && (
            <p className="hist-callout">
              Biggest climb: <strong>{movers.label}</strong> rises from #{movers.rank_actual} to
              #{movers.rank} on {metric} once every season is normalised to 24 races.
            </p>
          )}
          {board.data.rows.length === 0 ? (
            <EmptyState message="Nothing matches these filters — try lowering the minimum starts." />
          ) : (
            <LeaderboardTable board={board.data} />
          )}
          <p className="hist-footnote muted">
            {board.data.total} ranked
            {isDriver && ` · at least ${board.data.min_races} career starts`} ·{' '}
            {board.data.run.n_iterations.toLocaleString()} iterations per season
            {metric === 'points' && ' · points exclude the fastest-lap bonus, which only exists from 2004'}
          </p>
        </>
      )}
    </>
  )
}
