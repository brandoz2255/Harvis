import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  speakText: vi.fn()
}))

vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<typeof import('@/hermes')>()),
  speakText: mocks.speakText
}))

vi.mock('@/lib/voice-client-direct', async importOriginal => ({
  ...(await importOriginal<typeof import('@/lib/voice-client-direct')>()),
  directTtsConfig: vi.fn(async () => null)
}))

import { playSpeechText, startSpeechStream, stopVoicePlayback } from './voice-playback'

// Harvis: the browser UI has no speak-stream socket, so a spoken reply goes out
// one sentence at a time over POST /api/audio/speak — speech starts after the
// first sentence instead of after the whole reply.
describe('startSpeechStream without a speak-stream socket', () => {
  const played: string[] = []
  let endCurrent: (() => void) | null = null

  beforeEach(() => {
    played.length = 0
    endCurrent = null
    mocks.speakText.mockReset()
    mocks.speakText.mockImplementation(async (text: string) => ({ data_url: `data:audio/wav;base64,${btoa(text)}` }))

    class FakeAudio extends EventTarget {
      src: string

      constructor(src: string) {
        super()
        this.src = src
      }

      pause() {}

      play() {
        played.push(atob(this.src.split(',')[1]))
        endCurrent = () => this.dispatchEvent(new Event('ended'))

        return Promise.resolve()
      }
    }

    vi.stubGlobal('Audio', FakeAudio)
  })

  afterEach(() => {
    stopVoicePlayback()
    vi.unstubAllGlobals()
  })

  const tick = () => new Promise(resolve => setTimeout(resolve, 0))

  it('speaks the first sentence while the reply is still streaming', async () => {
    const session = await startSpeechStream({ source: 'voice-conversation' })

    expect(session).not.toBeNull()
    session!.append('Sure, the meeting moved to three today. ')
    session!.append('I also put the notes')
    await tick()

    expect(played).toEqual(['Sure, the meeting moved to three today.'])

    session!.append(' in your chat box for you. ')
    await tick()
    // The next sentence is synthesized while the first one plays.
    expect(mocks.speakText).toHaveBeenCalledTimes(2)

    endCurrent!()
    await tick()
    expect(played).toEqual([
      'Sure, the meeting moved to three today.',
      'I also put the notes in your chat box for you.'
    ])

    session!.finish()
    endCurrent!()

    await expect(session!.done).resolves.toBe('done')
  })

  it('falls back to whole-text playback when the first sentence cannot be synthesized', async () => {
    mocks.speakText.mockRejectedValue(new Error('TTS down'))

    const session = await startSpeechStream({ source: 'voice-conversation' })
    session!.append('This sentence never gets a voice at all. ')
    session!.finish()

    await expect(session!.done).resolves.toBe('fallback')
    expect(played).toEqual([])
  })

  it('stops speaking and drops the rest on barge-in', async () => {
    const session = await startSpeechStream({ source: 'voice-conversation' })
    session!.append('The first thing to say out loud here. The second thing that should never play. ')
    await tick()
    expect(played).toHaveLength(1)

    stopVoicePlayback()

    await expect(session!.done).resolves.toBe('done')
    endCurrent!()
    await tick()
    expect(played).toHaveLength(1)
  })
})

// Read-aloud of a finished reply must not wait for the whole text to be
// synthesized: with no speak-stream socket it goes out one sentence at a time.
describe('playSpeechText without a speak-stream socket', () => {
  const played: string[] = []

  beforeEach(() => {
    played.length = 0
    mocks.speakText.mockReset()
    mocks.speakText.mockImplementation(async (text: string) => ({ data_url: `data:audio/wav;base64,${btoa(text)}` }))

    class FakeAudio extends EventTarget {
      src: string

      constructor(src: string) {
        super()
        this.src = src
      }

      pause() {}

      play() {
        played.push(atob(this.src.split(',')[1]))
        setTimeout(() => this.dispatchEvent(new Event('ended')), 0)

        return Promise.resolve()
      }
    }

    vi.stubGlobal('Audio', FakeAudio)
  })

  afterEach(() => {
    stopVoicePlayback()
    vi.unstubAllGlobals()
  })

  it('synthesizes and plays one sentence at a time', async () => {
    const ok = await playSpeechText('The first sentence is right here. The second one follows it closely.', {
      source: 'read-aloud'
    })

    expect(ok).toBe(true)
    expect(mocks.speakText.mock.calls.map(c => c[0])).toEqual([
      'The first sentence is right here.',
      'The second one follows it closely.'
    ])
    expect(played).toEqual(['The first sentence is right here.', 'The second one follows it closely.'])
  })

  it('does not report success when a newer playback took over', async () => {
    const first = playSpeechText('An old reply that gets replaced before it finishes. It has a second sentence.', {
      source: 'read-aloud'
    })
    const second = playSpeechText('The newer reply wins the speaker.', { source: 'read-aloud' })

    await expect(first).resolves.toBe(false)
    await expect(second).resolves.toBe(true)
  })

  it('does not resynthesize the whole reply when stopped before the first sentence plays', async () => {
    let release: (() => void) | null = null

    mocks.speakText.mockImplementationOnce(
      (text: string) =>
        new Promise(resolve => {
          release = () => resolve({ data_url: `data:audio/wav;base64,${btoa(text)}` })
        })
    )

    const pending = playSpeechText('Stop me before I start talking. This part never plays.', { source: 'read-aloud' })

    await vi.waitFor(() => expect(release).not.toBeNull())
    stopVoicePlayback()
    release!()

    await expect(pending).resolves.toBe(false)
    expect(mocks.speakText).toHaveBeenCalledTimes(1)
    expect(played).toEqual([])
  })

  it('falls back to one whole-text request when the first sentence cannot be synthesized', async () => {
    mocks.speakText.mockRejectedValueOnce(new Error('TTS hiccup'))

    const text = 'The first sentence fails to synthesize. The whole reply then goes out at once.'
    const ok = await playSpeechText(text, { source: 'read-aloud' })

    expect(ok).toBe(true)
    expect(mocks.speakText.mock.calls.at(-1)?.[0]).toBe(text)
    expect(played).toEqual([text])
  })
})
