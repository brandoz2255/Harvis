import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { applyAskEvent, AskAllButton, EMPTY_ASK, toPassages } from './notebook-ask-all'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi, readSse } = vi.hoisted(() => ({ harvisApi: vi.fn(), readSse: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

vi.mock('./notebook-shared', async importOriginal => ({
  ...(await importOriginal<typeof import('./notebook-shared')>()),
  readSse,
  useChosenModel: () => ({ available: ['m1'], choose: () => undefined, chosen: 'm1', loading: false })
}))

const ev = (data: Record<string, unknown>) => ({ data, event: 'message' })

beforeEach(() => {
  harvisApi.mockReset()
  readSse.mockReset()
  harvisApi.mockImplementation(
    routeApi({
      'POST /onb-api/search': () => ({
        results: [{ matches: ['Perseverance landed in Jezero.'], title: 'Mars page' }]
      })
    })
  )
})

afterEach(cleanup)

describe('applyAskEvent', () => {
  it('folds the stream into strategy, answers and the final answer', () => {
    let s = applyAskEvent(
      EMPTY_ASK,
      ev({
        reasoning: 'Two angles',
        searches: [{ instructions: 'dates', term: 'landing' }, { term: '' }],
        type: 'strategy'
      })
    )
    expect(s.searches).toEqual([{ instructions: 'dates', term: 'landing' }])
    s = applyAskEvent(s, ev({ content: 'Sub answer', type: 'answer' }))
    s = applyAskEvent(s, ev({ content: 'Final', type: 'final_answer' }))
    s = applyAskEvent(s, ev({ type: 'complete' }))
    expect(s).toMatchObject({ answers: ['Sub answer'], done: true, error: '', final: 'Final' })
    expect(applyAskEvent(s, ev({ type: 'mystery' }))).toBe(s)
  })

  it('records an error frame', () => {
    expect(applyAskEvent(EMPTY_ASK, ev({ message: 'model gone', type: 'error' }))).toMatchObject({
      done: true,
      error: 'model gone'
    })
  })
})

describe('toPassages', () => {
  it('keeps a title and a one-line snippet, and tolerates junk', () => {
    expect(toPassages([{ matches: ['a\n\nb'], title: 'T' }, {}])).toEqual([
      { snippet: 'a b', title: 'T' },
      { snippet: '', title: 'Untitled source' }
    ])
    expect(toPassages(null)).toEqual([])
  })
})

describe('AskAllButton', () => {
  it('asks every notebook with the chosen model and shows the answer and the passages found', async () => {
    readSse.mockImplementation(async (_path: string, _body: unknown, onEvent: (e: unknown) => void) => {
      onEvent(ev({ reasoning: 'Plan', searches: [{ term: 'landing' }], type: 'strategy' }))
      onEvent(ev({ content: 'Sub', type: 'answer' }))
      onEvent(ev({ content: 'It landed in 2021.', type: 'final_answer' }))
      onEvent(ev({ type: 'complete' }))
    })

    renderWithQuery(<AskAllButton />)
    fireEvent.click(screen.getByRole('button', { name: /Ask all notebooks/ }))
    fireEvent.change(await screen.findByLabelText('Your question'), { target: { value: 'When did it land?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText('It landed in 2021.')).toBeTruthy()
    expect(await screen.findByText('Mars page')).toBeTruthy()
    expect(readSse).toHaveBeenCalledWith(
      '/onb-api/search/ask',
      { answer_model: 'm1', final_answer_model: 'm1', question: 'When did it land?', strategy_model: 'm1' },
      expect.any(Function),
      expect.anything()
    )
  })

  it('shows the server error', async () => {
    readSse.mockRejectedValue(new Error('No model is allowed for you.'))
    renderWithQuery(<AskAllButton />)
    fireEvent.click(screen.getByRole('button', { name: /Ask all notebooks/ }))
    fireEvent.change(await screen.findByLabelText('Your question'), { target: { value: 'q' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    await waitFor(() => expect(screen.getByText('No model is allowed for you.')).toBeTruthy())
  })
})
