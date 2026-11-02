import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithQuery, routeApi } from './notebook-test-utils'
import { castFor, DEFAULT_PROFILE, type SpeakerProfile, useSpeakerProfiles, VoicePicker } from './notebook-voices'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const builtin: SpeakerProfile = {
  id: DEFAULT_PROFILE,
  name: 'Host & Guest (default)',
  builtin: true,
  speakers: [
    { name: 'Host', voice_id: '__default__' },
    { name: 'Guest', voice_id: '__default__' }
  ]
}

const mine: SpeakerProfile = {
  id: 'p-1',
  name: 'Morning show',
  speakers: [
    { name: 'Ana', voice_id: 'af_bella' },
    { name: 'Ben', voice_id: 'bm_george' }
  ]
}

const voices = [
  { id: 'af_bella', name: 'Bella', gender: 'female', language: 'en-US' },
  { id: 'zf_xiaoxiao', name: 'Xiaoxiao', gender: 'female', language: 'zh' }
]

let saved: unknown[] = []

function Harness({ onChange }: { onChange: (id: string) => void }) {
  const profiles = useSpeakerProfiles()

  return <VoicePicker onChange={onChange} profiles={profiles.data} value={DEFAULT_PROFILE} />
}

beforeEach(() => {
  saved = []
  // Radix Select needs these in jsdom.
  Element.prototype.hasPointerCapture ??= () => false
  Element.prototype.scrollIntoView ??= () => {}
  harvisApi.mockReset()
  harvisApi.mockImplementation(
    routeApi({
      'GET /onb-api/speaker-profiles': () => [builtin, mine],
      'GET /onb-api/podcasts/voices': () => ({ voices }),
      'POST /onb-api/speaker-profiles': (_p, init) => {
        saved.push(JSON.parse(String(init?.body)))

        return { ...mine, id: 'p-2' }
      }
    })
  )
})

afterEach(cleanup)

describe('castFor', () => {
  it('returns the chosen set of your own, and nothing for the default voices', () => {
    expect(castFor([builtin, mine], 'p-1')).toEqual([
      { name: 'Ana', voice_id: 'af_bella' },
      { name: 'Ben', voice_id: 'bm_george' }
    ])
    expect(castFor([builtin, mine], DEFAULT_PROFILE)).toBeUndefined()
    expect(castFor([builtin, mine], 'someone-elses')).toBeUndefined()
    expect(castFor(undefined, 'p-1')).toBeUndefined()
  })
})

describe('VoicePicker', () => {
  it('offers the default voices and your own sets, and reports a choice', async () => {
    const onChange = vi.fn()
    renderWithQuery(<Harness onChange={onChange} />)
    await waitFor(() => expect(harvisApi).toHaveBeenCalledWith('/onb-api/speaker-profiles'))

    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Voices' }), { key: 'Enter' })
    expect(await screen.findByRole('option', { name: 'Default voices' })).toBeTruthy()
    fireEvent.click(await screen.findByRole('option', { name: 'Morning show' }))

    expect(onChange).toHaveBeenCalledWith('p-1')
  })

  it('saves a new set with the voice picked from the service list', async () => {
    const onChange = vi.fn()
    renderWithQuery(<Harness onChange={onChange} />)

    fireEvent.click(await screen.findByRole('button', { name: /New voices/ }))
    fireEvent.change(screen.getByLabelText('Voice set name'), { target: { value: 'Night show' } })

    fireEvent.keyDown(await screen.findByRole('combobox', { name: 'Speaker 1 voice' }), { key: 'Enter' })
    fireEvent.click(await screen.findByRole('option', { name: /Xiaoxiao \(female, zh\)/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save voices' }))

    await waitFor(() => expect(onChange).toHaveBeenCalledWith('p-2'))
    expect(saved).toEqual([
      {
        name: 'Night show',
        speakers: [
          { name: 'Alex', voice_id: 'zf_xiaoxiao' },
          { name: 'Sam', voice_id: '__default__' }
        ]
      }
    ])
  })

  it('shows the server message when a save is refused', async () => {
    harvisApi.mockImplementation(
      routeApi({
        'GET /onb-api/speaker-profiles': () => [builtin],
        'GET /onb-api/podcasts/voices': () => ({ voices }),
        'POST /onb-api/speaker-profiles': () => {
          throw new Error("Unknown voice 'x'.")
        }
      })
    )
    renderWithQuery(<Harness onChange={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: /New voices/ }))
    fireEvent.change(screen.getByLabelText('Voice set name'), { target: { value: 'Bad' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save voices' }))

    expect(await screen.findByText("Unknown voice 'x'.")).toBeTruthy()
  })
})
