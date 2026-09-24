/**
 * Bots: the /bots page (create, edit, duplicate, delete), the sidebar section
 * (list, start a chat bound to the bot), and the empty bot chat (starter chips).
 */

import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { stubResizeObserver } from '@/test/jsdom'

import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi, request, openSession, navigate, insert } = vi.hoisted(() => ({
  harvisApi: vi.fn(),
  request: vi.fn(),
  openSession: vi.fn(),
  navigate: vi.fn(),
  insert: vi.fn()
}))

vi.mock('./api', () => ({ harvisApi }))

vi.mock('@hermes/plugin-sdk', async importOriginal => {
  const sdk = await importOriginal<typeof import('@hermes/plugin-sdk')>()

  return { ...sdk, requestComposerInsert: insert, host: { ...sdk.host, navigate, openSession, request } }
})

const { BotsPage } = await import('./bots-page')
const { BotsSidebarSection } = await import('./bots-sidebar')
const { BotChatEmpty } = await import('./bot-chat')

const NB = '0f6d2a2e-4a0b-4c9b-9d2c-1c7d2c0a1234'

const paperBot = {
  id: 'b1',
  handle: 'paper-bot',
  name: 'Paper Bot',
  description: 'Reads papers.',
  instructions: 'Cite everything.',
  model: 'gemma4:e2b',
  avatar: { emoji: '📄' },
  notebook_ids: [NB],
  starter_prompts: ['Summarise the paper', 'List the methods'],
  tools: { web_research: true, workspace_agent: false },
  runs_on: {},
  created_at: null,
  updated_at: null
}

const posted: { method: string; path: string; body: unknown }[] = []

function mockRoutes(bots: unknown[] = [paperBot]) {
  harvisApi.mockImplementation(
    routeApi({
      'GET /hermes-api/api/harvis/bots/session/': () => ({ bot: paperBot }),
      'GET /hermes-api/api/harvis/bots': () => ({ bots }),
      'GET /hermes-api/api/model/options': () => ({
        model: 'gemma4:e2b',
        providers: [
          { name: 'Ollama', slug: 'ollama', models: ['gemma4:e2b', 'qwen3:8b'] },
          { name: 'LAN', slug: 'lan', models: ['gemma4:e2b'] }
        ]
      }),
      'GET /api/notebooks': () => ({ notebooks: [{ id: NB, title: 'Thesis', emoji: '🎓' }] }),
      'POST /hermes-api/api/harvis/bots/b1/duplicate': path => {
        posted.push({ method: 'POST', path, body: null })

        return { ...paperBot, id: 'b2', name: 'Paper Bot copy' }
      },
      'POST /hermes-api/api/harvis/bots': (path, init) => {
        const body = JSON.parse(String(init?.body))
        posted.push({ method: 'POST', path, body })

        return { ...paperBot, ...body, id: 'b3' }
      },
      'PUT /hermes-api/api/harvis/bots/b1': (path, init) => {
        const body = JSON.parse(String(init?.body))
        posted.push({ method: 'PUT', path, body })

        return { ...paperBot, ...body }
      },
      'DELETE /hermes-api/api/harvis/bots/b1': path => {
        posted.push({ method: 'DELETE', path, body: null })

        return { ok: true }
      }
    })
  )
}

function renderPage(url: string) {
  return renderWithQuery(
    <MemoryRouter initialEntries={[url]}>
      <BotsPage />
    </MemoryRouter>
  )
}

beforeEach(() => {
  stubResizeObserver()
  posted.length = 0
  harvisApi.mockReset()
  request.mockReset()
  openSession.mockReset()
  navigate.mockReset()
  insert.mockReset()
  mockRoutes()
})

afterEach(cleanup)

describe('the bots page', () => {
  it('creates a bot from the form with its knowledge, starters and tool switches', async () => {
    renderPage('/bots?id=new')

    fireEvent.change(await screen.findByPlaceholderText('e.g. Paper Reader'), { target: { value: 'Llama Expert' } })
    fireEvent.change(screen.getByLabelText(/^Instructions/), { target: { value: 'Only talk about llamas.' } })
    fireEvent.click(await screen.findByRole('button', { name: /Thesis/ }))
    fireEvent.change(screen.getByLabelText('New starter prompt'), { target: { value: 'Why llamas?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    fireEvent.click(screen.getByRole('switch', { name: 'Web research' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create bot' }))

    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0]).toMatchObject({
      method: 'POST',
      path: '/hermes-api/api/harvis/bots',
      body: {
        name: 'Llama Expert',
        instructions: 'Only talk about llamas.',
        notebook_ids: [NB],
        starter_prompts: ['Why llamas?'],
        tools: { web_research: false, workspace_agent: true }
      }
    })
  })

  it('keeps Create disabled until the bot has a name', async () => {
    renderPage('/bots?id=new')

    const create = await screen.findByRole('button', { name: 'Create bot' })
    expect((create as HTMLButtonElement).disabled).toBe(true)
  })

  it('edits, duplicates and deletes an existing bot', async () => {
    renderPage('/bots?id=b1')

    const name = await screen.findByDisplayValue('Paper Bot')
    fireEvent.change(name, { target: { value: 'Paper Bot 2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(posted.at(-1)).toMatchObject({ method: 'PUT', body: { name: 'Paper Bot 2' } }))

    fireEvent.click(screen.getByRole('button', { name: /Duplicate/ }))
    await waitFor(() => expect(posted.at(-1)?.path).toBe('/hermes-api/api/harvis/bots/b1/duplicate'))
  })

  it('asks before deleting', async () => {
    renderPage('/bots?id=b1')

    fireEvent.click(await screen.findByRole('button', { name: /Delete/ }))
    expect(posted).toHaveLength(0)
    const confirm = screen.getAllByRole('button', { name: /Delete/ }).at(-1)
    expect(screen.getByText(/Its chats stay/)).toBeTruthy()
    fireEvent.click(confirm as HTMLElement)
    await waitFor(() => expect(posted.at(-1)).toMatchObject({ method: 'DELETE' }))
  })

  it('does not press a button when the text of a grouped field is clicked', async () => {
    renderPage('/bots?id=b1')

    await screen.findByRole('button', { name: /Thesis/ })
    fireEvent.click(screen.getByText('Starter prompts', { selector: 'span' }))
    fireEvent.click(screen.getByText('Knowledge', { selector: 'span' }))
    expect(screen.getAllByRole('button', { name: /Remove starter/ })).toHaveLength(2)
    expect(screen.getByRole('button', { name: /Thesis/ }).getAttribute('aria-pressed')).toBe('true')
  })
})

describe('the sidebar bots section', () => {
  it('lists bots and starts a chat bound to the clicked one', async () => {
    request.mockResolvedValue({ session_id: 's-new', stored_session_id: 's-new' })
    renderWithQuery(<BotsSidebarSection />)

    fireEvent.click(await screen.findByRole('button', { name: 'Chat with Paper Bot' }))

    await waitFor(() => expect(openSession).toHaveBeenCalledWith('s-new', { intent: 'in-place' }))
    expect(request).toHaveBeenCalledWith('session.create', { bot_id: 'b1' })
  })

  it('offers to make the first bot when there are none', async () => {
    mockRoutes([])
    renderWithQuery(<BotsSidebarSection />)

    fireEvent.click(await screen.findByText(/No bots yet/))
    expect(navigate).toHaveBeenCalledWith('/bots?id=new')
  })

  it('shows the error when a chat cannot start', async () => {
    request.mockRejectedValue(new Error('gateway down'))
    renderWithQuery(<BotsSidebarSection />)

    fireEvent.click(await screen.findByRole('button', { name: 'Chat with Paper Bot' }))
    expect(await screen.findByText('gateway down')).toBeTruthy()
    expect(openSession).not.toHaveBeenCalled()
  })
})

describe('an empty bot chat', () => {
  it("shows the bot's name and puts a starter prompt in the composer", async () => {
    renderWithQuery(<BotChatEmpty sessionId="s1" />)

    expect(await screen.findByText('Paper Bot')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'List the methods' }))
    expect(insert).toHaveBeenCalledWith('List the methods')
    expect(harvisApi).toHaveBeenCalledWith('/hermes-api/api/harvis/bots/session/s1')
  })

  it('renders nothing for a plain chat', async () => {
    harvisApi.mockResolvedValue({ bot: null })
    const { container } = renderWithQuery(<BotChatEmpty sessionId="s2" />)

    await waitFor(() => expect(harvisApi).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })
})
