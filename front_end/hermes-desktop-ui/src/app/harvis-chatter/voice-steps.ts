/**
 * Several steps in one line, done in order: "open settings, then go to voice",
 * "go to messaging and open Discord", "open my notebooks. Type hello in the chat."
 * Each step that the app can do by itself (open a page, a tab or something on
 * screen; put text in the chat box) is done here, one after another, waiting for
 * the page to settle so the next step sees it. Whatever is left goes to Harvis
 * as one turn, in its place in the order, so a question keeps its context.
 */
import { openVoiceDestination, resolveVoiceNavigation, type VoiceDestination } from '@/lib/voice-navigation'
import { addLocalVoiceExchange, dictationText, queueChatDraft } from '@/store/voice-assistant'

type Navigate = Parameters<typeof openVoiceDestination>[0]

export interface VoiceStepHandlers {
  navigate: Navigate
  /** Hand a line to Harvis; resolves when the reply is done. */
  ask: (text: string) => Promise<void>
  /** Wait for the page to show the last step (tests pass an instant one). */
  settle?: () => Promise<void>
}

const STEP_VERBS =
  '(?:open|go|navigate|take|show|switch|bring|pull|jump|head|type|put|write|click|select|press|tap|expand|close)'

// Where one step ends: a sentence end, "then" / "after that", or "and" / a comma
// right before another command ("put milk and eggs in my chat" stays one step).
const STEP_BREAK = new RegExp(
  [
    '\\s*[.;!?]+\\s+',
    ',?\\s+(?:and\\s+)?then\\s+',
    ',?\\s+(?:and\\s+)?after\\s+that,?\\s+',
    `(?:,\\s*|\\s+)and\\s+(?=${STEP_VERBS}\\b)`,
    `,\\s*(?=${STEP_VERBS}\\b)`
  ].join('|'),
  'i'
)

const SETTLE_MS = 450

const settleDefault = () => new Promise<void>(resolve => window.setTimeout(resolve, SETTLE_MS))

/** The steps of a spoken or typed line, in order. */
export function splitVoiceSteps(text: string): string[] {
  return text
    .split(STEP_BREAK)
    .map(step =>
      step
        .trim()
        .replace(/^(?:(?:and|then|next|after that|and then),?\s+)+/i, '')
        .replace(/[.;!?,]+$/, '')
    )
    .filter(Boolean)
}

/** Run a line's steps one by one. */
export async function runVoiceSteps(text: string, { navigate, ask, settle = settleDefault }: VoiceStepHandlers) {
  const steps = splitVoiceSteps(text)
  let forHarvis: string[] = []
  let opened = false

  const flush = async () => {
    if (forHarvis.length) {
      const line = forHarvis.join('. ')

      forHarvis = []
      await ask(line)
    }
  }

  for (const step of steps) {
    // After opening something, a bare name is the next thing to open
    // ("go to settings then voice"), but only if it names something outright.
    let place: null | VoiceDestination = await resolveVoiceNavigation(step)

    if (!place && opened && !dictationText(step)) {
      place = await resolveVoiceNavigation(`open ${step}`, undefined, { laya: false })
    }

    if (place) {
      await flush()
      addLocalVoiceExchange(step, `Opening ${place.label}.`)
      openVoiceDestination(navigate, place)
      opened = true
      await settle()

      continue
    }

    const dictated = dictationText(step)

    if (dictated) {
      await flush()
      addLocalVoiceExchange(step, "It's in your chat box.")
      queueChatDraft(dictated)

      continue
    }

    forHarvis.push(steps.length > 1 ? step : text.trim())
  }

  await flush()
}
