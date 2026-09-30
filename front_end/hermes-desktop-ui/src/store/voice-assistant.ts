import { atom } from 'nanostores'

/**
 * Harvis's voice assistant conversation: its own transcript, apart from the
 * user's chats (python_back_end/plugins/hermes_ui/rest_voice.py). Talking to
 * Harvis is "do this, do that": the call shows its replies in its own little
 * transcript and never posts into the chat the user has open. When a reply
 * carries text for the chat (between <chat-draft> tags) it waits in
 * `$voiceChatDrafts` until the voice call puts it in the chat box, unsent.
 */

export interface VoiceTurn {
  id: string
  role: 'assistant' | 'user'
  text: string
  pending?: boolean
}

const API = '/hermes-api/api/voice'
const MAX_TURNS = 40
const DRAFT_RE = /<chat-draft>([\s\S]*?)<\/chat-draft>/gi
const OPEN_TAG = '<chat-draft>'
const STOPPED = 'Stopped.'

export const $voiceTurns = atom<VoiceTurn[]>([])
export const $voiceBusy = atom(false)
export const $voiceChatDrafts = atom<string[]>([])

let loaded: Promise<void> | null = null
let controller: AbortController | null = null
let spokenId: null | string = null
let seq = 0

const nextId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${++seq}`

/** What the call says out loud: the reply without the text meant for the chat
 *  box, and without a tag still arriving mid-stream. Grows only by appending
 *  while a reply streams, which the live speech feed relies on. */
export function spokenVoiceText(text: string): string {
  let out = text.replace(DRAFT_RE, ' ')
  const open = out.toLowerCase().indexOf(OPEN_TAG)

  if (open >= 0) {
    out = out.slice(0, open)
  }

  for (let n = Math.min(OPEN_TAG.length - 1, out.length); n > 0; n--) {
    if (OPEN_TAG.startsWith(out.slice(-n).toLowerCase())) {
      return out.slice(0, -n)
    }
  }

  return out
}

/** The pieces of a finished reply meant for the chat box. */
export function voiceChatDrafts(text: string): string[] {
  return [...text.matchAll(DRAFT_RE)].map(m => m[1].trim()).filter(Boolean)
}

// "type milk and eggs", "type hello team in the chat": dictation into the chat
// box needs no model, so it skips the round trip (and a small model's chance to
// paraphrase). Anything else goes to Harvis.
const DICTATE_RE =
  /^(?:please\s+)?type\s+(?:out\s+)?([\s\S]+?)(?:\s+(?:in|into)\s+(?:the\s+|my\s+)?chat(?:\s*box)?)?[.!]?$/i

// "put/write … in my chat" only counts when the chat is named.
const PUT_RE = /^(?:please\s+)?(?:put|write)\s+([\s\S]+?)\s+(?:in|into)\s+(?:the\s+|my\s+)?chat(?:\s*box)?[.!]?$/i

/** What to put in the chat box for "type …" or "put … in my chat", or null. */
export function dictationText(said: string): null | string {
  const match = DICTATE_RE.exec(said.trim()) ?? PUT_RE.exec(said.trim())

  return match ? match[1].trim() || null : null
}

function setTurns(update: (turns: VoiceTurn[]) => VoiceTurn[]) {
  $voiceTurns.set(update($voiceTurns.get()).slice(-MAX_TURNS))
}

function patchTurn(id: string, patch: Partial<VoiceTurn>) {
  setTurns(turns => turns.map(turn => (turn.id === id ? { ...turn, ...patch } : turn)))
}

/** The earlier voice conversation, loaded once per page load. Its replies count as spoken. */
export function loadVoiceSession(): Promise<void> {
  loaded ??= (async () => {
    try {
      const res = await fetch(`${API}/session`, { credentials: 'include' })

      if (!res.ok) {
        return
      }

      const body = (await res.json()) as { messages?: { role: string; text: string }[] }

      const history = (body.messages ?? [])
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map((m, i) => ({ id: `h-${i}`, role: m.role as VoiceTurn['role'], text: m.text }))

      if (!$voiceTurns.get().length) {
        $voiceTurns.set(history.slice(-MAX_TURNS))
        spokenId = history.findLast(t => t.role === 'assistant')?.id ?? spokenId
      }
    } catch {
      loaded = null
    }
  })()

  return loaded
}

/** The newest reply the call hasn't spoken yet, in the shape the voice loop reads. */
export function pendingVoiceReply(): null | { id: string; pending: boolean; text: string } {
  const last = $voiceTurns.get().findLast(t => t.role === 'assistant')

  if (!last || last.id === spokenId) {
    return null
  }

  const text = spokenVoiceText(last.text).trim()

  if (!text && !last.pending) {
    return null
  }

  return { id: last.id, pending: Boolean(last.pending), text }
}

export function markVoiceReplySpoken() {
  spokenId = $voiceTurns.get().findLast(t => t.role === 'assistant')?.id ?? spokenId
}

/** A turn Harvis handled in the browser (opening a page, typing into the chat). */
export function addLocalVoiceExchange(said: string, reply: string) {
  setTurns(turns => [
    ...turns,
    { id: nextId('u'), role: 'user', text: said },
    { id: nextId('a'), role: 'assistant', text: reply }
  ])
}

export function queueChatDraft(text: string) {
  const trimmed = text.trim()

  if (trimmed) {
    $voiceChatDrafts.set([...$voiceChatDrafts.get(), trimmed])
  }
}

export function takeChatDrafts(): string[] {
  const drafts = $voiceChatDrafts.get()

  $voiceChatDrafts.set([])

  return drafts
}

type Line = { t: 'delta'; text: string } | { t: 'done'; text: string; status?: string } | { t: string }

/** Ask the voice assistant. The reply streams into `$voiceTurns`; text for the chat box is queued. */
export async function sendVoiceTurn(text: string, { page = '' }: { page?: string } = {}): Promise<void> {
  const said = text.trim()

  if (!said || $voiceBusy.get()) {
    return
  }

  const replyId = nextId('a')
  const abort = new AbortController()
  let reply = ''

  controller = abort
  $voiceBusy.set(true)
  setTurns(turns => [
    ...turns,
    { id: nextId('u'), role: 'user', text: said },
    { id: replyId, pending: true, role: 'assistant', text: '' }
  ])

  try {
    const res = await fetch(`${API}/turn`, {
      body: JSON.stringify({ page, text: said }),
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
      signal: abort.signal
    })

    if (!res.ok || !res.body) {
      reply = res.status === 409 ? 'Still working on the last one.' : `Sorry, that didn't go through (${res.status}).`

      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()

      if (done) {
        break
      }

      buffer += decoder.decode(value, { stream: true })
      let newline = buffer.indexOf('\n')

      while (newline >= 0) {
        const raw = buffer.slice(0, newline).trim()

        buffer = buffer.slice(newline + 1)
        newline = buffer.indexOf('\n')

        if (!raw) {
          continue
        }

        const line = JSON.parse(raw) as Line

        if (line.t === 'delta' && 'text' in line) {
          reply += line.text
          patchTurn(replyId, { text: reply })
        } else if (line.t === 'done' && 'text' in line) {
          reply = line.text
        }
      }
    }
  } catch (error) {
    if (!abort.signal.aborted) {
      reply = reply || `Sorry, I couldn't reach Harvis (${error instanceof Error ? error.message : String(error)}).`
    }
  } finally {
    if (controller === abort) {
      controller = null
    }

    const final = reply.replace('\n\n[interrupted]', '').trim()

    // A reply cut off before its first word still gets a line, not a blank
    // that looks like the request vanished. It is not read out.
    if (!final) {
      spokenId = replyId
    }

    patchTurn(replyId, { pending: false, text: final || STOPPED })
    $voiceBusy.set(false)

    if (!abort.signal.aborted) {
      voiceChatDrafts(reply).forEach(queueChatDraft)
    }
  }
}

/** Stop the reply in flight (the user spoke over it, or ended the call). */
export function stopVoiceTurn() {
  controller?.abort()
}

/** Start the voice conversation over; the old one stays hidden on the server. */
export async function resetVoiceSession(): Promise<void> {
  stopVoiceTurn()
  $voiceTurns.set([])
  spokenId = null

  try {
    await fetch(`${API}/session`, { credentials: 'include', method: 'DELETE' })
  } catch {
    // Offline: the next turn still goes to the old conversation.
  }
}
