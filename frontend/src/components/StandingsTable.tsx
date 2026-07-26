import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import type { Metric, SeasonDriverRow } from '../types'
import ConfidenceBar from './ConfidenceBar'
import SimStatCell from './SimStatCell'
import './StandingsTable.css'

interface Props {
  rows: SeasonDriverRow[]
  /** How many races the season actually ran. */
  seasonRaces: number
  /** The length every season is normalised to. */
  targetRaces: number
}

const METRICS: { key: Exclude<Metric, 'championships'>; label: string; decimals: number }[] = [
  { key: 'points', label: 'Points', decimals: 0 },
  { key: 'wins', label: 'Wins', decimals: 0 },
  { key: 'podiums', label: 'Podiums', decimals: 0 },
  { key: 'poles', label: 'Poles', decimals: 0 },
]

export default function StandingsTable({ rows, seasonRaces, targetRaces }: Props) {
  const [metric, setMetric] = useState<Exclude<Metric, 'championships'>>('points')
  const active = METRICS.find((m) => m.key === metric)!

  const sorted = useMemo(
    () => [...rows].sort((a, b) => b[metric].median - a[metric].median || b[metric].mean - a[metric].mean),
    [rows, metric],
  )

  // One shared scale down the column, so bar lengths compare across rows.
  const max = useMemo(
    () => Math.max(...rows.map((r) => r[metric].p97_5), 1),
    [rows, metric],
  )

  return (
    <section className="standings">
      <div className="standings-controls">
        <div className="metric-tabs" role="tablist" aria-label="Metric">
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
        <p className="standings-legend muted">
          <span className="key key-median" /> simulated median
          <span className="key key-range" /> 95% interval
          <span className="key key-scaled" /> pro-rata 24/{' '}R
        </p>
      </div>

      <div className="scroll-x">
        <table className="standings-table">
          <caption className="visually-hidden">
            Season standings over {targetRaces} races, showing the actual result, the
            pro-rata projection and the simulated median with its 95% interval.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="col-rank">
                #
              </th>
              <th scope="col">Driver</th>
              <th scope="col" className="col-team">
                Team
              </th>
              <th scope="col" className="num">
                Actual
              </th>
              <th scope="col" className="num">
                Pro-rata
              </th>
              <th scope="col" className="num">
                Simulated over {targetRaces}
              </th>
              <th scope="col" className="col-bar">
                <span className="visually-hidden">Interval</span>
              </th>
              <th scope="col" className="num">
                Title
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, index) => (
              <tr
                key={row.driver.driver_id}
                className={row.is_actual_champion ? 'is-champion' : undefined}
              >
                <td className="col-rank muted tabular">{index + 1}</td>
                <td>
                  <Link className="driver-name" to={`/drivers/${row.driver.driver_id}`}>
                    {row.driver.name}
                  </Link>
                  {row.is_actual_champion && (
                    <span className="badge badge-champion" title="Actual world champion">
                      champion
                    </span>
                  )}
                  {row.is_part_season && (
                    <span
                      className="badge badge-part"
                      title={`Contested ${row.actual.races} of ${seasonRaces} races; would have started about ${row.entries_mean.toFixed(1)} of ${targetRaces}`}
                    >
                      {row.actual.races}/{seasonRaces} races
                    </span>
                  )}
                </td>
                <td className="col-team secondary">{row.constructor?.name ?? '—'}</td>
                <td className="num tabular secondary">
                  {row.actual[active.key].toFixed(active.decimals)}
                </td>
                <td className="num tabular muted">{row.scaled[active.key].toFixed(1)}</td>
                <td className="num">
                  <SimStatCell
                    stat={row[metric]}
                    scaled={row.scaled[active.key]}
                    actual={row.actual[active.key]}
                    decimals={active.decimals}
                  />
                </td>
                <td className="col-bar">
                  <ConfidenceBar
                    low={row[metric].p2_5}
                    median={row[metric].median}
                    high={row[metric].p97_5}
                    scaled={row.scaled[active.key]}
                    max={max}
                    label={`${row.driver.name} ${active.label}`}
                  />
                </td>
                <td className="num tabular">
                  {row.p_champion > 0.0005 ? (
                    <span className="title-odds">{(row.p_champion * 100).toFixed(1)}%</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
