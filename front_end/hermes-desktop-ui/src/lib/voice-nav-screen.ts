/**
 * Spoken navigation inside whatever page is open: "open SOUL.md" in the Files
 * tree, "go to my GPU notebook", "open the planning room". Instead of a fixed
 * list it reads the navigation already on screen (tabs, tree rows, links and
 * list rows) and returns the one whose label the user said.
 *
 * Only things that move you somewhere count. A button that acts (send, save,
 * delete, run …) is never a match, even when its label is said outright.
 */

const NAV_ITEMS = [
  '[role="tab"]',
  '[role="treeitem"]',
  '[role="option"]',
  '[role="menuitemradio"]',
  'a[href]',
  'nav button',
  '[role="navigation"] button',
  '[role="tablist"] button',
  '[role="tree"] button',
  'li > button'
].join(', ')

// The voice call's own card and bubble, and anything modal, are never targets.
const OFF_LIMITS =
  '[data-slot="harvis-voice-orb"], [data-slot="harvis-voice-bubble"], [role="dialog"], [role="alertdialog"]'

const ACTION_WORDS =
  /\b(?:delete|remove|send|save|revoke|clear|reset|disconnect|sign|log ?out|pay|buy|purchase|install|uninstall|approve|deny|dismiss|archive|stop|kill|run|submit|publish|post|confirm|cancel|close|new|create|add|upload|download|share|copy|rename|edit|restart|update)\b/

const MAX_LABEL_WORDS = 6

export function normaliseLabel(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9' -]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** An element's visible words, with a space between separate pieces of text. */
function labelOf(el: HTMLElement): string {
  const aria = el.getAttribute('aria-label')

  if (aria) {
    return aria.trim()
  }

  const parts: string[] = []
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)

  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent?.trim()

    if (text) {
      parts.push(text)
    }
  }

  return parts.join(' ')
}

function usable(el: HTMLElement): boolean {
  if (el.closest(OFF_LIMITS) || el.matches(':disabled, [aria-disabled="true"]')) {
    return false
  }

  return el.getClientRects().length > 0
}

/** How well a label answers the spoken target: 3 exact, 2 starts with it, 1 contains it, 0 no. */
function score(label: string, target: string): number {
  if (!label || label.split(' ').length > MAX_LABEL_WORDS || ACTION_WORDS.test(label)) {
    return 0
  }

  if (label === target) {
    return 3
  }

  if (label.startsWith(`${target} `)) {
    return 2
  }

  return ` ${label} `.includes(` ${target} `) ? 1 : 0
}

export interface ScreenTarget {
  element: HTMLElement
  label: string
}

/** The on-screen navigation item the target names, or null. Ties go to the first on the page. */
export function findOnScreen(target: string, root: ParentNode = document): null | ScreenTarget {
  const wanted = normaliseLabel(target)

  if (!wanted || ACTION_WORDS.test(wanted)) {
    return null
  }

  let best: null | ScreenTarget = null
  let bestScore = 0

  for (const el of root.querySelectorAll<HTMLElement>(NAV_ITEMS)) {
    const label = labelOf(el)
    const s = score(normaliseLabel(label), wanted)

    if (s > bestScore && usable(el)) {
      best = { element: el, label: label.slice(0, 60) }
      bestScore = s

      if (s === 3) {
        break
      }
    }
  }

  return best
}
