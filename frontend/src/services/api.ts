/**
 * Sole HTTP client for the app. Components and hooks call these functions;
 * nothing else calls `fetch` directly.
 */

import type {
  ChampionOdds,
  Health,
  LeaderBoard,
  LeaderQuery,
  SeasonDetail,
  SeasonSummary,
} from '../types'

const BASE = '/api'

export class ApiError extends Error {
  // Declared explicitly rather than as a constructor parameter property, which
  // the project's erasableSyntaxOnly setting disallows.
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Request failed with status ${res.status}`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // Non-JSON error body; keep the status-based message.
    }
    throw new ApiError(detail, res.status)
  }
  return (await res.json()) as T
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

async function get<T>(
  path: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<T> {
  return handleResponse<T>(await fetch(`${BASE}${path}${qs(params)}`))
}

export function getHealth(): Promise<Health> {
  return get<Health>('/health')
}

export function getSeasons(): Promise<SeasonSummary[]> {
  return get<SeasonSummary[]>('/seasons')
}

export function getSeason(year: number): Promise<SeasonDetail> {
  return get<SeasonDetail>(`/seasons/${year}`)
}

export function getChampionOdds(year: number): Promise<ChampionOdds[]> {
  return get<ChampionOdds[]>(`/seasons/${year}/champion-odds`)
}

export function getLeaders(query: LeaderQuery): Promise<LeaderBoard> {
  return get<LeaderBoard>('/historical/leaders', { ...query })
}
