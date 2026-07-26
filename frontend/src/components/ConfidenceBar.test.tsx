import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import ConfidenceBar from './ConfidenceBar'

describe('ConfidenceBar', () => {
  it('positions the range and median against the shared scale', () => {
    const { container } = render(
      <ConfidenceBar low={5} median={10} high={15} max={20} label="Wins" />,
    )
    const range = container.querySelector('.cbar-range') as HTMLElement
    const median = container.querySelector('.cbar-median') as HTMLElement

    expect(range.style.left).toBe('25%')
    expect(range.style.width).toBe('50%')
    expect(median.style.left).toBe('50%')
  })

  it('describes itself for screen readers', () => {
    render(<ConfidenceBar low={4} median={8} high={13} max={24} label="Fangio Wins" />)
    expect(
      screen.getByRole('img', { name: 'Fangio Wins: median 8, 95% interval 4 to 13' }),
    ).toBeInTheDocument()
  })

  it('draws the pro-rata reference only when supplied', () => {
    const { container, rerender } = render(
      <ConfidenceBar low={1} median={2} high={3} max={10} label="Wins" />,
    )
    expect(container.querySelector('.cbar-scaled')).toBeNull()

    rerender(<ConfidenceBar low={1} median={2} high={3} scaled={2.4} max={10} label="Wins" />)
    expect(container.querySelector('.cbar-scaled')).not.toBeNull()
  })

  it('stays visible when the interval has zero width', () => {
    const { container } = render(
      <ConfidenceBar low={24} median={24} high={24} max={24} label="Wins" />,
    )
    const range = container.querySelector('.cbar-range') as HTMLElement
    expect(parseFloat(range.style.width)).toBeGreaterThan(0)
  })

  it('does not divide by zero on an empty scale', () => {
    const { container } = render(
      <ConfidenceBar low={0} median={0} high={0} max={0} label="Wins" />,
    )
    const median = container.querySelector('.cbar-median') as HTMLElement
    expect(median.style.left).toBe('0%')
  })
})
