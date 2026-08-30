import { afterEach, describe, expect, it, vi } from 'vitest'

import { publicApi, setCsrfToken } from './api'

afterEach(() => {
  setCsrfToken(null)
  vi.unstubAllGlobals()
})

describe('public authenticated writes', () => {
  it('sends CSRF and reuses one idempotency key after an uncertain network failure', async () => {
    const calls: RequestInit[] = []
    let attempt = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        calls.push(init ?? {})
        attempt += 1
        if (attempt === 1) throw new TypeError('network interrupted')
        return json({ schema_version: '2.1.0', request_id: 'req-write', status: 'ok' })
      }),
    )
    setCsrfToken('c'.repeat(43))

    await expect(publicApi.updateMemoryDefault('off')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
    })
    await expect(publicApi.updateMemoryDefault('off')).resolves.toBeUndefined()

    const firstHeaders = new Headers(calls[0].headers)
    const secondHeaders = new Headers(calls[1].headers)
    expect(firstHeaders.get('X-CSRF-Token')).toBe('c'.repeat(43))
    expect(firstHeaders.get('Idempotency-Key')).toMatch(/^web-account-preferences-/)
    expect(secondHeaders.get('Idempotency-Key')).toBe(firstHeaders.get('Idempotency-Key'))
  })

  it('uses a new key when the request body changes after a failure', async () => {
    const keys: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        keys.push(new Headers(init?.headers).get('Idempotency-Key') ?? '')
        throw new TypeError('network interrupted')
      }),
    )
    setCsrfToken('d'.repeat(43))

    await expect(publicApi.updateMemoryDefault('off')).rejects.toBeTruthy()
    await expect(publicApi.updateMemoryDefault('on')).rejects.toBeTruthy()
    expect(keys[1]).not.toBe(keys[0])
  })
})

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
