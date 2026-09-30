/**
 * Spoken navigation: "open settings", "take me to my notebooks", "go to Discord".
 *
 * A voice turn that sounds like a page request is matched here BEFORE it is
 * sent to the model, as a tree: the app's pages, then the tabs inside them
 * (lib/voice-nav-tree.ts: "Discord" is Messaging → Discord), then whatever
 * navigation is on screen right now (lib/voice-nav-screen.ts: a file in the
 * Files tree, a notebook, a room). Names are matched exactly, which is instant
 * and never wrong; a short target that matches nothing is handed to the
 * backend, which asks the Laya sidecar
 * (python_back_end/plugins/hermes_ui/voice_route.py) and only answers above a
 * strict confidence bar. Anything else (a question, a task) returns null and
 * the line goes to the model as usual.
 */
import { contributedRoutes, navigateToWorkspacePage, SIDEBAR_NAV_AREA, type SidebarNavContribution } from '@/app/routes'
import { registry } from '@/contrib/registry'

import { findOnScreen } from './voice-nav-screen'
import { VOICE_NAV_CHILDREN } from './voice-nav-tree'

export interface VoiceDestination {
  id: string
  label: string
  path: string
  names: string[]
  /** The page a tab belongs to ("/messaging" for Discord). */
  parent?: string
  /** An on-screen item to click instead of changing the URL. */
  element?: HTMLElement
}

const CORE: VoiceDestination[] = [
  { id: 'new', label: 'a new chat', path: '/', names: ['new chat', 'new conversation', 'blank chat', 'fresh chat'] },
  { id: 'settings', label: 'Settings', path: '/settings', names: ['settings', 'preferences', 'options'] },
  { id: 'command-center', label: 'Command Center', path: '/command-center', names: ['command center', 'dashboard'] },
  { id: 'skills', label: 'Skills', path: '/skills', names: ['skills', 'capabilities', 'tools'] },
  {
    id: 'messaging',
    label: 'Messaging',
    path: '/messaging',
    names: ['messaging', 'messages', 'channels', 'messaging apps', 'apps']
  },
  { id: 'webhooks', label: 'Webhooks', path: '/webhooks', names: ['webhooks', 'webhook'] },
  { id: 'artifacts', label: 'Artifacts', path: '/artifacts', names: ['artifacts', 'files', 'documents'] },
  {
    id: 'cron',
    label: 'Scheduled jobs',
    path: '/cron',
    names: [
      'cron',
      'cron jobs',
      'crontab',
      'chron jobs',
      'crown jobs',
      'corn jobs',
      'scheduled jobs',
      'scheduled tasks',
      'scheduler',
      'schedules',
      'schedule',
      'reminders',
      'timers',
      'jobs',
      'automations'
    ]
  },
  { id: 'profiles', label: 'Profiles', path: '/profiles', names: ['profiles', 'profile', 'personas'] },
  { id: 'agents', label: 'Agents', path: '/agents', names: ['agents'] },
  { id: 'starmap', label: 'Star Map', path: '/starmap', names: ['star map', 'starmap'] }
]

// Plugin pages: extra spoken names for the ones that exist today. A page a
// plugin adds later is still reachable by its sidebar label.
const PAGE_NAMES: Record<string, { label: string; names: string[] }> = {
  '/research': { label: 'Deep Research', names: ['research', 'deep research', 'research reports'] },
  '/notebooks': { label: 'Notebooks', names: ['notebooks', 'notebook'] },
  '/bots': { label: 'Bots', names: ['bots', 'bot mode', 'bot rooms', 'rooms', 'group chat', 'group chats'] },
  '/browser': { label: 'Browser', names: ['browser', 'web browser'] },
  '/kanban': { label: 'Kanban', names: ['kanban', 'kanban board', 'board'] }
}

/** Every page a spoken line can open: the app's own pages plus plugin pages. */
export function voiceDestinations(): VoiceDestination[] {
  const navLabels = new Map<string, string>()

  for (const c of registry.getArea(SIDEBAR_NAV_AREA)) {
    const nav = c.data as SidebarNavContribution | undefined

    if (nav?.path && nav.label) {
      navLabels.set(nav.path, nav.label)
    }
  }

  const plugin = contributedRoutes().map(route => {
    const known = PAGE_NAMES[route.path]
    const label = navLabels.get(route.path) ?? known?.label ?? route.title ?? route.path.slice(1)

    return {
      id: route.path
        .slice(1)
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, '-')
        .slice(0, 40),
      label,
      path: route.path,
      names: [...new Set([label.toLowerCase(), ...(known?.names ?? [])])]
    }
  })

  const pages = [...CORE, ...plugin.filter(p => p.id && !CORE.some(c => c.id === p.id))]
  const tabs = pages.flatMap(page =>
    (VOICE_NAV_CHILDREN[page.path] ?? []).map(child => ({
      id: `${page.id}-${child.id}`
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, '-')
        .slice(0, 40),
      label: `${page.label}, ${child.label}`,
      path: `${page.path}?${child.query}`,
      names: child.names,
      parent: page.path
    }))
  )

  return [...pages, ...tabs]
}

const LEAD = /^(?:(?:hey|ok|okay)\s+\w+[,\s]+)?(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?/
const VERB_SOURCE =
  "(?:open(?:\\s+up)?|go\\s+(?:back\\s+)?to|take\\s+me\\s+(?:back\\s+)?to|bring\\s+me\\s+to|show\\s+me|switch\\s+to|navigate\\s+to|bring\\s+up|pull\\s+up|jump\\s+to|head\\s+to|let'?s\\s+go\\s+to)"
const VERB = new RegExp(`^${VERB_SOURCE}\\s+(.+)$`)
// Speech-to-text sometimes repeats a line ("navigate to discord navigate to
// discord …"): the target stops where the request starts over.
const REPEAT = new RegExp(`\\s+${VERB_SOURCE}(?:\\s|$)`)
const NEW_CHAT = /^(?:start|begin|make|create|open)\s+(?:a\s+)?(?:new|fresh|blank)\s+(?:chat|conversation)$/
const QUESTION_WORD = /^(?:how|what|why|where|when|who|which|whether|if|that|this|it)\b/
const PARENT_JOIN = /^(?:in|on|under|from|inside|within|of|for)\s+/
const MAX_TARGET_WORDS = 4

function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9' -]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function cleanTarget(target: string): string {
  return target
    .replace(/^(?:the|my|our|a|an)\s+/, '')
    .replace(/\s+(?:please|for me|now|real quick)$/, '')
    .replace(/\s+(?:page|tab|screen|view|section|panel|folder|file)$/, '')
    .replace(/^(?:the|my|our|a|an)\s+/, '')
    .trim()
}

/** What a line asks to open ("my notebooks page" → "notebooks"), or null when it
 *  is not phrased as a page request at all. */
export function navigationTarget(text: string): null | string {
  const line = normalise(text).replace(LEAD, '')

  if (NEW_CHAT.test(line)) {
    return 'new chat'
  }

  const target = VERB.exec(line)?.[1]?.split(REPEAT)[0]

  return target ? cleanTarget(target) || null : null
}

/** The tab named in "discord in messaging" / "messaging discord", given the page's name. */
function withoutParent(target: string, parentName: string): null | string {
  if (target.startsWith(`${parentName} `)) {
    return cleanTarget(target.slice(parentName.length + 1))
  }

  if (target.endsWith(` ${parentName}`)) {
    return cleanTarget(target.slice(0, -parentName.length - 1).replace(/\s+(?:in|on|under|from|inside|within|of)$/, ''))
  }

  return null
}

// Speech-to-text drops and adds endings: "schedule jobs" is "scheduled jobs",
// "setting" is "settings". Only used when no name matches exactly.
function stem(phrase: string): string {
  return phrase
    .split(' ')
    .map(word => (word.length > 3 ? word.replace(/s$/, '').replace(/(?:ing|ed|e)$/, '') : word))
    .join(' ')
}

type SameName = (name: string, target: string) => boolean

const EXACT: SameName = (name, target) => name === target
const LOOSE: SameName = (name, target) => stem(name) === stem(target)

function matchWith(same: SameName, target: string, pages: VoiceDestination[], here: string): null | VoiceDestination {
  const named = pages.filter(page => page.names.some(name => same(name, target)))

  if (named.length) {
    return named.find(p => !p.parent) ?? named.find(p => p.parent === here) ?? named[0]
  }

  for (const parent of pages.filter(p => !p.parent)) {
    for (const name of parent.names) {
      const rest = withoutParent(target, name)?.replace(PARENT_JOIN, '')

      if (rest) {
        const tab = pages.find(p => p.parent === parent.path && p.names.some(n => same(n, rest)))

        if (tab) {
          return tab
        }
      }
    }
  }

  return null
}

/**
 * The page or tab the target names outright, or null. A page wins over a tab
 * with the same name, and a tab of the page you are on wins over one elsewhere
 * ("sessions" on Settings is not Command Center's). An exact name beats one
 * that only matches without its endings.
 */
export function matchDestination(
  target: string,
  pages: VoiceDestination[],
  here = typeof window === 'undefined' ? '' : window.location.pathname
): null | VoiceDestination {
  return matchWith(EXACT, target, pages, here) ?? matchWith(LOOSE, target, pages, here)
}

/** The pages Laya chooses between: every page, then the tabs of the page you are on. */
function layaChoices(pages: VoiceDestination[], here: string): VoiceDestination[] {
  const top = pages.filter(p => !p.parent)

  return [...top, ...pages.filter(p => p.parent === here)].slice(0, 40)
}

async function askLaya(text: string, pages: VoiceDestination[]): Promise<null | string> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 4000)

  try {
    const res = await fetch('/hermes-api/api/harvis/voice/navigate', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, pages: pages.map(({ id, label }) => ({ id, label })) }),
      signal: controller.signal
    })

    if (!res.ok) {
      return null
    }

    const body = (await res.json()) as { page?: null | string }

    return typeof body.page === 'string' ? body.page : null
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

/** The page, tab or on-screen item a spoken line asks to open, or null to send the line to the model.
 *  `laya: false` skips the model fallback (a guess is not good enough for that line). */
export async function resolveVoiceNavigation(
  text: string,
  pages: VoiceDestination[] = voiceDestinations(),
  { laya = true }: { laya?: boolean } = {}
): Promise<null | VoiceDestination> {
  const target = navigationTarget(text)

  if (!target) {
    return null
  }

  const here = typeof window === 'undefined' ? '' : window.location.pathname
  const named = matchDestination(target, pages, here)

  if (named) {
    return named
  }

  // Only a short noun phrase can be a page; "show me how transformers work" is a question.
  if (target.split(' ').length > MAX_TARGET_WORDS || QUESTION_WORD.test(target)) {
    return null
  }

  const onScreen = typeof document === 'undefined' ? null : findOnScreen(target)

  if (onScreen) {
    return {
      id: 'screen',
      label: onScreen.label,
      path: here,
      names: [target],
      element: onScreen.element
    }
  }

  if (!laya) {
    return null
  }

  const choices = layaChoices(pages, here)
  const id = await askLaya(text, choices)

  return choices.find(page => page.id === id) ?? null
}

type Navigate = Parameters<typeof navigateToWorkspacePage>[0]

/** Open what `resolveVoiceNavigation` found: click it when it is on screen, else go to its page. */
export function openVoiceDestination(navigate: Navigate, destination: VoiceDestination): void {
  if (destination.element) {
    // A closed folder in a tree opens on its own row, not on the tree item
    // around it (clicking the item only selects it).
    const target =
      destination.element.querySelector<HTMLElement>('[aria-expanded="false"]:not([role="treeitem"])') ??
      destination.element

    target.scrollIntoView?.({ block: 'nearest' })
    target.click()

    return
  }

  navigateToWorkspacePage(navigate, destination.path)
}
