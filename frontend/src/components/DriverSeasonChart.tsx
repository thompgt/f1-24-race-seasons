import type { DriverSeason } from '../types'
import './DriverSeasonChart.css'

interface Props {
  seasons: DriverSeason[]
  metric: 'wins' | 'podiums' | 'poles' | 'points'
  label: string
}

const WIDTH = 720
const HEIGHT = 220
const PAD = { top: 12, right: 12, bottom: 26, left: 34 }

/**
 * Per-season simulated total: a band for the 95% interval, a line through the
 * medians, and hollow markers for what actually happened.
 *
 * Hand-rolled SVG rather than a charting library — the whole thing is one path
 * and two polylines, and a chart dependency would be the largest package in the
 * tree.
 */
export default function DriverSeasonChart({ seasons, metric, label }: Props) {
  if (seasons.length < 2) return null

  const inner = {
    w: WIDTH - PAD.left - PAD.right,
    h: HEIGHT - PAD.top - PAD.bottom,
  }
  const maxValue = Math.max(...seasons.map((s) => s[metric].p97_5), 1)

  const x = (i: number) => PAD.left + (seasons.length === 1 ? inner.w / 2 : (i / (seasons.length - 1)) * inner.w)
  const y = (value: number) => PAD.top + inner.h - (value / maxValue) * inner.h

  const band = [
    ...seasons.map((s, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(s[metric].p97_5)}`),
    ...seasons
      .slice()
      .reverse()
      .map((s, i) => `L${x(seasons.length - 1 - i)},${y(s[metric].p2_5)}`),
    'Z',
  ].join(' ')

  const medianLine = seasons.map((s, i) => `${x(i)},${y(s[metric].median)}`).join(' ')
  const actualKey = (
    { wins: 'actual_wins', podiums: 'actual_podiums', poles: 'actual_poles', points: 'actual_points' } as const
  )[metric]
  const actualLine = seasons.map((s, i) => `${x(i)},${y(s[actualKey])}`).join(' ')

  const ticks = [0, maxValue / 2, maxValue]

  return (
    <figure className="dchart">
      <figcaption>
        {label} per season — <span className="dchart-key sim">simulated over 24 races</span> against{' '}
        <span className="dchart-key actual">what happened</span>
      </figcaption>
      <div className="scroll-x">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`${label} per season from ${seasons[0].year} to ${seasons[seasons.length - 1].year}`}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                className="dchart-grid"
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
              />
              <text className="dchart-tick" x={PAD.left - 6} y={y(tick) + 4} textAnchor="end">
                {tick.toFixed(0)}
              </text>
            </g>
          ))}

          <path className="dchart-band" d={band} />
          <polyline className="dchart-median" points={medianLine} />
          <polyline className="dchart-actual" points={actualLine} />

          {seasons.map((season, i) => (
            <g key={season.year}>
              <circle
                className="dchart-dot"
                cx={x(i)}
                cy={y(season[metric].median)}
                r={4}
              >
                <title>
                  {season.year}: simulated {season[metric].median.toFixed(0)} (
                  {season[metric].p2_5.toFixed(0)}–{season[metric].p97_5.toFixed(0)}), actual{' '}
                  {season[actualKey].toFixed(0)} from {season.races} races
                </title>
              </circle>
              {(i === 0 || i === seasons.length - 1 || seasons.length <= 12) && (
                <text className="dchart-tick" x={x(i)} y={HEIGHT - 8} textAnchor="middle">
                  {String(season.year).slice(2)}
                </text>
              )}
            </g>
          ))}
        </svg>
      </div>
    </figure>
  )
}
