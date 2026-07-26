import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, getHealth } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubFetch(response: Partial<Response> & { json: () => Promise<unknown> }) {
  const spy = vi.fn().mockResolvedValue({ ok: true, status: 200, ...response })
  vi.stubGlobal('fetch', spy)
  return spy
}

describe('api client', () => {
  it('returns the parsed body on success', async () => {
    stubFetch({ json: async () => ({ status: 'ok', database_present: true }) })
    await expect(getHealth()).resolves.toEqual({ status: 'ok', database_present: true })
  })

  it('surfaces the server-provided detail on failure', async () => {
    stubFetch({ ok: false, status: 404, json: async () => ({ detail: 'no such season' }) })
    await expect(getHealth()).rejects.toThrow('no such season')
  })

  it('falls back to a status message when the error body is not JSON', async () => {
    stubFetch({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error('not json')
      },
    })
    await expect(getHealth()).rejects.toMatchObject({
      message: 'Request failed with status 500',
      status: 500,
    } satisfies Partial<ApiError>)
  })
})
