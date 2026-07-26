import { useCallback, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import ChampionOddsPanel from '../components/ChampionOddsPanel'
import SeasonSelector from '../components/SeasonSelector'
import StandingsTable from '../components/StandingsTable'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useAsync } from '../hooks/useAsync'
import { getSeason, getSeasons } from '../services/api'
import './SeasonPage.css'

const DEFAULT_YEAR = 1958

export default function SeasonPage() {
  const params = useParams<{ year?: string }>()
  const navigate = useNavigate()

  const seasons = useAsync(getSeasons, [])
  const year = params.year ? Number(params.year) : DEFAULT_YEAR
  const season = useAsync(() => getSeason(year), [year])

  const onSelect = useCallback(
    (next: number) => navigate(`/seasons/${next}`),
    [navigate],
  )

  const changedCount = useMemo(
    () => seasons.data?.filter((s) => s.champion_changes).length ?? 0,
    [seasons.data],
  )

  if (seasons.error) return <ErrorState message={seasons.error} onRetry={seasons.reload} />
  if (seasons.loading || !seasons.data) return <LoadingState label="Loading seasons" />

  return (
    <>
      <SeasonSelector seasons={seasons.data} selected={year} onSelect={onSelect} />

      {season.error && <ErrorState message={season.error} onRetry={season.reload} />}
      {season.loading && <LoadingState label={`Loading ${year}`} />}

      {season.data && !season.loading && (
        <>
          <header className="season-header">
            <div>
              <h1>{season.data.year}</h1>
              <p className="season-sub secondary">
                {season.data.n_races} championship {season.data.n_races === 1 ? 'race' : 'races'}
                {season.data.n_sprints > 0 && `, ${season.data.n_sprints} sprints`} — simulated
                over {season.data.target_races}
                {!season.data.is_complete && (
                  <span className="badge-progress">season in progress</span>
                )}
              </p>
            </div>
            <dl className="season-facts">
              <div>
                <dt>Actual champion</dt>
                <dd>{season.data.actual_champion?.name ?? 'not yet decided'}</dd>
              </div>
              <div>
                <dt>Scale factor</dt>
                <dd className="tabular">
                  ×{(season.data.target_races / season.data.n_races).toFixed(2)}
                </dd>
              </div>
              <div>
                <dt>Seasons changing title</dt>
                <dd className="tabular">{changedCount} of {seasons.data.length}</dd>
              </div>
            </dl>
          </header>

          {season.data.excluded_races.length > 0 && (
            <p className="season-excluded muted">
              Excluded: {season.data.excluded_races.map((r) => r.name).join(', ')} —{' '}
              {season.data.excluded_races[0].reason}
            </p>
          )}

          <ChampionOddsPanel
            rows={season.data.drivers}
            targetRaces={season.data.target_races}
            seasonRaces={season.data.n_races}
          />

          {season.data.drivers.length === 0 ? (
            <EmptyState message="No results recorded for this season." />
          ) : (
            <StandingsTable
              rows={season.data.drivers}
              seasonRaces={season.data.n_races}
              targetRaces={season.data.target_races}
            />
          )}
        </>
      )}
    </>
  )
}
