import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { QUERY_KEYS } from '@/lib/api/query-client'
import {
  artifactsApi,
  type ArtifactLogItem,
  type GeneratableKind,
} from '@/lib/api/artifacts'
import { podcastsApi } from '@/lib/api/podcasts'

const ACTIVE_PODCAST_STATUSES = ['pending', 'generating', 'running', 'queued']

function hasActivePodcast(items?: ArtifactLogItem[]): boolean {
  return !!items?.some(
    (a) => a.kind === 'podcast' && ACTIVE_PODCAST_STATUSES.includes(a.status),
  )
}

/** The per-notebook Studio log: generated quiz/flashcards/study_guide + podcasts. */
export function useNotebookArtifacts(notebookId?: string) {
  return useQuery({
    queryKey: QUERY_KEYS.notebookArtifacts(notebookId ?? ''),
    queryFn: () => artifactsApi.list(notebookId!),
    enabled: !!notebookId,
    // Poll while a podcast is still generating so its status flips to ready live.
    // Stop on error / no-data so a failed fetch never polls forever.
    refetchInterval: (query) => {
      if (query.state.error || !query.state.data) return false
      return hasActivePodcast(query.state.data as ArtifactLogItem[]) ? 10_000 : false
    },
  })
}

export function useGenerateArtifact(notebookId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { kind: GeneratableKind; modelId?: string; sourceIds?: string[] }) =>
      artifactsApi.generate(notebookId, vars.kind, vars.modelId, vars.sourceIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookArtifacts(notebookId) })
    },
  })
}

export function useDeleteArtifact(notebookId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (item: ArtifactLogItem) =>
      item.kind === 'podcast'
        ? podcastsApi.deleteEpisode(item.id)
        : artifactsApi.remove(notebookId, item.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookArtifacts(notebookId) })
    },
  })
}
