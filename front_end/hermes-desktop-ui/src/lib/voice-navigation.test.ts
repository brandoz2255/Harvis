import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  navigationTarget,
  openVoiceDestination,
  resolveVoiceNavigation,
  type VoiceDestination,
  voiceDestinations
} from './voice-navigation'

const PAGES: VoiceDestination[] = [
  { id: 'settings', label: 'Settings', path: '/settings', names: ['settings', 'preferences'] },
  { id: 'cron', label: 'Scheduled jobs', path: '/cron', names: ['cron', 'scheduled jobs', 'reminders'] },
  { id: 'starmap', label: 'Star Map', path: '/starmap', names: ['star map', 'starmap'] },
  { id: 'new', label: 'a new chat', path: '/', names: ['new chat'] },
  { id: 'notebooks', label: 'Notebooks', path: '/notebooks', names: ['notebooks'] }
]

function stubLaya(page: null | string) {
  const fetch = vi.fn(async () => new Response(JSON.stringify({ page, confidence: 0.9 }), { status: 200 }))
  vi.stubGlobal('fetch', fetch)

  return fetch
}

afterEach(() => vi.unstubAllGlobals())

describe('voice navigation', () => {
  it('pulls the page out of the ways people ask for one', () => {
    expect(navigationTarget('Open settings.')).toBe('settings')
    expect(navigationTarget('Can you please take me to my notebooks page?')).toBe('notebooks')
    expect(navigationTarget('hey harvis, pull up the star map')).toBe('star map')
    expect(navigationTarget('Start a new chat')).toBe('new chat')
    expect(navigationTarget('hi how are you')).toBeNull()
    expect(navigationTarget('what is the capital of france')).toBeNull()
  })

  it('opens a page named outright without asking Laya', async () => {
    const fetch = stubLaya('settings')

    expect((await resolveVoiceNavigation('open the star map', PAGES))?.path).toBe('/starmap')
    expect((await resolveVoiceNavigation('show me my scheduled jobs', PAGES))?.path).toBe('/cron')
    expect((await resolveVoiceNavigation('start a new chat', PAGES))?.path).toBe('/')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('asks Laya only about a short page-like target it cannot name', async () => {
    const fetch = stubLaya('notebooks')

    expect((await resolveVoiceNavigation('pull up my study notes', PAGES))?.path).toBe('/notebooks')
    expect(fetch).toHaveBeenCalledTimes(1)
    const body = JSON.parse(String((fetch.mock.calls[0] as unknown as [string, RequestInit])[1].body))
    expect(body.pages).toContainEqual({ id: 'cron', label: 'Scheduled jobs' })
  })

  it('leaves questions, chat and failures to the model', async () => {
    const fetch = stubLaya('settings')

    expect(await resolveVoiceNavigation('hi there', PAGES)).toBeNull()
    expect(await resolveVoiceNavigation('show me how transformers work', PAGES)).toBeNull()
    expect(await resolveVoiceNavigation('open the pdf about gpus that i uploaded yesterday', PAGES)).toBeNull()
    expect(fetch).not.toHaveBeenCalled()

    stubLaya(null)
    expect(await resolveVoiceNavigation('open the thing', PAGES)).toBeNull()

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('down', { status: 502 }))
    )
    expect(await resolveVoiceNavigation('open the thing', PAGES)).toBeNull()
  })

  it('lists the app pages even with no plugins loaded', () => {
    const ids = voiceDestinations().map(page => page.id)

    expect(ids).toEqual(expect.arrayContaining(['new', 'settings', 'cron', 'skills', 'artifacts']))
  })

  it('finds scheduled jobs however it is said', async () => {
    const fetch = stubLaya(null)

    for (const line of [
      'go to schedule jobs',
      'open the scheduled jobs page',
      'take me to my crown jobs',
      'open the scheduler',
      'go to schedules'
    ]) {
      expect((await resolveVoiceNavigation(line))?.path, line).toBe('/cron')
    }

    expect((await resolveVoiceNavigation('open setting'))?.path).toBe('/settings')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('never asks Laya when told not to', async () => {
    const fetch = stubLaya('notebooks')

    expect(await resolveVoiceNavigation('pull up my study notes', PAGES, { laya: false })).toBeNull()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('goes a level down into the tab you name', async () => {
    const fetch = stubLaya('settings')
    const open = async (line: string) => (await resolveVoiceNavigation(line))?.path

    expect(await open('navigate to discord')).toBe('/messaging?platform=discord')
    expect(await open('open my email')).toBe('/messaging?platform=email')
    expect(await open('go to the discord tab in messaging')).toBe('/messaging?platform=discord')
    expect(await open('open messaging telegram')).toBe('/messaging?platform=telegram')
    expect(await open('open voice settings')).toBe('/settings?tab=config:voice')
    expect(await open('take me to fallback models')).toBe('/settings?tab=config:model&mview=fallback')
    expect(await open('open mcp servers')).toBe('/skills?tab=mcp')
    expect(await open('show me usage')).toBe('/command-center?section=usage')
    expect(await open('open messaging')).toBe('/messaging')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('hears "Discord" through the usual speech-to-text slips', async () => {
    stubLaya(null)

    expect((await resolveVoiceNavigation('Go to this code.'))?.path).toBe('/messaging?platform=discord')
    expect(
      (await resolveVoiceNavigation('navigate to discord navigate to discord navigate to discord navigate'))?.label
    ).toBe('Messaging, Discord')
  })

  it('opens navigation that is on screen right now', async () => {
    stubLaya(null)
    document.body.innerHTML = `
      <ul role="tree"><li><button role="treeitem">SOUL.md</button></li><li><button role="treeitem">notes</button></li></ul>
      <button>Delete notes</button>`
    for (const el of document.querySelectorAll('button')) {
      el.getClientRects = () => [{}] as unknown as DOMRectList
    }
    const clicked = vi.fn()
    document.querySelector('[role="treeitem"]')!.addEventListener('click', clicked)

    const found = await resolveVoiceNavigation('open soul.md', PAGES)

    expect(found?.element?.textContent).toBe('SOUL.md')
    openVoiceDestination(vi.fn(), found!)
    expect(clicked).toHaveBeenCalledTimes(1)
    expect((await resolveVoiceNavigation('open delete notes', PAGES))?.element).toBeUndefined()
    document.body.innerHTML = ''
  })

  it('opens a closed folder in the Files tree by its row, not the tree item around it', async () => {
    stubLaya(null)
    document.body.innerHTML = `
      <div role="tree"><div role="treeitem" aria-expanded="false"><div aria-expanded="false"><span>skills</span></div></div></div>`
    const item = document.querySelector<HTMLElement>('[role="treeitem"]')!
    const row = item.firstElementChild as HTMLElement
    item.getClientRects = () => [{}] as unknown as DOMRectList
    const onRow = vi.fn()
    row.addEventListener('click', event => {
      event.stopPropagation()
      onRow()
    })
    const onItem = vi.fn()
    item.addEventListener('click', onItem)

    openVoiceDestination(vi.fn(), (await resolveVoiceNavigation('open the skills folder', []))!)

    expect(onRow).toHaveBeenCalledTimes(1)
    expect(onItem).not.toHaveBeenCalled()
    document.body.innerHTML = ''
  })
})
