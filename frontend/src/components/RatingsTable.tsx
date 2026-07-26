import { Link } from 'react-router-dom'

import type { RatingBoard, RatingSort } from '../types'
import './RatingsTable.css'

/** Difficulty reads as a multiple of an average win, so it always shows a sign. */
function difficultyClass(value: number | null): string {
  if (value === null) return ''
  if (value >= 1.1) return 'hard'
  if (value <= 0.9) return 'easy'
  return ''
}

export default function RatingsTable({
  board,
  sort,
}: {
  board: RatingBoard
  sort: RatingSort
}) {
  return (
    <div className="table-scroll">
      <table className="ratings-table">
        <thead>
          <tr>
            <th className="col-rank">#</th>
            <th>Driver</th>
            <th className="num">Races</th>
            <th className={`num${sort === 'peak' ? ' sorted' : ''}`}>Peak Elo</th>
            <th className={`num${sort === 'vs_field' ? ' sorted' : ''}`}>vs field</th>
            <th className={`num${sort === 'teammate' ? ' sorted' : ''}`}>Team-mate Elo</th>
            <th className="num">H2H</th>
            <th className="num">Wins</th>
            <th className={`num${sort === 'difficulty' ? ' sorted' : ''}`}>Avg difficulty</th>
          </tr>
        </thead>
        <tbody>
          {board.rows.map((row) => (
            <tr key={row.driver_id}>
              <td className="col-rank muted">{row.rank}</td>
              <td>
                <Link className="driver-name" to={`/drivers/${row.driver_id}`}>
                  {row.name}
                </Link>
                <span className="rating-sub muted">
                  {row.first_year}–{row.last_year}
                </span>
              </td>
              <td className="num muted">{row.races}</td>
              <td className="num">{Math.round(row.peak_rating)}</td>
              <td className="num muted">
                {row.peak_vs_field >= 0 ? '+' : ''}
                {Math.round(row.peak_vs_field)}
              </td>
              <td className="num">{Math.round(row.peak_teammate_rating)}</td>
              <td className="num muted">
                {row.teammate_races > 0
                  ? `${row.teammate_wins}–${row.teammate_races - row.teammate_wins}`
                  : '—'}
              </td>
              <td className="num">{row.wins}</td>
              <td className={`num difficulty ${difficultyClass(row.mean_win_difficulty)}`}>
                {row.mean_win_difficulty === null
                  ? '—'
                  : `×${row.mean_win_difficulty.toFixed(2)}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
