import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SignInScreen } from './sign-in-screen'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function serve(terms: { required: boolean; points?: string[] }, legal: Response = json(404, {})) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/config') {
        return json(200, {
          onboarding: false,
          features: { enable_signup: true, terms: { version: 'v', points: [], ...terms } }
        })
      }

      return String(input) === '/api/legal' ? legal : json(404, {})
    })
  )
}

const renderScreen = async () => {
  await act(async () => {
    render(<SignInScreen />)
  })
}

const legalLinks = () => screen.queryAllByRole('button', { name: 'Terms and Acceptable Use' })

describe('SignInScreen legal link', () => {
  beforeEach(() => {
    // The Radix checkbox measures itself.
    vi.stubGlobal(
      'ResizeObserver',
      class {
        disconnect() {}
        observe() {}
        unobserve() {}
      }
    )
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ addEventListener: vi.fn(), matches: true, removeEventListener: vi.fn() }))
    )
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('is in the footer in sign-in mode and in sign-up mode', async () => {
    serve({ required: false })
    await renderScreen()
    expect(legalLinks()).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }))
    expect(legalLinks()).toHaveLength(1)
  })

  it('also sits beside the house-rules checkbox when this Harvis asks for it', async () => {
    serve({ required: true, points: ['Be kind here.'] })
    await renderScreen()
    expect(legalLinks()).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }))
    expect(screen.getByText('Be kind here.')).toBeTruthy()
    expect(legalLinks()).toHaveLength(2)
    // The checkbox label is untouched.
    expect(screen.getByLabelText('I have read the house rules and agree to them.')).toBeTruthy()
  })

  it('opens the terms without signing anyone in, and survives an older server', async () => {
    serve({ required: false })
    await renderScreen()

    await act(async () => {
      fireEvent.click(legalLinks()[0]!)
    })

    expect(await screen.findByText(/does not publish its terms yet/)).toBeTruthy()
    expect(screen.getByRole('dialog')).toBeTruthy()
  })
})
