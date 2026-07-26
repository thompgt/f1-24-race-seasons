import ConfidenceBar from './ConfidenceBar'
import SimStatCell from './SimStatCell'
import type { Basis, LeaderBoard } from '../types'
import './LeaderboardTable.css'

interface Props {
  board: LeaderBoard
}

const BASIS_LABEL: Record<Basis, string> = {
  sim: 'Simulated over 24 races',
  scaled: 'Pro-rata projection',
  actual: 'As it happened',
}

/** An arrow plus a number — direction is never carried by colour alone. */
function RankDelta({ delta }: { delta: number | null }) {
  if (delta === null) return <span className="muted">—</span>
  if (delta === 0) return <span className="muted">·</span>

  const up = delta > 0
  return (
    <span className={up ? 'delta delta-up' : 'delta delta-down'}>
      {up ? '▲' : '▼'} {Math.abs(delta)}
    </span>
  )
}

export default function LeaderboardTable({ board }: Props) {
  const decimals = board.metric === 'points' ? 0 : 0
  const max = Math.max(...board.rows.map((r) => r.sim.p97_5), 1)
  const isGroup = board.group_by !== 'driver'

  return (
    <div className="scroll-x">
      <table className="leaderboard">
        <caption className="visually-hidden">
          All-time {board.metric} ranked by {BASIS_LABEL[board.basis].toLowerCase()}, with
          movement against the unadjusted record.
        </caption>
        <thead>
          <tr>
            <th scope="col" className="col-rank">
              #
            </th>
            <th scope="col" className="col-move">
              Move
            </th>
            <th scope="col">{isGroup ? 'Group' : 'Driver'}</th>
            <th scope="col" className="num">
              Actual
            </th>
            <th scope="col" className="num">
              Pro-rata
            </th>
            <th scope="col" className="num">
              Simulated
            </th>
            <th scope="col" className="col-bar">
              <span className="visually-hidden">Interval</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {board.rows.map((row) => (
            <tr key={row.key}>
              <td className="col-rank muted tabular">{row.rank}</td>
              <td className="col-move tabular">
                <RankDelta delta={row.rank_delta ?? null} />
              </td>
              <td>
                <span className="leader-name">{row.label}</span>
                {row.sublabel && <span className="leader-sub muted">{row.sublabel}</span>}
                {row.rank_actual !== null && row.rank_delta !== null && row.rank_delta !== 0 && (
                  <span className="leader-was muted">
                    was #{row.rank_actual}
                  </span>
                )}
              </td>
              <td className="num tabular secondary">{row.actual.toFixed(decimals)}</td>
              <td className="num tabular muted">{row.scaled.toFixed(decimals)}</td>
              <td className="num">
                <SimStatCell stat={row.sim} scaled={row.scaled} actual={row.actual} />
              </td>
              <td className="col-bar">
                <ConfidenceBar
                  low={row.sim.p2_5}
                  median={row.sim.median}
                  high={row.sim.p97_5}
                  scaled={row.scaled}
                  max={max}
                  label={`${row.label} ${board.metric}`}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
