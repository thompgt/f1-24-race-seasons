import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import DriverSeasonChart from '../components/DriverSeasonChart'
import SimStatCell from '../components/SimStatCell'
import { ErrorState, LoadingState } from '../components/States'
import { useAsync } from '../hooks/useAsync'
import { getDriver } from '../services/api'
import './DriverPage.css'

type ChartMetric = 'wins' | 'podiums' | 'poles' | 'points'

const CHART_METRICS: { key: ChartMetric; label: string }[] = [
  { key: 'wins', label: 'Wins' },
  { key: 'podiums', label: 'Podiums' },
  { key: 'poles', label: 'Poles' },
  { key: 'points', label: 'Points' },
]

export default function DriverPage() {
  const { driverId } = useParams<{ driverId: string }>()
  const [metric, setMetric] = useState<ChartMetric>('wins')
  const driver = useAsync(() => getDriver(Number(driverId)), [driverId])

  if (driver.error) return <ErrorState message={driver.error} onRetry={driver.reload} />
  if (driver.loading || !driver.data) return <LoadingState label="Loading driver" />

  const { career, seasons } = driver.data
  const titleOdds = Object.entries(career.championships_at_least)
    .map(([n, p]) => ({ n: Number(n), p }))
    .filter((entry) => entry.p >= 0.01)

  return (
    <article className="driver">
      <header>
        <Link to="/historical" className="back">
          ← All-time leaders
        </Link>
        <h1>{driver.data.driver.name}</h1>
        <p className="secondary">
          {driver.data.driver.nationality} · {career.first_year}–{career.last_year} ·{' '}
          {career.seasons} seasons · {career.races} starts
        </p>
      </header>

      <section className="totals">
        {[
          { label: 'Wins', actual: career.actual_wins, stat: career.wins },
          { label: 'Podiums', actual: career.actual_podiums, stat: career.podiums },
          { label: 'Poles', actual: career.actual_poles, stat: career.poles },
          {
            label: 'Championships',
            actual: career.actual_championships,
            stat: career.championships,
          },
        ].map((item) => (
          <div key={item.label} className="total card">
            <span className="total-label">{item.label}</span>
            <span className="total-sim tabular">{item.stat.median.toFixed(0)}</span>
            <span className="total-ci muted tabular">
              {item.stat.p2_5.toFixed(0)}–{item.stat.p97_5.toFixed(0)} over 24 races
            </span>
            <span className="total-actual muted tabular">actually {item.actual.toFixed(0)}</span>
          </div>
        ))}
      </section>

      {titleOdds.length > 0 && (
        <section className="titles card">
          <h2>How many titles?</h2>
          <p className="secondary">
            Career titles are a sum of per-season outcomes, so the simulation gives a
            distribution rather than a single number.
          </p>
          <ul>
            {titleOdds.map((entry) => (
              <li key={entry.n}>
                <span className="titles-n tabular">{entry.n}+</span>
                <span className="titles-track">
                  <span className="titles-fill" style={{ width: `${entry.p * 100}%` }} />
                </span>
                <span className="titles-p tabular">{(entry.p * 100).toFixed(0)}%</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="segmented chart-metrics" role="tablist" aria-label="Chart metric">
        {CHART_METRICS.map((m) => (
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

      <DriverSeasonChart
        seasons={seasons}
        metric={metric}
        label={CHART_METRICS.find((m) => m.key === metric)!.label}
      />

      <div className="scroll-x">
        <table className="driver-seasons">
          <thead>
            <tr>
              <th scope="col">Season</th>
              <th scope="col">Team</th>
              <th scope="col" className="num">
                Races
              </th>
              <th scope="col" className="num">
                Actual
              </th>
              <th scope="col" className="num">
                Simulated
              </th>
              <th scope="col" className="num">
                Title
              </th>
            </tr>
          </thead>
          <tbody>
            {seasons.map((season) => {
              const actual = {
                wins: season.actual_wins,
                podiums: season.actual_podiums,
                poles: season.actual_poles,
                points: season.actual_points,
              }[metric]
              return (
                <tr key={season.year} className={season.is_actual_champion ? 'is-champion' : ''}>
                  <td>
                    <Link to={`/seasons/${season.year}`} className="tabular">
                      {season.year}
                    </Link>
                    {season.is_actual_champion && <span className="badge badge-champion">champion</span>}
                  </td>
                  <td className="secondary">{season.constructor?.name ?? '—'}</td>
                  <td className="num tabular muted">{season.races}</td>
                  <td className="num tabular secondary">{actual.toFixed(0)}</td>
                  <td className="num">
                    <SimStatCell stat={season[metric]} actual={actual} />
                  </td>
                  <td className="num tabular">
                    {season.p_champion > 0.0005 ? (
                      `${(season.p_champion * 100).toFixed(0)}%`
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </article>
  )
}
