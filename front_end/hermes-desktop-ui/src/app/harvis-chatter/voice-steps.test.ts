import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { runVoiceSteps, splitVoiceSteps } from './voice-steps'

const draft = vi.fn()
const exchange = vi.fn()

vi.mock('@/store/voice-assistant', async importOriginal => ({
  ...(await importOriginal<typeof import('@/store/voice-assistant')>()),
  addLocalVoiceExchange: (...args: unknown[]) => exchange(...args),
  queueChatDraft: (...args: unknown[]) => draft(...args)
}))

beforeEach(() => {
  draft.mockClear()
  exchange.mockClear()
  // Nothing here should need Laya; fail loudly if a step asks it.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('down', { status: 502 }))
  )
})

afterEach(() => vi.unstubAllGlobals())

function handlers() {
  const log: string[] = []
  const navigate = vi.fn((to: unknown) => log.push(`go ${typeof to === 'string' ? to : JSON.stringify(to)}`))

  const ask = vi.fn(async (text: string) => {
    log.push(`ask ${text}`)
  })

  return { ask, log, navigate: navigate as never, settle: async () => {} }
}

describe('voice steps', () => {
  it('splits a line into the steps it was given, in order', () => {
    expect(splitVoiceSteps('open settings, then go to voice')).toEqual(['open settings', 'go to voice'])
    expect(splitVoiceSteps('go to messaging and open discord')).toEqual(['go to messaging', 'open discord'])
    expect(splitVoiceSteps('Open my notebooks. Type hello in the chat.')).toEqual([
      'Open my notebooks',
      'Type hello in the chat'
    ])
    expect(splitVoiceSteps('go to cron and after that open settings')).toEqual(['go to cron', 'open settings'])
    expect(splitVoiceSteps('put milk and eggs in my chat')).toEqual(['put milk and eggs in my chat'])
    expect(splitVoiceSteps('what is rust and why is it fast')).toEqual(['what is rust and why is it fast'])
  })

  it('opens each place in turn before the next step', async () => {
    const h = handlers()

    await runVoiceSteps('go to schedule jobs, then open settings', h)

    expect(h.log.map(line => line.split(' ')[0])).toEqual(['go', 'go'])
    expect(h.log[0]).toContain('/cron')
    expect(h.log[1]).toContain('/settings')
    expect(h.ask).not.toHaveBeenCalled()
    expect(exchange.mock.calls.map(call => call[1])).toEqual(['Opening Scheduled jobs.', 'Opening Settings.'])
  })

  it('hands what it cannot do itself to Harvis, in its place', async () => {
    const h = handlers()

    await runVoiceSteps('what time is it. Then open settings. Then tell me a joke', h)

    expect(h.log[0]).toBe('ask what time is it')
    expect(h.log[1]).toContain('/settings')
    expect(h.log[2]).toBe('ask tell me a joke')
  })

  it('sends a single question whole', async () => {
    const h = handlers()

    await runVoiceSteps('why is the sky blue?', h)

    expect(h.ask).toHaveBeenCalledWith('why is the sky blue?')
  })

  it('puts dictation in the chat box between other steps', async () => {
    const h = handlers()

    await runVoiceSteps('open settings, then put milk and eggs in my chat', h)

    expect(h.log[0]).toContain('/settings')
    expect(draft).toHaveBeenCalledTimes(1)
    expect(h.ask).not.toHaveBeenCalled()
  })
})
