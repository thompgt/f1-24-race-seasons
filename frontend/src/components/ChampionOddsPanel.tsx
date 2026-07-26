import type { SeasonDriverRow } from '../types'
import './ChampionOddsPanel.css'

interface Props {
  rows: SeasonDriverRow[]
  targetRaces: number
  seasonRaces: number
}

const MIN_ODDS = 0.005

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

/**
 * How often each driver takes the title, under both models.
 *
 * They answer different questions and often disagree, which is the reason both
 * are shown rather than one being picked. Resampling the races that happened
 * scales the championship margin along with everything else, so it can rarely
 * take a title off the leader; continuing the season from end-of-year form can,
 * because it asks who was quickest at the finish rather than who averaged best.
 *
 * The actual champion is always listed even when neither model favours them —
 * that gap is the finding, so hiding it would defeat the point.
 */
export default function ChampionOddsPanel({ rows, targetRaces, seasonRaces }: Props) {
  const extraRaces = Math.max(targetRaces - seasonRaces, 0)
  const hasContinuation = extraRaces > 0 && rows.some((r) => r.p_champion_continued !== null)

  const contenders = rows
    .filter(
      (row) =>
        row.p_champion >= MIN_ODDS ||
        (row.p_champion_continued ?? 0) >= MIN_ODDS ||
        row.is_actual_champion,
    )
    .sort(
      (a, b) =>
        Math.max(b.p_champion, b.p_champion_continued ?? 0) -
        Math.max(a.p_champion, a.p_champion_continued ?? 0),
    )
    .slice(0, 8)

  if (contenders.length === 0) return null

  const byResample = [...contenders].sort((a, b) => b.p_champion - a.p_champion)[0]
  const byContinue = hasContinuation
    ? [...contenders].sort(
        (a, b) => (b.p_champion_continued ?? 0) - (a.p_champion_continued ?? 0),
      )[0]
    : null
  const modelsDisagree =
    byContinue !== null && byContinue.driver.driver_id !== byResample.driver.driver_id

  return (
    <section className="odds card">
      <header>
        <h2>Title odds over {targetRaces} races</h2>
        {modelsDisagree ? (
          <p className="odds-note">
            The two models disagree. Resampling the season favours{' '}
            <strong>{byResample.driver.name}</strong> ({pct(byResample.p_champion)});
            racing out the remaining {extraRaces} from end-of-season form favours{' '}
            <strong>{byContinue.driver.name}</strong> (
            {pct(byContinue.p_champion_continued ?? 0)}).
          </p>
        ) : (
          !byResample.is_actual_champion &&
          rows.some((r) => r.is_actual_champion) && (
            <p className="odds-note">
              The title changes hands: <strong>{byResample.driver.name}</strong> takes
              it in {pct(byResample.p_champion)} of simulated seasons.
            </p>
          )
        )}
      </header>

      {hasContinuation && (
        <p className="odds-legend">
          <span className="key key-resample" aria-hidden="true" /> resample the season
          <span className="key key-continue" aria-hidden="true" /> continue it (+
          {extraRaces} races)
        </p>
      )}

      <ul className={hasContinuation ? 'odds-paired' : ''}>
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
            <span className="odds-bars">
              <span className="odds-track">
                <span
                  className="odds-fill is-resample"
                  style={{ width: `${Math.max(row.p_champion * 100, 0.8)}%` }}
                />
              </span>
              {hasContinuation && (
                <span className="odds-track">
                  <span
                    className="odds-fill is-continue"
                    style={{
                      width: `${Math.max((row.p_champion_continued ?? 0) * 100, 0.8)}%`,
                    }}
                  />
                </span>
              )}
            </span>
            <span className="odds-values tabular">
              <span>{pct(row.p_champion)}</span>
              {hasContinuation && (
                <span className="odds-continue-value">
                  {pct(row.p_champion_continued ?? 0)}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>

      {!hasContinuation && seasonRaces >= targetRaces && (
        <p className="odds-footnote muted">
          This season already ran the full {targetRaces} races, so there is no
          remainder to race out — only the resampling model has anything to say.
        </p>
      )}
    </section>
  )
}
