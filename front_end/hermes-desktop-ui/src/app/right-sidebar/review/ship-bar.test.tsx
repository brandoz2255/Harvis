import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { $reviewFiles } from '@/store/review'
import { resetServerCapabilities, setServerCapabilities } from '@/store/server-capabilities'

import { ReviewShipBar } from './ship-bar'

describe('ReviewShipBar', () => {
  beforeEach(() => {
    $reviewFiles.set([{ added: 1, path: 'a.txt', removed: 0, status: 'M' } as never])
  })

  afterEach(() => {
    cleanup()
    $reviewFiles.set([])
    resetServerCapabilities()
  })

  it('offers a plain Commit, with no push or pull request, when the repo has no remote', () => {
    setServerCapabilities({ capabilities: { git: true, git_remote: false } })
    render(<ReviewShipBar />)

    expect(screen.getByRole('button', { name: 'Commit' })).toBeTruthy()
    expect(screen.queryByText('Ask Harvis to open PR')).toBeNull()
    expect(screen.queryByLabelText('Create PR')).toBeNull()
    expect(screen.queryByText('Commit & Push')).toBeNull()
  })

  it('offers push and pull requests once the backend can reach a remote', () => {
    setServerCapabilities({ capabilities: { git: true, git_remote: true } })
    render(<ReviewShipBar />)

    expect(screen.getByText('Ask Harvis to open PR')).toBeTruthy()
    expect(screen.getByLabelText('Create PR')).toBeTruthy()
  })
})
