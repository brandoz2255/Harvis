import { cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Artifact } from './notebook-artifacts'
import { ArtifactView } from './notebook-artifact-view'
import { shuffled } from './notebook-flashcards'
import { renderWithQuery } from './notebook-test-utils'

vi.mock('./api', () => ({ harvisApi: vi.fn() }))

afterEach(cleanup)

const make = (content: Artifact['content'], kind: Artifact['kind'] = 'quiz'): Artifact => ({
  audio_url: null,
  content,
  created_at: '2026-10-12T00:00:00Z',
  error_message: null,
  format: 'json',
  id: 'a1',
  kind,
  status: 'ready',
  title: 'Item'
})

const cards = [
  { front: 'Front A', back: 'Back A' },
  { front: 'Front B', back: 'Back B' }
]

function renderView(artifact: Artifact) {
  return renderWithQuery(<ArtifactView artifact={artifact} notebookId="nb" onBack={() => undefined} />)
}

describe('Flashcards', () => {
  it('flips on click and on Space, and the buttons wait for the answer', () => {
    renderView(make({ cards }, 'flashcards'))
    const card = screen.getByRole('button', { name: 'Show the answer' })
    expect((screen.getByRole('button', { name: 'Got it' }) as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(card)
    expect(screen.getByText('Back A')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Got it' }) as HTMLButtonElement).disabled).toBe(false)

    fireEvent.keyDown(screen.getByRole('button', { name: 'Show the front' }), { key: ' ' })
    expect(screen.getByText('Front A')).toBeTruthy()
  })

  it('moves with next and previous and wraps around', () => {
    renderView(make({ cards }, 'flashcards'))
    fireEvent.click(screen.getByRole('button', { name: 'Next card' }))
    expect(screen.getByText('Front B')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next card' }))
    expect(screen.getByText('Front A')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Previous card' }))
    expect(screen.getByText('Front B')).toBeTruthy()
  })

  it('puts "Again" cards at the back of the pile and finishes when every card is known', () => {
    renderView(make({ cards }, 'flashcards'))
    fireEvent.click(screen.getByRole('button', { name: 'Show the answer' }))
    fireEvent.click(screen.getByRole('button', { name: 'Again' }))
    expect(screen.getByText('Front B')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Show the answer' }))
    fireEvent.click(screen.getByRole('button', { name: 'Got it' }))
    expect(screen.getByText('Front A')).toBeTruthy()
    expect(screen.getByText(/1 of 1 left · 1 known/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Show the answer' }))
    fireEvent.click(screen.getByRole('button', { name: 'Got it' }))
    expect(screen.getByText(/Done\. You knew all 2 cards/)).toBeTruthy()
    expect(screen.getByText(/1 time a card came back/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Study again' }))
    expect(screen.getByText('Front A')).toBeTruthy()
  })

  it('shuffles without losing or repeating a card', () => {
    const out = shuffled([1, 2, 3, 4, 5], () => 0.3)
    expect([...out].sort()).toEqual([1, 2, 3, 4, 5])
    renderView(make({ cards }, 'flashcards'))
    fireEvent.click(screen.getByRole('button', { name: /Shuffle/ }))
    expect(screen.getByText(/1 of 2 left/)).toBeTruthy()
  })
})

describe('Quiz', () => {
  const questions = [
    { q: 'Largest planet?', options: ['Mars', 'Jupiter'], answer: 1, explanation: 'Jupiter is a gas giant.' },
    { q: 'Red planet?', options: ['Mars', 'Venus'], answer: 0, explanation: 'Iron oxide on the surface.' }
  ]

  it('explains each answer, scores at the end, and can be retried', () => {
    renderView(make({ questions }))
    fireEvent.click(screen.getByRole('button', { name: 'Jupiter' }))
    expect(screen.getByText(/Correct\. Jupiter is a gas giant\./)).toBeTruthy()
    expect(screen.getByText('1 of 1 right so far')).toBeTruthy()
    expect(screen.queryByText(/You scored/)).toBeNull()

    fireEvent.click(screen.getAllByRole('button', { name: 'Venus' })[0])
    expect(screen.getByText(/Not quite\. The answer is: Mars\. Iron oxide/)).toBeTruthy()
    expect(screen.getByText('You scored 1 of 2')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByText('Pick an answer to check it.')).toBeTruthy()
    expect(screen.queryByText(/You scored/)).toBeNull()
  })
})

describe('Mind map', () => {
  const tree = {
    title: 'Mars',
    children: [
      { label: 'Surface', children: [{ label: 'Craters', children: [{ label: 'Jezero' }] }, { label: 'Dust' }] },
      { label: 'Moons' }
    ]
  }

  it('shows the first branches open and lets the person open and close the rest', () => {
    renderView(make({ tree }, 'mindmap'))
    expect(screen.getByText('Mars')).toBeTruthy()
    expect(screen.getByText('Dust')).toBeTruthy()
    expect(screen.queryByText('Jezero')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /Craters/ }))
    expect(screen.getByText('Jezero')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Collapse all' }))
    expect(screen.queryByText('Dust')).toBeNull()
    expect(screen.getByText('Surface')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(screen.getByText('Jezero')).toBeTruthy()
  })
})
