import { ErrorState, LoadingState } from '../components/States'
import { useAsync } from '../hooks/useAsync'
import { getMeta } from '../services/api'
import './MethodPage.css'

export default function MethodPage() {
  const meta = useAsync(getMeta, [])

  if (meta.error) return <ErrorState message={meta.error} onRetry={meta.reload} />
  if (meta.loading || !meta.data) return <LoadingState label="Loading method" />

  const m = meta.data

  return (
    <article className="method">
      <header>
        <h1>Method</h1>
        <p className="secondary">
          Formula 1 grew from {m.shortest_season_races} championship races in{' '}
          {m.shortest_season_year} to {m.longest_season_races} in {m.longest_season_year}.
          Every all-time record therefore favours drivers who simply had more chances.
          This is how that is corrected.
        </p>
      </header>

      <section>
        <h2>How a season is normalised</h2>
        <ol className="steps">
          {m.method.map((step) => (
            <li key={step.title}>
              <h3>{step.title}</h3>
              <p>{step.detail}</p>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2>What the numbers do not account for</h2>
        <p className="secondary section-intro">
          These are served by the API alongside the figures, so this list cannot fall
          out of step with what the pipeline actually does.
        </p>
        <ul className="caveats">
          {m.caveats.map((caveat) => (
            <li key={caveat.key}>
              <h3>{caveat.title}</h3>
              <p>{caveat.detail}</p>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Data</h2>
        <ul className="sources">
          {m.data_sources.map((source) => (
            <li key={source}>{source}</li>
          ))}
        </ul>
        <dl className="run-facts">
          <div>
            <dt>Seasons</dt>
            <dd className="tabular">
              {m.first_year}–{m.last_year}
            </dd>
          </div>
          <div>
            <dt>Iterations per season</dt>
            <dd className="tabular">{m.run.n_iterations.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Normalised to</dt>
            <dd className="tabular">{m.target_races} races</dd>
          </div>
          <div>
            <dt>Seed</dt>
            <dd className="tabular">{m.run.master_seed}</dd>
          </div>
        </dl>
      </section>
    </article>
  )
}
