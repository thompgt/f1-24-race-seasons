import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { renderWithRouter } from '../testUtils'
import type { SeasonDriverRow } from '../types'
import StandingsTable from './StandingsTable'

/**
 * `SeasonDriverRow` has a field literally named `constructor`, which collides
 * with `Object.prototype.constructor` under `Partial<T>` — so overrides are
 * passed as named options rather than a partial row.
 */
interface RowOptions {
  name: string
  races?: number
  points?: number
  wins?: number
  poles?: number
  pChampion?: number
  isChampion?: boolean
  isPartSeason?: boolean
}

function row(options: RowOptions): SeasonDriverRow {
  const {
    name,
    races = 10,
    points = 40,
    wins = 4,
    poles = 3,
    pChampion = 0.186,
    isChampion = false,
    isPartSeason = false,
  } = options
  const factor = 24 / 10

  return {
    driver: { driver_id: name.length, name, code: null, nationality: 'British' },
    constructor: { constructor_id: 1, name: 'Vanwall', nationality: 'British' },
    actual: {
      races,
      points,
      points_no_fl: points,
      wins,
      podiums: 6,
      poles,
      position: 2,
    },
    scaled: {
      points: points * factor,
      wins: wins * factor,
      podiums: 6 * factor,
      poles: poles * factor,
    },
    points: {
      mean: points * factor,
      median: Math.round(points * factor),
      p2_5: points * factor - 20,
      p97_5: points * factor + 20,
    },
    wins: {
      mean: wins * factor,
      median: Math.round(wins * factor),
      p2_5: Math.max(0, wins * factor - 5),
      p97_5: wins * factor + 5,
    },
    podiums: { mean: 14.4, median: 14, p2_5: 10, p97_5: 19 },
    poles: { mean: poles * factor, median: Math.round(poles * factor), p2_5: 3, p97_5: 12 },
    entries_mean: races * factor,
    entries_p2_5: races * factor,
    entries_p97_5: races * factor,
    p_champion: pChampion,
    p_champion_continued: pChampion,
    form_strength: 1,
    p_top3: 0.9,
    is_actual_champion: isChampion,
    is_part_season: isPartSeason,
  }
}

// Modelled on 1958: Hawthorn took the title with one win to Moss's four.
const rows = [
  row({ name: 'Stirling Moss', points: 40, wins: 4 }),
  row({ name: 'Mike Hawthorn', points: 42, wins: 1, pChampion: 0.783, isChampion: true }),
  row({ name: 'Harry Schell', races: 3, points: 2, wins: 0, poles: 0, pChampion: 0, isPartSeason: true }),
]

function renderTable() {
  return renderWithRouter(<StandingsTable rows={rows} seasonRaces={10} targetRaces={24} />)
}

describe('StandingsTable', () => {
  it('shows all three bases in every row', () => {
    renderTable()
    const moss = screen.getByText('Stirling Moss').closest('tr')!
    const cells = within(moss).getAllByRole('cell')

    // actual points, pro-rata points, then the simulated median.
    expect(cells[3]).toHaveTextContent('40')
    expect(cells[4]).toHaveTextContent('96.0')
    expect(cells[5]).toHaveTextContent('96')
  })

  it('sorts by the selected metric, not by a fixed order', async () => {
    renderTable()
    const names = () =>
      screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[1].textContent)

    // Points first: Hawthorn leads.
    expect(names()[0]).toContain('Mike Hawthorn')

    await userEvent.click(screen.getByRole('tab', { name: 'Wins' }))
    // On wins, Moss leads — the whole point of the 1958 comparison.
    expect(names()[0]).toContain('Stirling Moss')
  })

  it('marks the actual champion', () => {
    renderTable()
    const hawthorn = screen.getByText('Mike Hawthorn').closest('tr')!
    expect(within(hawthorn).getByText('champion')).toBeInTheDocument()
  })

  it('flags a part-season entrant with their real race count', () => {
    renderTable()
    const schell = screen.getByText('Harry Schell').closest('tr')!
    expect(within(schell).getByText('3/10 races')).toBeInTheDocument()
  })

  it('shows a dash rather than 0.0% for a driver with no title chance', () => {
    renderTable()
    const schell = screen.getByText('Harry Schell').closest('tr')!
    const cells = within(schell).getAllByRole('cell')
    expect(cells[cells.length - 1]).toHaveTextContent('—')
  })
})
