/**
 * Sole HTTP client for the app. Components and hooks call these functions;
 * nothing else calls `fetch` directly.
 */

import type { Health } from '../types'

const BASE = '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
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
