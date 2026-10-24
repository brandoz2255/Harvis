import { type RefObject, useEffect, useMemo, useRef } from 'react'

import { artifactContentHash } from '@/lib/artifact-detect'
import { reportUnauthorized } from '@/lib/harvis-session'

/**
 * Smart artifacts: a sandboxed HTML page can ask Harvis a question and keep a
 * little data through ONE postMessage door: `window.harvis.askModel(prompt)`,
 * `saveData(key, value)` and `loadData(key)`, each returning a Promise.
 *
 * The iframe keeps `sandbox="allow-scripts"` with NO `allow-same-origin`. The
 * page posts a request tagged with the per-mount token; the parent believes it
 * only if the token matches AND it came from that mount's own frame, then
 * replies to that frame. askModel is a plain completion (no tools, no runs, no
 * web), capped in length, one in flight, ten a minute per artifact, because
 * the page was written by a model and could otherwise burn the user's GPU.
 * Data lives in the PARENT's localStorage (the frame has none), keyed by the
 * artifact's content hash, 64 KB at most.
 */

export const REQUEST_MESSAGE_TYPE = 'harvis-artifact-request'
export const RESPONSE_MESSAGE_TYPE = 'harvis-artifact-response'

/** Longest prompt a page may send. */
export const MAX_ASK_PROMPT = 4000
/** askModel calls allowed per artifact per rolling minute. */
export const MAX_ASKS_PER_MINUTE = 10
export const ASK_WINDOW_MS = 60_000
/** Cap on one artifact's saved data, measured on its serialized form. */
export const MAX_DATA_BYTES = 64 * 1024
const MAX_KEY_LENGTH = 128
/** Hard ceiling on the model's reply, so one call cannot hold the GPU for long. */
const ASK_MAX_TOKENS = 1024
const ASK_TIMEOUT_MS = 120_000
const DATA_STORAGE_PREFIX = 'harvis-artifact-data:v1:'

/** The chat route every Harvis page already uses (same-origin, session cookie). */
export const ASK_ENDPOINT = '/api/chat/completions'

// ---- the page's side: scripts injected into the srcdoc -----------------------------

const IN_FRAME_ASK_TIMEOUT_MS = ASK_TIMEOUT_MS + 15_000
const IN_FRAME_DATA_TIMEOUT_MS = 15_000

/** Runs FIRST (in `<head>` when there is one), so `window.harvis` exists before
 *  any of the page's own scripts. Calls made before the transport script loads
 *  are queued and sent once it attaches; the functions keep forwarding after
 *  that, so a page that captured `const ask = window.harvis.askModel` early
 *  still works. No messaging happens here — see `bridgeTransportScript`. */
export function bridgeStubScript(): string {
  return (
    '<script>(function(){var q=[],impl=null;function d(n){return function(){var a=arguments;' +
    'if(impl)return impl[n].apply(null,a);return new Promise(function(res,rej){q.push([n,a,res,rej])})}}' +
    'window.harvis={askModel:d("askModel"),saveData:d("saveData"),loadData:d("loadData"),' +
    '_attach:function(i){impl=i;var p;while(p=q.shift()){(function(x){try{i[x[0]].apply(null,x[1]).then(x[2],x[3])}' +
    'catch(e){x[3](e)}})(p)}}}})()</script>'
  )
}

/** The real implementation: request/response over postMessage with the mount
 *  token. Replies are only believed when they come from `parent` and carry the
 *  token and a request id we are waiting on. */
export function bridgeTransportScript(token: string): string {
  return (
    '<script>(function(){var T=' +
    JSON.stringify(token) +
    ',REQ=' +
    JSON.stringify(REQUEST_MESSAGE_TYPE) +
    ',RES=' +
    JSON.stringify(RESPONSE_MESSAGE_TYPE) +
    ',MAX=' +
    String(MAX_ASK_PROMPT) +
    ',pending={},seq=0;' +
    'function call(op,f,ms){return new Promise(function(resolve,reject){var id=++seq;' +
    'var timer=setTimeout(function(){delete pending[id];reject(new Error("Harvis did not answer in time."))},ms);' +
    'pending[id]={resolve:resolve,reject:reject,timer:timer};var m={type:REQ,token:T,id:id,op:op};' +
    'for(var k in f)m[k]=f[k];' +
    'try{parent.postMessage(m,"*")}catch(e){clearTimeout(timer);delete pending[id];reject(e)}})}' +
    'addEventListener("message",function(e){if(e.source!==parent)return;var d=e.data;' +
    'if(!d||d.type!==RES||d.token!==T)return;var p=pending[d.id];if(!p)return;delete pending[d.id];' +
    'clearTimeout(p.timer);if(d.ok)p.resolve(d.result);' +
    'else p.reject(new Error(typeof d.error==="string"?d.error:"Harvis could not do that."))});' +
    'function bad(s){return Promise.reject(new Error(s))}' +
    'function okKey(k){return typeof k==="string"&&k.length>0&&k.length<=' +
    String(MAX_KEY_LENGTH) +
    '}' +
    'var impl={askModel:function(p){if(typeof p!=="string"||!p.trim())return bad("askModel needs a prompt.");' +
    'if(p.length>MAX)return bad("askModel prompts are limited to "+MAX+" characters.");' +
    'return call("ask",{prompt:p},' +
    String(IN_FRAME_ASK_TIMEOUT_MS) +
    ')},saveData:function(k,v){if(!okKey(k))return bad("saveData needs a short text key.");var s;' +
    'try{s=JSON.stringify(v)}catch(x){return bad("saveData needs a JSON-serializable value.")}' +
    'if(typeof s!=="string")return bad("saveData needs a JSON-serializable value.");' +
    'return call("save",{key:k,json:s},' +
    String(IN_FRAME_DATA_TIMEOUT_MS) +
    ')},loadData:function(k){if(!okKey(k))return bad("loadData needs a short text key.");' +
    'return call("load",{key:k},' +
    String(IN_FRAME_DATA_TIMEOUT_MS) +
    ')}};' +
    'if(window.harvis&&window.harvis._attach)window.harvis._attach(impl);else window.harvis=impl})()</script>'
  )
}

/** Insert `snippet` as early as the document allows without breaking it: just
 *  inside `<head>`, else after `<html>`, else after the doctype, else first. */
function insertEarly(doc: string, snippet: string): string {
  const spots = [/<head(?=[\s>])[^>]*>/i, /<html(?=[\s>])[^>]*>/i, /^\s*<!doctype[^>]*>/i]

  for (const spot of spots) {
    const found = spot.exec(doc)

    if (found) {
      const at = found.index + found[0].length

      return doc.slice(0, at) + snippet + doc.slice(at)
    }
  }

  return snippet + doc
}

/** Insert `snippet` just before the LAST `</body>`, or append when there is none. */
function insertLate(doc: string, snippet: string): string {
  let at = -1

  for (const found of doc.matchAll(/<\/body\s*>/gi)) {
    at = found.index
  }

  return at < 0 ? doc + snippet : doc.slice(0, at) + snippet + doc.slice(at)
}

/** Give a document `window.harvis`: the stub early, the transport last. */
export function withArtifactBridge(doc: string, token: string): string {
  return insertLate(insertEarly(doc, bridgeStubScript()), bridgeTransportScript(token))
}

// ---- the parent's side ---------------------------------------------------------------

type BridgeOp = 'ask' | 'load' | 'save'

interface BridgeRequest {
  id: number
  json?: string
  key?: string
  op: BridgeOp
  prompt?: string
}

/** A refusal that is safe to show the page: the message is ours, never a stack. */
class BridgeError extends Error {}

/** Parse a page request. Null unless it is OUR type with OUR token and a sane shape. */
export function bridgeRequestFromMessage(data: unknown, token: string): BridgeRequest | null {
  if (typeof data !== 'object' || data === null) {
    return null
  }

  const m = data as Record<string, unknown>

  if (m.type !== REQUEST_MESSAGE_TYPE || m.token !== token || typeof m.id !== 'number' || !Number.isFinite(m.id)) {
    return null
  }

  if (m.op !== 'ask' && m.op !== 'save' && m.op !== 'load') {
    return null
  }

  return {
    id: m.id,
    json: typeof m.json === 'string' ? m.json : undefined,
    key: typeof m.key === 'string' ? m.key : undefined,
    op: m.op,
    prompt: typeof m.prompt === 'string' ? m.prompt : undefined
  }
}

/** Strip a reasoning model's `<think>` block, which is not part of the answer. */
function stripThinking(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/gi, '').trim()
}

function replyText(body: unknown): string {
  const content = (body as { choices?: { message?: { content?: unknown } }[] } | null)?.choices?.[0]?.message?.content

  return typeof content === 'string' ? content : ''
}

/**
 * One plain completion through the session the user is already signed in with
 * (same-origin cookie, a 401 asks the session watcher to re-check). No model is
 * named, so the user's default applies; `harvis_plain` keeps the turn to the
 * model alone — no tools, no runs, no web lookup.
 */
export async function askHarvis(prompt: string): Promise<string> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), ASK_TIMEOUT_MS)

  try {
    const res = await fetch(ASK_ENDPOINT, {
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        harvis_plain: true,
        harvis_research: false,
        max_tokens: ASK_MAX_TOKENS,
        messages: [{ content: prompt, role: 'user' }],
        model: '',
        stream: false
      }),
      signal: controller.signal
    })

    if (!res.ok) {
      if (res.status === 401) {
        reportUnauthorized()
      }

      throw new BridgeError(`Harvis could not answer (${res.status}).`)
    }

    const text = stripThinking(replyText(await res.json()))

    if (!text) {
      throw new BridgeError('Harvis sent an empty answer.')
    }

    return text
  } catch (error) {
    if (error instanceof BridgeError) {
      throw error
    }

    throw new BridgeError(
      controller.signal.aborted ? 'Harvis did not answer in time.' : 'Harvis is not answering right now.'
    )
  } finally {
    clearTimeout(timer)
  }
}

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>

function browserStorage(): null | StorageLike {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

const byteLength = (text: string): number => new TextEncoder().encode(text).length

/** The saved values for one artifact. Null-prototype, so a key named `__proto__` is plain data. */
type DataMap = Record<string, unknown>

function parseData(raw: null | string): DataMap {
  const data: DataMap = Object.create(null) as DataMap

  try {
    const parsed: unknown = JSON.parse(raw ?? '{}')

    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      Object.assign(data, parsed)
    }
  } catch {
    // damaged entry: start clean
  }

  return data
}

export interface BridgeHostOptions {
  /** Test seam; defaults to `askHarvis`. */
  ask?: (prompt: string) => Promise<string>
  /** The artifact's content hash NOW (it follows new versions). */
  contentKey: () => string
  /** This mount's own frame window — the only source a request is believed from. */
  frame: () => null | undefined | unknown
  /** Test seam; defaults to `Date.now`. */
  now?: () => number
  /** Test seam; defaults to `window.localStorage`, `null` for none (memory only). */
  storage?: null | StorageLike
  token: string
}

export interface BridgeHost {
  /** Resolves true once a valid request from our frame was answered, false when ignored. */
  handle: (event: { data: unknown; source: unknown }) => Promise<boolean>
}

/** The parent-side handler for one artifact mount. Holds the rate limit, the
 *  one-in-flight latch and the storage fallback, so they outlive any reload of
 *  the frame inside the page. */
export function createBridgeHost(options: BridgeHostOptions): BridgeHost {
  const ask = options.ask ?? askHarvis
  const now = options.now ?? Date.now
  const storage = options.storage === undefined ? browserStorage() : options.storage
  const memory = new Map<string, string>()
  const askTimes: number[] = []
  let asking = false

  const readRaw = (storageKey: string): null | string => {
    // Memory is newer than storage: used when localStorage is blocked or full.
    const pending = memory.get(storageKey)

    if (pending !== undefined) {
      return pending
    }

    try {
      const value = storage?.getItem(storageKey)

      return typeof value === 'string' ? value : null
    } catch {
      return null // storage unavailable
    }
  }

  const writeRaw = (storageKey: string, value: string) => {
    try {
      if (!storage) {
        throw new Error('no storage')
      }

      storage.setItem(storageKey, value)
      memory.delete(storageKey)
    } catch {
      memory.set(storageKey, value)
    }
  }

  const askModel = async (prompt: string | undefined): Promise<string> => {
    if (typeof prompt !== 'string' || !prompt.trim()) {
      throw new BridgeError('askModel needs a prompt.')
    }

    if (prompt.length > MAX_ASK_PROMPT) {
      throw new BridgeError(`askModel prompts are limited to ${MAX_ASK_PROMPT} characters.`)
    }

    if (asking) {
      throw new BridgeError('Harvis is still answering the last question.')
    }

    const at = now()

    while (askTimes.length && at - askTimes[0]! >= ASK_WINDOW_MS) {
      askTimes.shift()
    }

    if (askTimes.length >= MAX_ASKS_PER_MINUTE) {
      throw new BridgeError(`This page can ask ${MAX_ASKS_PER_MINUTE} questions a minute. Try again shortly.`)
    }

    askTimes.push(at)
    asking = true

    try {
      return await ask(prompt)
    } catch (error) {
      throw error instanceof BridgeError ? error : new BridgeError('Harvis could not answer.')
    } finally {
      asking = false
    }
  }

  const validKey = (key: string | undefined): key is string =>
    typeof key === 'string' && key.length > 0 && key.length <= MAX_KEY_LENGTH

  const saveData = (key: string | undefined, json: string | undefined): true => {
    if (!validKey(key)) {
      throw new BridgeError('saveData needs a short text key.')
    }

    let value: unknown

    try {
      value = JSON.parse(json ?? '')
    } catch {
      throw new BridgeError('saveData needs a JSON-serializable value.')
    }

    const storageKey = DATA_STORAGE_PREFIX + options.contentKey()
    const data = parseData(readRaw(storageKey))

    data[key] = value

    const serialized = JSON.stringify(data)

    if (byteLength(serialized) > MAX_DATA_BYTES) {
      throw new BridgeError(`Saved data is limited to ${MAX_DATA_BYTES / 1024} KB per page.`)
    }

    writeRaw(storageKey, serialized)

    return true
  }

  const loadData = (key: string | undefined): unknown => {
    if (!validKey(key)) {
      throw new BridgeError('loadData needs a short text key.')
    }

    const data = parseData(readRaw(DATA_STORAGE_PREFIX + options.contentKey()))

    return key in data ? data[key] : null
  }

  const run = async (request: BridgeRequest): Promise<unknown> => {
    if (request.op === 'ask') {
      return askModel(request.prompt)
    }

    return request.op === 'save' ? saveData(request.key, request.json) : loadData(request.key)
  }

  return {
    async handle(event) {
      const request = bridgeRequestFromMessage(event.data, options.token)
      const frame = options.frame()

      // Anything inside any frame can postMessage the parent: the token proves
      // it is this mount's document, and the source check proves it is this
      // mount's frame.
      if (!request || !frame || event.source !== frame) {
        return false
      }

      const reply = (body: { error?: string; ok: boolean; result?: unknown }) => {
        try {
          ;(frame as { postMessage: (message: unknown, target: string) => void }).postMessage(
            { id: request.id, token: options.token, type: RESPONSE_MESSAGE_TYPE, ...body },
            // The sandboxed document has an opaque origin; '*' is the only target that reaches it.
            '*'
          )
        } catch {
          // the frame went away mid-call
        }
      }

      try {
        reply({ ok: true, result: await run(request) })
      } catch (error) {
        reply({ error: error instanceof BridgeError ? error.message : 'Harvis could not do that.', ok: false })
      }

      return true
    }
  }
}

/** Content hash that keys an artifact's saved data (same FNV hash the registry uses, plus length). */
export function artifactDataKey(content: string): string {
  return `${artifactContentHash(content)}-${content.length.toString(36)}`
}

/** A fresh per-mount token. */
export function newBridgeToken(): string {
  try {
    const bytes = crypto.getRandomValues(new Uint32Array(2))

    return `${bytes[0]!.toString(36)}${bytes[1]!.toString(36)}`
  } catch {
    return Math.random().toString(36).slice(2)
  }
}

/**
 * Listen for the page in `frameRef` and answer it. `html` is the artifact's own
 * source (null until it has loaded); it only keys the saved data. The host, and
 * with it the rate limit, lives as long as the mount.
 */
export function useArtifactBridge(frameRef: RefObject<HTMLIFrameElement | null>, token: string, html: null | string) {
  const key = useMemo(() => (html === null ? '' : artifactDataKey(html)), [html])
  const keyRef = useRef(key)

  useEffect(() => {
    keyRef.current = key
  }, [key])

  useEffect(() => {
    const host = createBridgeHost({
      contentKey: () => keyRef.current,
      frame: () => frameRef.current?.contentWindow ?? null,
      token
    })

    const onMessage = (event: MessageEvent) => {
      void host.handle(event)
    }

    window.addEventListener('message', onMessage)

    return () => window.removeEventListener('message', onMessage)
  }, [frameRef, token])
}
