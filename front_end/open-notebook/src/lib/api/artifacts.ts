import apiClient from './client'

// Studio artifacts = the reviewable study material generated from a notebook.
// quiz / flashcards + the Markdown "report" kinds (study_guide / briefing / faq /
// timeline — the NotebookLM Reports set) are persisted server-side
// (onb_notebook_artifacts); podcasts come from standalone_podcasts and are merged
// into the same per-notebook log.
export type ArtifactKind =
  | 'quiz'
  | 'flashcards'
  | 'study_guide'
  | 'briefing'
  | 'faq'
  | 'timeline'
  | 'podcast'
export type GeneratableKind = Exclude<ArtifactKind, 'podcast'>

/** The report kinds — Markdown artifacts rendered with the shared markdown view. */
export const MARKDOWN_KINDS: ReadonlyArray<ArtifactKind> = [
  'study_guide',
  'briefing',
  'faq',
  'timeline',
]

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

export interface ArtifactContent {
  questions?: QuizQuestion[]
  cards?: Flashcard[]
  markdown?: string
}

export interface ArtifactLogItem {
  id: string
  kind: ArtifactKind
  title: string
  format: 'json' | 'markdown' | 'audio'
  content: ArtifactContent | null
  status: string
  audio_url: string | null
  error_message: string | null
  created_at: string
}

export const artifactsApi = {
  list: async (notebookId: string): Promise<ArtifactLogItem[]> => {
    const res = await apiClient.get<ArtifactLogItem[]>(`/notebooks/${notebookId}/artifacts`)
    return res.data
  },
  generate: async (
    notebookId: string,
    kind: GeneratableKind,
    modelId?: string,
    sourceIds?: string[],
  ): Promise<ArtifactLogItem> => {
    const res = await apiClient.post<ArtifactLogItem>(`/notebooks/${notebookId}/generate`, {
      kind,
      model_id: modelId,
      // Selected-source grounding (NotebookLM-style): only the checked sources.
      source_ids: sourceIds && sourceIds.length > 0 ? sourceIds : undefined,
    })
    return res.data
  },
  remove: async (notebookId: string, artifactId: string): Promise<void> => {
    await apiClient.delete(`/notebooks/${notebookId}/artifacts/${artifactId}`)
  },
}
