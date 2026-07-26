import type { SimStat } from '../types'
import './SimStatCell.css'

interface Props {
  stat: SimStat
  /** Shown as a hollow tick alongside, and in the tooltip. */
  scaled?: number
  actual?: number
  /** Points need a decimal; win and pole counts do not. */
  decimals?: number
}

/**
 * The simulated median with its 95% interval — the app's basic unit of figure.
 *
 * The interval is always visible rather than hidden behind a hover, because for
 * a short season it is the whole story: Fangio's 1952 win count is not "8", it
 * is "8, and anywhere from 4 to 12 is consistent with what he actually did".
 */
export default function SimStatCell({ stat, scaled, actual, decimals = 0 }: Props) {
  const fmt = (value: number) => value.toFixed(decimals)
  const tooltip = [
    `Simulated over 24 races`,
    `median ${fmt(stat.median)}`,
    `mean ${stat.mean.toFixed(1)}`,
    `95% interval ${fmt(stat.p2_5)}–${fmt(stat.p97_5)}`,
    scaled !== undefined ? `pro-rata ${scaled.toFixed(1)}` : null,
    actual !== undefined ? `actual ${fmt(actual)}` : null,
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <span className="simstat tabular" title={tooltip}>
      <span className="simstat-median">{fmt(stat.median)}</span>
      <span className="simstat-ci">
        {fmt(stat.p2_5)}–{fmt(stat.p97_5)}
      </span>
    </span>
  )
}
