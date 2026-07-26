import { Link } from 'react-router-dom'

import type { NotableWin } from '../types'
import './NotableWins.css'

export default function NotableWins({
  title,
  caption,
  wins,
  tone,
}: {
  title: string
  caption: string
  wins: NotableWin[]
  tone: 'hard' | 'easy'
}) {
  // Bars are scaled against the widest value in this list, so the two panels
  // are each readable on their own terms rather than one being a stub.
  const widest = Math.max(...wins.map((w) => w.difficulty), 0.001)

  return (
    <section className={`notable notable-${tone}`}>
      <h2>{title}</h2>
      <p className="secondary">{caption}</p>
      <ol className="notable-list">
        {wins.map((win) => (
          <li key={`${win.race_id}-${win.driver_id}`}>
            <span className="notable-value">×{win.difficulty.toFixed(2)}</span>
            <span className="notable-bar" aria-hidden="true">
              <span style={{ width: `${(win.difficulty / widest) * 100}%` }} />
            </span>
            <span className="notable-who">
              <Link to={`/drivers/${win.driver_id}`}>{win.driver_name}</Link>
              <span className="muted"> · {win.year} {win.race_name.replace(' Grand Prix', '')}</span>
            </span>
            <span className="notable-expected muted">
              expected P{win.expected_position.toFixed(1)} of {win.starters}
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}
