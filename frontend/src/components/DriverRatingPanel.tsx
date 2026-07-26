import type { CareerTotals, DriverRating } from '../types'
import './DriverRatingPanel.css'

function difficultyTone(value: number): 'hard' | 'easy' | '' {
  if (value >= 1.1) return 'hard'
  if (value <= 0.9) return 'easy'
  return ''
}

/**
 * The rating half of a driver's page. Deliberately shows the entry rating and
 * the team-mate rating side by side: a large gap between them is the whole
 * story for anyone who spent a career in the wrong car.
 */
export default function DriverRatingPanel({
  rating,
  career,
}: {
  rating: DriverRating
  career: CareerTotals
}) {
  const tone = rating.mean_win_difficulty ? difficultyTone(rating.mean_win_difficulty) : ''
  const losses = rating.teammate_races - rating.teammate_wins

  return (
    <section className="rating-panel card">
      <h2>Rating</h2>

      <div className="rating-figures">
        <div>
          <span className="rating-label">Peak Elo</span>
          <span className="rating-value tabular">{Math.round(rating.peak_rating)}</span>
          <span className="rating-note muted">driver and car together</span>
        </div>
        <div>
          <span className="rating-label">Peak team-mate Elo</span>
          <span className="rating-value tabular">
            {Math.round(rating.peak_teammate_rating)}
          </span>
          <span className="rating-note muted">
            {rating.teammate_rank ? `#${rating.teammate_rank} all-time · ` : ''}
            same car as the comparison
          </span>
        </div>
        <div>
          <span className="rating-label">Team-mate record</span>
          <span className="rating-value tabular">
            {rating.teammate_races > 0 ? `${rating.teammate_wins}–${losses}` : '—'}
          </span>
          <span className="rating-note muted">classified finishes, head to head</span>
        </div>
        <div>
          <span className="rating-label">Average win difficulty</span>
          <span className={`rating-value tabular ${tone}`}>
            {rating.mean_win_difficulty === null
              ? '—'
              : `×${rating.mean_win_difficulty.toFixed(2)}`}
          </span>
          <span className="rating-note muted">
            {rating.mean_win_difficulty === null
              ? 'no wins to weigh'
              : `over ${rating.wins} wins · ×1.00 is average`}
          </span>
        </div>
      </div>

      {rating.wins > 0 && (
        <p className="rating-summary secondary">
          Weighting each win by how contested it was turns {career.actual_wins.toFixed(0)}{' '}
          wins into {rating.quality_wins.toFixed(1)} — and{' '}
          <strong>{career.quality_wins.median.toFixed(0)}</strong> once every season is
          also normalised to 24 races, against{' '}
          {career.wins.median.toFixed(0)} unweighted.
        </p>
      )}
    </section>
  )
}
