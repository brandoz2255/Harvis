import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $voiceBusy,
  $voiceChatDrafts,
  $voiceTurns,
  dictationText,
  markVoiceReplySpoken,
  pendingVoiceReply,
  sendVoiceTurn,
  spokenVoiceText,
  takeChatDrafts,
  voiceChatDrafts
} from './voice-assistant'

function ndjson(lines: object[]) {
  const body = lines.map(l => JSON.stringify(l)).join('\n') + '\n'

  return new Response(
    new ReadableStream({
      start(controller) {
        // Split mid-line so the reader has to stitch chunks back together.
        const bytes = new TextEncoder().encode(body)
        controller.enqueue(bytes.slice(0, 20))
        controller.enqueue(bytes.slice(20))
        controller.close()
      }
    }),
    { status: 200 }
  )
}

beforeEach(() => {
  $voiceTurns.set([])
  $voiceChatDrafts.set([])
  $voiceBusy.set(false)
})

afterEach(() => vi.unstubAllGlobals())

describe('spokenVoiceText', () => {
  it('leaves out text meant for the chat box', () => {
    expect(spokenVoiceText('Done. <chat-draft>milk\neggs</chat-draft> Anything else?')).toBe('Done.   Anything else?')
  })

  it('hides a draft still streaming in, and a half-arrived tag', () => {
    expect(spokenVoiceText("It's in your chat box. <chat-draft>milk")).toBe("It's in your chat box. ")
    expect(spokenVoiceText("It's in your chat box. <chat-d")).toBe("It's in your chat box. ")
    expect(spokenVoiceText('Two < three')).toBe('Two < three')
  })

  it('only grows by appending while a reply streams', () => {
    const full = 'Sure. <chat-draft>a list</chat-draft> Done.'
    let before = ''

    for (let i = 1; i <= full.length; i++) {
      const now = spokenVoiceText(full.slice(0, i)).trimEnd()

      if (!full.slice(0, i).includes('</chat-draft>')) {
        expect(now.startsWith(before.trimEnd())).toBe(true)
      }

      before = now
    }
  })
})

describe('voiceChatDrafts', () => {
  it('pulls every draft out of a finished reply', () => {
    expect(
      voiceChatDrafts('<chat-draft> one </chat-draft> and <CHAT-DRAFT>two</CHAT-DRAFT><chat-draft> </chat-draft>')
    ).toEqual(['one', 'two'])
  })
})

describe('sendVoiceTurn', () => {
  it('streams the reply into its own transcript and queues the draft for the chat box', async () => {
    const fetchMock = vi.fn(async () =>
      ndjson([
        { t: 'start', session_id: 'v1' },
        { t: 'delta', text: "It's in your " },
        { t: 'delta', text: 'chat box.' },
        { t: 'done', text: "It's in your chat box. <chat-draft>milk\neggs</chat-draft>" }
      ])
    )
    vi.stubGlobal('fetch', fetchMock)

    await sendVoiceTurn('put milk and eggs in my chat', { page: 'Chat (/c/1)' })

    expect(fetchMock).toHaveBeenCalledWith(
      '/hermes-api/api/voice/turn',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ page: 'Chat (/c/1)', text: 'put milk and eggs in my chat' })
      })
    )
    const turns = $voiceTurns.get()
    expect(turns.map(t => t.role)).toEqual(['user', 'assistant'])
    expect(turns[1].pending).toBe(false)
    expect(pendingVoiceReply()).toMatchObject({ pending: false, text: "It's in your chat box." })
    expect(takeChatDrafts()).toEqual(['milk\neggs'])
    expect($voiceChatDrafts.get()).toEqual([])
    expect($voiceBusy.get()).toBe(false)

    markVoiceReplySpoken()
    expect(pendingVoiceReply()).toBeNull()
  })

  it('says so when the last turn is still running', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('busy', { status: 409 }))
    )

    await sendVoiceTurn('and another thing')

    expect($voiceTurns.get().at(-1)).toMatchObject({ pending: false, text: 'Still working on the last one.' })
    expect($voiceChatDrafts.get()).toEqual([])
  })
})

describe('dictationText', () => {
  it('takes what to type, with or without "in the chat"', () => {
    expect(dictationText('type milk, eggs and bread')).toBe('milk, eggs and bread')
    expect(dictationText('Type hello team in the chat.')).toBe('hello team')
    expect(dictationText('please type out see you at 5 into my chat box')).toBe('see you at 5')
    expect(dictationText('put milk and eggs in my chat')).toBe('milk and eggs')
    expect(dictationText('write running late into the chat box')).toBe('running late')
  })

  it('leaves everything else to Harvis', () => {
    expect(dictationText('make me a grocery list in the chat')).toBeNull()
    expect(dictationText('what type of dog is that')).toBeNull()
    expect(dictationText('type')).toBeNull()
    expect(dictationText('write me a poem about cats')).toBeNull()
  })
})
