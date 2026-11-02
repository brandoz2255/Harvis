import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, gatewayWsUrl } from './api'

afterEach(() => vi.unstubAllGlobals())
describe('Harvis browser facade routing', () => {
  it('routes desktop API and websocket through the Harvis facade', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await api({ path: '/api/profiles' })
    expect(fetchMock.mock.calls[0][0]).toBe('/hermes-api/api/profiles')
    expect(gatewayWsUrl()).toContain('/hermes-api/ws')
  })
})
