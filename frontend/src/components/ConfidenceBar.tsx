import './ConfidenceBar.css'

interface Props {
  /** 2.5th percentile across iterations. */
  low: number
  median: number
  /** 97.5th percentile across iterations. */
  high: number
  /** The naive 24/R projection, drawn as a reference tick. */
  scaled?: number
  /** Upper bound of the shared scale, so rows are comparable. */
  max: number
  label: string
}

/**
 * A horizontal interval: the 95% range as a bar, the median as a solid tick, and
 * the pro-rata projection as a hollow reference tick.
 *
 * Rows share one scale (`max`), so bar lengths are comparable down a column —
 * per-row autoscaling would make a 2-win driver look like a 20-win one.
 */
export default function ConfidenceBar({ low, median, high, scaled, max, label }: Props) {
  const scale = (value: number) => (max > 0 ? Math.min(100, (value / max) * 100) : 0)

  const left = scale(low)
  const right = scale(high)
  const width = Math.max(right - left, 0.6)

  return (
    <div
      className="cbar"
      role="img"
      aria-label={`${label}: median ${median.toFixed(0)}, 95% interval ${low.toFixed(0)} to ${high.toFixed(0)}`}
    >
      <div className="cbar-track">
        <div className="cbar-range" style={{ left: `${left}%`, width: `${width}%` }} />
        <div className="cbar-median" style={{ left: `${scale(median)}%` }} />
        {scaled !== undefined && (
          <div
            className="cbar-scaled"
            style={{ left: `${scale(scaled)}%` }}
            title={`Pro-rata projection: ${scaled.toFixed(1)}`}
          />
        )}
      </div>
    </div>
  )
}
