import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LegalLink } from './legal-panel'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const DOC = {
  version: '2026-10-28',
  terms: [{ heading: 'Using Harvis', body: 'Free under the MIT license.' }],
  acceptable_use: [{ heading: 'Use it lawfully', body: 'Nothing illegal.' }],
  house_rules: { required: false, version: null, points: [] }
}

const open = () => {
  render(<LegalLink />)
  fireEvent.click(screen.getByRole('button', { name: 'Terms and Acceptable Use' }))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('LegalLink', () => {
  it('does not fetch until it is opened, then shows terms and acceptable use', async () => {
    const fetchMock = vi.fn(async () => json(200, DOC))
    vi.stubGlobal('fetch', fetchMock)
    render(<LegalLink />)
    expect(fetchMock).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Terms and Acceptable Use' }))

    expect(await screen.findByText('Free under the MIT license.')).toBeTruthy()
    expect(screen.getByRole('dialog', { name: 'Terms and Acceptable Use' })).toBeTruthy()
    expect(screen.getByText('Version 2026-10-28')).toBeTruthy()
    expect(screen.getByText('Use it lawfully')).toBeTruthy()
    expect(screen.queryByText('House rules')).toBeNull()
    expect(fetchMock).toHaveBeenCalledWith('/api/legal', expect.anything())
  })

  it('lists the house rules when this Harvis requires them', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(200, { ...DOC, house_rules: { required: true, version: 'v', points: ['Be kind here.'] } }))
    )
    open()

    expect(await screen.findByText('Be kind here.')).toBeTruthy()
    expect(screen.getByText('House rules')).toBeTruthy()
  })

  it('says so plainly on an older server without the endpoint', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(404, { detail: 'Not Found' }))
    )
    open()

    expect(await screen.findByText(/does not publish its terms yet/)).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('offers a retry when the server cannot be reached', async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValue(json(200, DOC))
    vi.stubGlobal('fetch', fetchMock)
    open()

    expect(await screen.findByRole('alert')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Free under the MIT license.')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('closes with the button or Escape and gives focus back', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(200, DOC))
    )
    open()
    await screen.findByText('Free under the MIT license.')

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())

    fireEvent.click(screen.getByRole('button', { name: 'Terms and Acceptable Use' }))
    fireEvent.keyDown(await screen.findByRole('dialog'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})
