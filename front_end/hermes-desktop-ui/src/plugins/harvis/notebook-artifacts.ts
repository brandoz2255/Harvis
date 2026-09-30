/**
 * Studio artifacts, the open-notebook way: quizzes, flashcards and the Markdown
 * reports (study guide, briefing, FAQ, timeline) generated from a notebook's
 * sources and kept server-side, plus the notebook's podcasts, as one log.
 * Served by the `/onb-api` facade, which shares the Harvis session and tables.
 */

import { harvisApi } from './api'

export type ArtifactKind = 'briefing' | 'faq' | 'flashcards' | 'podcast' | 'quiz' | 'study_guide' | 'timeline'
export type GeneratableKind = Exclude<ArtifactKind, 'podcast'>

export interface QuizQuestion {
  q: string
  options: string[]
  answer: number
  explanation?: string
}

export interface Flashcard {
  front: string
  back: string
}

export interface Artifact {
  id: string
  kind: ArtifactKind
  title: string
  format: 'audio' | 'json' | 'markdown'
  content: { cards?: Flashcard[]; markdown?: string; questions?: QuizQuestion[] } | null
  status: string
  audio_url: null | string
  error_message: null | string
  created_at: string
}

/** The Create buttons, in the order open-notebook's Studio rail shows them. */
export const CREATE_KINDS: { icon: string; kind: GeneratableKind; label: string }[] = [
  { icon: 'question', kind: 'quiz', label: 'Quiz' },
  { icon: 'layers', kind: 'flashcards', label: 'Flashcards' },
  { icon: 'book', kind: 'study_guide', label: 'Study Guide' },
  { icon: 'file', kind: 'briefing', label: 'Briefing Doc' },
  { icon: 'comment-discussion', kind: 'faq', label: 'FAQ' },
  { icon: 'history', kind: 'timeline', label: 'Timeline' }
]

export const KIND_ICON: Record<ArtifactKind, string> = {
  ...(Object.fromEntries(CREATE_KINDS.map(c => [c.kind, c.icon])) as Record<GeneratableKind, string>),
  podcast: 'mic'
}

export const artifactsKey = (id: string) => ['harvis', 'notebooks', id, 'artifacts'] as const
export const suggestionsKey = (id: string, sourceCount: number) =>
  ['harvis', 'notebooks', id, 'suggestions', sourceCount] as const

const base = (notebookId: string) => `/onb-api/notebooks/${encodeURIComponent(notebookId)}`

export const listArtifacts = (notebookId: string) => harvisApi<Artifact[]>(`${base(notebookId)}/artifacts`)

export const generateArtifact = (notebookId: string, kind: GeneratableKind, model?: null | string) =>
  harvisApi<Artifact>(`${base(notebookId)}/generate`, {
    method: 'POST',
    body: JSON.stringify({ kind, model_id: model || undefined })
  })

export const deleteArtifact = (notebookId: string, artifactId: string) =>
  harvisApi(`${base(notebookId)}/artifacts/${encodeURIComponent(artifactId)}`, { method: 'DELETE' })

/** 4-6 questions grounded in the sources; an empty list when there is nothing to ask about. */
export const suggestQuestions = (notebookId: string, model?: null | string) =>
  harvisApi<{ questions: string[] }>(`${base(notebookId)}/suggest-questions`, {
    method: 'POST',
    body: JSON.stringify({ model_id: model || undefined })
  }).then(r => r.questions ?? [])

/** Podcasts are still being made while their status is one of these. */
export const isPodcastActive = (a: Artifact) =>
  a.kind === 'podcast' && ['generating', 'pending', 'queued', 'running'].includes(a.status)
