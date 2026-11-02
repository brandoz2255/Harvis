import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NotebookJoinButton, NotebookShareButton, type NotebookShare } from './notebook-share'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-1'
let shares: NotebookShare[] = []

const user = (id: string, username: string, role: NotebookShare['role']): NotebookShare => ({
  created_at: null,
  id,
  kind: 'user',
  role,
  username
})

const bodyOf = (path: string, method: string) => {
  const call = harvisApi.mock.calls.find(c => c[0] === path && c[1]?.method === method)

  return call ? JSON.parse(call[1].body as string) : undefined
}

beforeEach(() => {
  shares = []
  harvisApi.mockReset()
  harvisApi.mockImplementation(
    routeApi({
      [`GET /api/notebooks/${NB}/shares`]: () => ({ shares }),
      [`POST /api/notebooks/${NB}/shares/link`]: (_p, init) => {
        const { role } = JSON.parse(init?.body as string)
        const made: NotebookShare = {
          created_at: null,
          id: 'link-1',
          kind: 'link',
          role,
          token: 'raw-code-123',
          username: null
        }
        shares = [...shares, { ...made, token: undefined }]

        return made
      },
      [`POST /api/notebooks/${NB}/shares`]: (_p, init) => {
        const { role, user: who } = JSON.parse(init?.body as string)

        if (who === 'nobody') {
          throw new Error('No account matches that username or email.')
        }

        shares = [...shares, user('s-1', who, role)]

        return shares[shares.length - 1]
      },
      [`DELETE /api/notebooks/${NB}/shares/`]: path => {
        const id = path.split('/').pop()
        shares = shares.filter(s => s.id !== id)

        return { message: 'Share revoked' }
      },
      ['POST /api/notebooks/shares/accept']: (_p, init) => {
        if (JSON.parse(init?.body as string).token === 'dead') {
          throw new Error('That link is not valid or was revoked.')
        }

        return { notebook_id: 'nb-joined', role: 'viewer' }
      }
    })
  )
})

afterEach(cleanup)

const openShare = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'Share notebook' }))
  await screen.findByText('Who has access')
}

describe('NotebookShareButton', () => {
  it('renders nothing for someone who is not the owner and never asks for shares', () => {
    const { container } = renderWithQuery(<NotebookShareButton isOwner={false} notebookId={NB} />)

    expect(container.innerHTML).toBe('')
    expect(harvisApi).not.toHaveBeenCalled()
  })

  it('lists who has access, with their role', async () => {
    shares = [user('s-1', 'vera', 'viewer'), user('s-2', 'edna', 'editor')]
    renderWithQuery(<NotebookShareButton isOwner notebookId={NB} />)
    await openShare()

    expect(await screen.findByText('vera')).toBeTruthy()
    expect(screen.getByText('Viewer', { selector: 'span span' })).toBeTruthy()
    expect(screen.getByText('Editor', { selector: 'span span' })).toBeTruthy()
  })

  it('says only you when nothing is shared', async () => {
    renderWithQuery(<NotebookShareButton isOwner notebookId={NB} />)
    await openShare()

    expect(await screen.findByText('Only you.')).toBeTruthy()
  })

  it('adds a person by username or email with the chosen role', async () => {
    renderWithQuery(<NotebookShareButton isOwner notebookId={NB} />)
    await openShare()

    fireEvent.change(screen.getByLabelText('Add a person'), { target: { value: ' vera@example.test ' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Chat only' })[0]!)
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(screen.getByText('vera@example.test')).toBeTruthy())
    expect(bodyOf(`/api/notebooks/${NB}/shares`, 'POST')).toEqual({ role: 'chat_only', user: 'vera@example.test' })
    expect((screen.getByLabelText('Add a person') as HTMLInputElement).value).toBe('')
  })

  it('shows the server reason when the account does not exist', async () => {
    renderWithQuery(<NotebookShareButton isOwner notebookId={NB} />)
    await openShare()

    fireEvent.change(screen.getByLabelText('Add a person'), { target: { value: 'nobody' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))

    expect(await screen.findByText('No account matches that username or email.')).toBeTruthy()
  })

  it('creates a link code, shows it, and copies it', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    renderWithQuery(<NotebookShareButton isOwner notebookId={NB} />)
    await openShare()

    fireEvent.click(screen.getByRole('button', { name: 'Create link code' }))

    const input = (await screen.findByLabelText('Link code')) as HTMLInputElement
    expect(input.value).toBe('raw-code-123')
    expect(bodyOf(`/api/notebooks/${NB}/shares/link`, 'POST')).toEqual({ role: 'viewer' })

    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('raw-code-123'))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeTruthy()
  })

  it('revokes a person and drops the row; revoking the link also clears the shown code', async () => {
    shares = [user('s-1', 'vera', 'viewer')]
    renderWithQuery(<NotebookShareButton isOwner notebookId={NB} />)
    await openShare()
    await screen.findByText('vera')

    fireEvent.click(screen.getByRole('button', { name: 'Revoke vera' }))
    await waitFor(() => expect(screen.queryByText('vera')).toBeNull())
    expect(harvisApi).toHaveBeenCalledWith(`/api/notebooks/${NB}/shares/s-1`, { method: 'DELETE' })

    fireEvent.click(screen.getByRole('button', { name: 'Create link code' }))
    await screen.findByDisplayValue('raw-code-123')
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke Link code' }))
    await waitFor(() => expect(screen.queryByDisplayValue('raw-code-123')).toBeNull())
  })
})

describe('NotebookJoinButton', () => {
  it('redeems a code and reports the notebook it opened', async () => {
    const onJoined = vi.fn()
    renderWithQuery(<NotebookJoinButton onJoined={onJoined} />)
    fireEvent.click(screen.getByRole('button', { name: 'Join a notebook' }))
    fireEvent.change(screen.getByLabelText('Link code'), { target: { value: ' good-code ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Join' }))

    await waitFor(() => expect(onJoined).toHaveBeenCalledWith('nb-joined'))
    expect(bodyOf('/api/notebooks/shares/accept', 'POST')).toEqual({ token: 'good-code' })
  })

  it('shows the reason and stays open when the code is dead', async () => {
    const onJoined = vi.fn()
    renderWithQuery(<NotebookJoinButton onJoined={onJoined} />)
    fireEvent.click(screen.getByRole('button', { name: 'Join a notebook' }))
    fireEvent.change(screen.getByLabelText('Link code'), { target: { value: 'dead' } })
    fireEvent.click(screen.getByRole('button', { name: 'Join' }))

    expect(await screen.findByText('That link is not valid or was revoked.')).toBeTruthy()
    expect(onJoined).not.toHaveBeenCalled()
  })
})
