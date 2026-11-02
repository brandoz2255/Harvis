import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchLegal } from './legal'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const stub = (res: Response | Error) =>
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      if (res instanceof Error) {
        throw res
      }

      return res
    })
  )

afterEach(() => vi.unstubAllGlobals())

describe('fetchLegal', () => {
  it('reads the terms, acceptable use and house rules', async () => {
    stub(
      json(200, {
        version: '2026-10-28',
        terms: [{ heading: 'Using Harvis', body: 'MIT.' }],
        acceptable_use: [{ heading: 'Lawful', body: 'Be lawful.' }],
        house_rules: { required: true, version: '2026-10-27', points: ['Be kind.'] }
      })
    )

    expect(await fetchLegal()).toEqual({
      version: '2026-10-28',
      terms: [{ heading: 'Using Harvis', body: 'MIT.' }],
      acceptableUse: [{ heading: 'Lawful', body: 'Be lawful.' }],
      houseRules: { required: true, version: '2026-10-27', points: ['Be kind.'] }
    })
  })

  it('drops malformed sections and treats rules without points as not required', async () => {
    stub(
      json(200, {
        version: 'v',
        terms: [{ heading: 'ok', body: 'fine' }, { heading: 3 }, null, 'x'],
        acceptable_use: 'nope',
        house_rules: { required: true, version: 4, points: [] }
      })
    )

    expect(await fetchLegal()).toEqual({
      version: 'v',
      terms: [{ heading: 'ok', body: 'fine' }],
      acceptableUse: [],
      houseRules: { required: false, version: null, points: [] }
    })
  })

  it('resolves null on a server without the endpoint', async () => {
    stub(json(404, { detail: 'Not Found' }))
    expect(await fetchLegal()).toBeNull()
    stub(new Response('<!doctype html><title>app</title>', { status: 200 }))
    expect(await fetchLegal()).toBeNull()
    stub(json(200, { something: 'else' }))
    expect(await fetchLegal()).toBeNull()
  })

  it('rejects when the server errors or cannot be reached', async () => {
    stub(json(502, {}))
    await expect(fetchLegal()).rejects.toThrow()
    stub(new TypeError('Failed to fetch'))
    await expect(fetchLegal()).rejects.toThrow('Failed to fetch')
  })
})
