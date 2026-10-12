import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { McpOAuthClientForm } from './mcp-oauth-client-form'

afterEach(cleanup)

describe('McpOAuthClientForm', () => {
  it('does not submit without a client id', () => {
    const onSubmit = vi.fn()
    render(<McpOAuthClientForm busy={false} onSubmit={onSubmit} />)

    fireEvent.submit(screen.getByRole('button', { name: /connect/i }).closest('form')!)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits the id, and the secret only when one was typed', () => {
    const onSubmit = vi.fn()
    render(<McpOAuthClientForm busy={false} onSubmit={onSubmit} />)
    const [id, secret] = screen
      .getAllByRole('textbox')
      .concat(Array.from(document.querySelectorAll('input[type=password]')) as never)

    fireEvent.change(id!, { target: { value: ' abc ' } })
    fireEvent.submit(screen.getByRole('button', { name: /connect/i }).closest('form')!)
    expect(onSubmit).toHaveBeenLastCalledWith({ client_id: 'abc' })

    fireEvent.change(secret!, { target: { value: 's3' } })
    fireEvent.submit(screen.getByRole('button', { name: /connect/i }).closest('form')!)
    expect(onSubmit).toHaveBeenLastCalledWith({ client_id: 'abc', client_secret: 's3' })
  })

  it('tells the person which redirect URL to allow', () => {
    render(<McpOAuthClientForm busy={false} onSubmit={() => {}} />)
    expect(screen.getByText(/\/hermes-api\/api\/mcp\/oauth\/callback/)).toBeTruthy()
  })
})
