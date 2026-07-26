import { useEffect, useRef } from 'react'

import type { SeasonSummary } from '../types'
import './SeasonSelector.css'

interface Props {
  seasons: SeasonSummary[]
  selected: number
  onSelect: (year: number) => void
}

/**
 * The year strip. Seasons whose title changes under normalisation are marked,
 * because those are the ones worth opening — the marker is a dot plus a
 * title-attribute, never colour alone.
 */
export default function SeasonSelector({ seasons, selected, onSelect }: Props) {
  const activeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest', inline: 'center' })
  }, [selected])

  return (
    <nav className="season-selector scroll-x" aria-label="Season">
      <ul>
        {seasons.map((season) => (
          <li key={season.year}>
            <button
              ref={season.year === selected ? activeRef : undefined}
              className={season.year === selected ? 'active' : ''}
              aria-current={season.year === selected ? 'true' : undefined}
              onClick={() => onSelect(season.year)}
              title={
                season.champion_changes
                  ? `${season.year}: title moves to ${season.likeliest_champion?.name} over 24 races`
                  : `${season.year}: ${season.n_races} races`
              }
            >
              {season.year}
              {season.champion_changes && <span className="marker" aria-hidden="true" />}
              {!season.is_complete && <span className="marker marker-partial" aria-hidden="true" />}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
