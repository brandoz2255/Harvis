import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChatConfigButton, configBody } from './notebook-chat-config'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-1'
let stored: { length: string; output_language: null | string; persona: null | string; style: string } = {
  length: 'default',
  output_language: null,
  persona: null,
  style: 'default'
}

beforeEach(() => {
  stored = { length: 'default', output_language: null, persona: null, style: 'default' }
  harvisApi.mockReset()
  harvisApi.mockImplementation(
    routeApi({
      [`GET /api/notebooks/${NB}/chat-config`]: () => stored,
      [`PUT /api/notebooks/${NB}/chat-config`]: (_path, init) => {
        stored = JSON.parse(init?.body as string)

        return stored
      }
    })
  )
})

afterEach(cleanup)

describe('ChatConfigButton', () => {
  it('loads the saved settings into the dialog', async () => {
    stored = { length: 'longer', output_language: 'Spanish', persona: 'A skeptic', style: 'custom' }
    renderWithQuery(<ChatConfigButton notebookId={NB} />)
    fireEvent.click(screen.getByRole('button', { name: 'Configure chat' }))

    expect(((await screen.findByLabelText('Persona')) as HTMLTextAreaElement).value).toBe('A skeptic')
    expect((screen.getByLabelText('Answer language') as HTMLInputElement).value).toBe('Spanish')
    expect(screen.getByRole('button', { name: 'Longer' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'Custom' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('saves the chosen style, length and language with PUT', async () => {
    renderWithQuery(<ChatConfigButton notebookId={NB} />)
    fireEvent.click(screen.getByRole('button', { name: 'Configure chat' }))
    await screen.findByText('Style')

    expect(screen.queryByLabelText('Persona')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Learning guide' }))
    fireEvent.click(screen.getByRole('button', { name: 'Shorter' }))
    fireEvent.change(screen.getByLabelText('Answer language'), { target: { value: ' French ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `/api/notebooks/${NB}/chat-config`,
        expect.objectContaining({
          body: JSON.stringify({
            length: 'shorter',
            output_language: 'French',
            persona: null,
            style: 'learning_guide'
          }),
          method: 'PUT'
        })
      )
    )
    await waitFor(() => expect(screen.queryByText('Configure chat', { selector: 'h2' })).toBeNull())
  })

  it('shows the server error and keeps the dialog open when saving fails', async () => {
    harvisApi.mockImplementation(
      routeApi({
        [`GET /api/notebooks/${NB}/chat-config`]: () => stored,
        [`PUT /api/notebooks/${NB}/chat-config`]: () => {
          throw new Error('Persona is too long')
        }
      })
    )
    renderWithQuery(<ChatConfigButton notebookId={NB} />)
    fireEvent.click(screen.getByRole('button', { name: 'Configure chat' }))
    await screen.findByText('Style')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Persona is too long')).toBeTruthy()
  })
})

describe('configBody', () => {
  it('clears a blank persona or language and caps the lengths', () => {
    expect(configBody({ length: 'default', output_language: '  ', persona: '   ', style: 'default' })).toEqual({
      length: 'default',
      output_language: null,
      persona: null,
      style: 'default'
    })
    expect(
      configBody({ length: 'default', output_language: 'x'.repeat(60), persona: 'y'.repeat(2500), style: 'custom' })
    ).toMatchObject({ output_language: 'x'.repeat(40), persona: 'y'.repeat(2000) })
  })
})
