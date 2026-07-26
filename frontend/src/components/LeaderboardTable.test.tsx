import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { LeaderBoard, LeaderRow } from '../types'
import LeaderboardTable from './LeaderboardTable'

function leaderRow(
  rank: number,
  label: string,
  actual: number,
  median: number,
  rankActual: number | null,
): LeaderRow {
  return {
    rank,
    key: label,
    label,
    sublabel: '1950–1958',
    actual,
    scaled: median,
    sim: { mean: median, median, p2_5: median - 10, p97_5: median + 10 },
    rank_actual: rankActual,
    rank_delta: rankActual === null ? null : rankActual - rank,
    n_entities: 1,
    seasons_active: 8,
    first_year: 1950,
    last_year: 1958,
  }
}

function board(rows: LeaderRow[]): LeaderBoard {
  return {
    metric: 'wins',
    group_by: 'driver',
    basis: 'sim',
    total: rows.length,
    min_races: 10,
    year_from: null,
    year_to: null,
    run: {
      run_id: 1,
      created_at: '2026-07-26T00:00:00Z',
      n_iterations: 10000,
      target_races: 24,
      master_seed: 20240424,
      seasons_simulated: 77,
    },
    rows,
  }
}

describe('LeaderboardTable', () => {
  it('shows a climb with an up arrow and the previous rank', () => {
    render(
      <LeaderboardTable board={board([leaderRow(3, 'Juan Fangio', 24, 83, 12)])} />,
    )
    const row = screen.getByText('Juan Fangio').closest('tr')!
    expect(within(row).getByText(/▲/)).toHaveTextContent('▲ 9')
    expect(within(row).getByText('was #12')).toBeInTheDocument()
  })

  it('shows a fall with a down arrow', () => {
    render(
      <LeaderboardTable board={board([leaderRow(5, 'Max Verstappen', 71, 77, 3)])} />,
    )
    const row = screen.getByText('Max Verstappen').closest('tr')!
    expect(within(row).getByText(/▼/)).toHaveTextContent('▼ 2')
  })

  it('marks an unmoved entry without an arrow', () => {
    render(<LeaderboardTable board={board([leaderRow(1, 'Lewis Hamilton', 105, 131, 1)])} />)
    const row = screen.getByText('Lewis Hamilton').closest('tr')!
    expect(within(row).queryByText(/▲|▼/)).toBeNull()
    expect(within(row).queryByText(/was #/)).toBeNull()
  })

  it('renders a dash when the metric has no unadjusted baseline', () => {
    render(<LeaderboardTable board={board([leaderRow(1, 'Ferrari', 0, 19, null)])} />)
    const row = screen.getByText('Ferrari').closest('tr')!
    const move = within(row).getAllByRole('cell')[1]
    expect(move).toHaveTextContent('—')
  })

  it('shows all three bases per row', () => {
    render(<LeaderboardTable board={board([leaderRow(3, 'Juan Fangio', 24, 83, 12)])} />)
    const cells = within(screen.getByText('Juan Fangio').closest('tr')!).getAllByRole('cell')
    expect(cells[3]).toHaveTextContent('24')
    expect(cells[4]).toHaveTextContent('83')
    expect(cells[5]).toHaveTextContent('83')
  })
})
