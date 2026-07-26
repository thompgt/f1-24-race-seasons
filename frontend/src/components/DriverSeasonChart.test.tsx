import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { DriverSeason } from '../types'
import DriverSeasonChart from './DriverSeasonChart'

function season(year: number, actualWins: number, median: number): DriverSeason {
  return {
    year,
    constructor: { constructor_id: 1, name: 'Maserati', nationality: 'Italian' },
    races: 8,
    actual_wins: actualWins,
    actual_podiums: actualWins + 1,
    actual_poles: actualWins,
    actual_points: actualWins * 25,
    scaled_wins: actualWins * 3,
    wins: { mean: median, median, p2_5: median - 4, p97_5: median + 4 },
    podiums: { mean: median, median, p2_5: median - 4, p97_5: median + 4 },
    poles: { mean: median, median, p2_5: median - 4, p97_5: median + 4 },
    points: { mean: median * 25, median: median * 25, p2_5: 0, p97_5: median * 30 },
    p_champion: 0.5,
    is_actual_champion: year === 1954,
  }
}

const seasons = [season(1950, 3, 12), season(1951, 3, 10), season(1954, 6, 18)]

describe('DriverSeasonChart', () => {
  it('draws a band, a median line and an actual line', () => {
    const { container } = render(
      <DriverSeasonChart seasons={seasons} metric="wins" label="Wins" />,
    )
    expect(container.querySelector('.dchart-band')).not.toBeNull()
    expect(container.querySelector('.dchart-median')).not.toBeNull()
    expect(container.querySelector('.dchart-actual')).not.toBeNull()
    expect(container.querySelectorAll('.dchart-dot')).toHaveLength(3)
  })

  it('labels itself with the span it covers', () => {
    render(<DriverSeasonChart seasons={seasons} metric="wins" label="Wins" />)
    expect(
      screen.getByRole('img', { name: 'Wins per season from 1950 to 1954' }),
    ).toBeInTheDocument()
  })

  it('gives every point a tooltip carrying both bases', () => {
    const { container } = render(
      <DriverSeasonChart seasons={seasons} metric="wins" label="Wins" />,
    )
    const titles = Array.from(container.querySelectorAll('.dchart-dot title')).map(
      (t) => t.textContent,
    )
    expect(titles[0]).toContain('1950')
    expect(titles[0]).toContain('simulated 12')
    expect(titles[0]).toContain('actual 3')
  })

  it('renders nothing for a single-season career, where a line is meaningless', () => {
    const { container } = render(
      <DriverSeasonChart seasons={[season(1950, 3, 12)]} metric="wins" label="Wins" />,
    )
    expect(container.querySelector('svg')).toBeNull()
  })
})
