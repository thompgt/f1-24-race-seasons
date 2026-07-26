import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import SimStatCell from './SimStatCell'

const stat = { mean: 8.4, median: 8, p2_5: 4, p97_5: 13 }

describe('SimStatCell', () => {
  it('shows the median and the interval together', () => {
    render(<SimStatCell stat={stat} />)
    expect(screen.getByText('8')).toBeInTheDocument()
    expect(screen.getByText('4–13')).toBeInTheDocument()
  })

  it('puts every basis in the tooltip', () => {
    const { container } = render(<SimStatCell stat={stat} scaled={9.6} actual={4} />)
    const title = container.querySelector('.simstat')?.getAttribute('title') ?? ''
    expect(title).toContain('median 8')
    expect(title).toContain('mean 8.4')
    expect(title).toContain('95% interval 4–13')
    expect(title).toContain('pro-rata 9.6')
    expect(title).toContain('actual 4')
  })

  it('respects the requested precision', () => {
    render(<SimStatCell stat={{ mean: 243.2, median: 243.5, p2_5: 180.2, p97_5: 300.9 }} decimals={1} />)
    expect(screen.getByText('243.5')).toBeInTheDocument()
    expect(screen.getByText('180.2–300.9')).toBeInTheDocument()
  })
})
