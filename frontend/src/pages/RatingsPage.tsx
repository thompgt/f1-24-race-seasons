import { useState } from 'react'

import NotableWins from '../components/NotableWins'
import RatingsTable from '../components/RatingsTable'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useAsync } from '../hooks/useAsync'
import { getNotableWins, getRatingLeaders } from '../services/api'
import type { RatingSort } from '../types'
import './RatingsPage.css'

const SORTS: { key: RatingSort; label: string; hint: string }[] = [
  {
    key: 'teammate',
    label: 'Team-mate Elo',
    hint: 'Rated only against the driver in the same car, so machinery largely cancels.',
  },
  {
    key: 'peak',
    label: 'Peak Elo',
    hint: 'The whole entry, driver and car. Drifts upward across eras — compare within one, not across.',
  },
  {
    key: 'vs_field',
    label: 'Margin over field',
    hint: 'Peak rating minus the mean rating of the grid they lined up against.',
  },
  {
    key: 'difficulty',
    label: 'Win difficulty',
    hint: 'Average contest per win. Above ×1.00 means the field was expected to beat them.',
  },
]

export default function RatingsPage() {
  const [sort, setSort] = useState<RatingSort>('teammate')
  const [minRaces, setMinRaces] = useState(20)

  const board = useAsync(
    () => getRatingLeaders(sort, { min_races: minRaces, limit: 40 }),
    [sort, minRaces],
  )
  const hardest = useAsync(() => getNotableWins('hardest', 10), [])
  const easiest = useAsync(() => getNotableWins('easiest', 10), [])

  const active = SORTS.find((s) => s.key === sort)!

  return (
    <>
      <header className="ratings-header">
        <h1>Ratings</h1>
        <p className="secondary">
          The 24-race simulation counts a win the same whoever it was taken from.
          These ratings supply the other half: an Elo rating built from every
          pairwise result in F1 history, and the difficulty of each win that
          follows from it.
        </p>
      </header>

      <div className="ratings-controls">
        <div className="control">
          <span className="control-label">Rank by</span>
          <div className="segmented" role="tablist" aria-label="Rank by">
            {SORTS.map((option) => (
              <button
                key={option.key}
                role="tab"
                aria-selected={option.key === sort}
                className={option.key === sort ? 'active' : ''}
                onClick={() => setSort(option.key)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="control">
          <label className="control-label" htmlFor="rating-min-races">
            Min. starts
          </label>
          <input
            id="rating-min-races"
            type="number"
            min={0}
            max={400}
            step={10}
            value={minRaces}
            onChange={(e) => setMinRaces(Number(e.target.value) || 0)}
          />
        </div>
      </div>

      <p className="ratings-hint">{active.hint}</p>

      {board.loading && <LoadingState label="Loading ratings" />}
      {board.error && <ErrorState message={board.error} onRetry={board.reload} />}
      {board.data && board.data.rows.length === 0 && (
        <EmptyState message="No drivers meet that start threshold." />
      )}
      {board.data && board.data.rows.length > 0 && (
        <RatingsTable board={board.data} sort={sort} />
      )}

      <div className="notable-grid">
        {hardest.data && (
          <NotableWins
            tone="hard"
            title="Hardest wins"
            caption="Won from an expected finish far down the order — the field on the day had every reason to beat them."
            wins={hardest.data}
          />
        )}
        {easiest.data && (
          <NotableWins
            tone="easy"
            title="Least contested wins"
            caption="The ratings already had them winning before the lights went out."
            wins={easiest.data}
          />
        )}
      </div>

      <p className="ratings-footnote muted">
        Difficulty is the winner's expected finishing position from the ratings
        carried into that race, scaled so the average win in F1 history is
        ×1.00. It measures how contested a win was, which means a chaotic wet
        afternoon counts as contested — a driver expected to finish eighth who
        won did beat a field that should have beaten them.
      </p>
    </>
  )
}
