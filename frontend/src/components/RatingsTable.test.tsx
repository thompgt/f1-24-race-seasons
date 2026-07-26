import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithRouter } from '../testUtils'
import type { RatingBoard, RatingRow } from '../types'
import RatingsTable from './RatingsTable'

function ratingRow(options: Partial<RatingRow> & { name: string }): RatingRow {
  return {
    rank: 1,
    driver_id: 4,
    nationality: 'Spanish',
    first_year: 2001,
    last_year: 2025,
    races: 439,
    peak_rating: 1861,
    peak_teammate_rating: 1971,
    peak_vs_field: 297,
    final_rating: 1578,
    wins: 32,
    quality_wins: 29.4,
    mean_win_difficulty: 0.92,
    teammate_races: 300,
    teammate_wins: 200,
    ...options,
  }
}

function board(rows: RatingRow[], sort: RatingBoard['sort'] = 'teammate'): RatingBoard {
  return { sort, min_races: 20, total: rows.length, rows }
}

describe('RatingsTable', () => {
  it('shows both ratings, so car and driver are never conflated', () => {
    renderWithRouter(
      <RatingsTable board={board([ratingRow({ name: 'Fernando Alonso' })])} sort="teammate" />,
    )
    const row = screen.getByText('Fernando Alonso').closest('tr')!
    const cells = within(row).getAllByRole('cell')
    expect(cells[3]).toHaveTextContent('1861') // peak, entry
    expect(cells[5]).toHaveTextContent('1971') // team-mate, driver
  })

  it('marks the column being sorted on', () => {
    renderWithRouter(
      <RatingsTable board={board([ratingRow({ name: 'Alain Prost' })], 'difficulty')} sort="difficulty" />,
    )
    expect(screen.getByRole('columnheader', { name: 'Avg difficulty' })).toHaveClass('sorted')
    expect(screen.getByRole('columnheader', { name: 'Peak Elo' })).not.toHaveClass('sorted')
  })

  it('signs the margin over the field', () => {
    renderWithRouter(
      <RatingsTable
        board={board([ratingRow({ name: 'Backmarker', peak_vs_field: -120 })])}
        sort="vs_field"
      />,
    )
    const row = screen.getByText('Backmarker').closest('tr')!
    expect(within(row).getAllByRole('cell')[4]).toHaveTextContent('-120')
  })

  it('tints a contested win record apart from an uncontested one', () => {
    renderWithRouter(
      <RatingsTable
        board={board([
          ratingRow({ name: 'Jim Clark', driver_id: 373, mean_win_difficulty: 1.24 }),
          ratingRow({ name: 'Max Verstappen', driver_id: 830, rank: 2, mean_win_difficulty: 0.53 }),
        ])}
        sort="difficulty"
      />,
    )
    const cell = (name: string) =>
      within(screen.getByText(name).closest('tr')!).getAllByRole('cell')[8]
    expect(cell('Jim Clark')).toHaveClass('hard')
    expect(cell('Max Verstappen')).toHaveClass('easy')
    // The number is always printed, so colour is never the only signal.
    expect(cell('Max Verstappen')).toHaveTextContent('×0.53')
  })

  it('renders a dash for a driver who never won', () => {
    renderWithRouter(
      <RatingsTable
        board={board([ratingRow({ name: 'Andrea de Cesaris', wins: 0, mean_win_difficulty: null })])}
        sort="difficulty"
      />,
    )
    const row = screen.getByText('Andrea de Cesaris').closest('tr')!
    expect(within(row).getAllByRole('cell')[8]).toHaveTextContent('—')
  })

  it('shows the team-mate head-to-head record', () => {
    renderWithRouter(
      <RatingsTable
        board={board([
          ratingRow({ name: 'Fernando Alonso', teammate_races: 300, teammate_wins: 200 }),
        ])}
        sort="teammate"
      />,
    )
    const row = screen.getByText('Fernando Alonso').closest('tr')!
    expect(within(row).getAllByRole('cell')[6]).toHaveTextContent('200–100')
  })
})
