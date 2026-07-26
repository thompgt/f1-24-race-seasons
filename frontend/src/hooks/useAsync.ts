import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../services/api'

interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

/**
 * Runs a fetch on mount and whenever `deps` change, discarding results from
 * superseded requests so a slow response cannot overwrite a newer one.
 */
export function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let current = true
    setLoading(true)
    setError(null)

    fetcher()
      .then((result) => {
        if (current) setData(result)
      })
      .catch((err: unknown) => {
        if (!current) return
        setError(err instanceof ApiError ? err.message : 'Something went wrong.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })

    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { data, loading, error, reload }
}
