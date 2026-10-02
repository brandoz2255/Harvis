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

import { startSpeechStream, stopVoicePlayback } from './voice-playback'

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
