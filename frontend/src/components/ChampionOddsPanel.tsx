import type { SeasonDriverRow } from '../types'
import './ChampionOddsPanel.css'

interface Props {
  rows: SeasonDriverRow[]
  targetRaces: number
}

const MIN_ODDS = 0.005

/**
 * How often each driver takes the title across iterations.
 *
 * The actual champion is always shown even when the simulation rarely favours
 * them — that gap is the finding, so hiding it would defeat the point.
 */
export default function ChampionOddsPanel({ rows, targetRaces }: Props) {
  const contenders = rows
    .filter((row) => row.p_champion >= MIN_ODDS || row.is_actual_champion)
    .sort((a, b) => b.p_champion - a.p_champion)
    .slice(0, 8)

  if (contenders.length === 0) return null

  const leader = contenders[0]
  const upset = !leader.is_actual_champion && rows.some((r) => r.is_actual_champion)

  return (
    <section className="odds card">
      <header>
        <h2>Title odds over {targetRaces} races</h2>
        {upset && (
          <p className="odds-note">
            The title changes hands: <strong>{leader.driver.name}</strong> takes it in{' '}
            {(leader.p_champion * 100).toFixed(0)}% of simulated seasons.
          </p>
        )}
      </header>
      <ul>
        {contenders.map((row) => (
          <li key={row.driver.driver_id}>
            <span className="odds-name">
              {row.driver.name}
              {row.is_actual_champion && (
                <span className="odds-actual" title="Actual world champion">
                  actual champion
                </span>
              )}
            </span>
            <span className="odds-track">
              <span
                className={`odds-fill${row.is_actual_champion ? ' is-actual' : ''}`}
                style={{ width: `${Math.max(row.p_champion * 100, 0.8)}%` }}
              />
            </span>
            <span className="odds-value tabular">{(row.p_champion * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
