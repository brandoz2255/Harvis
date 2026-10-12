/**
 * What the server can do for a notebook right now (reading audio and images,
 * speaking a podcast, searching the web). The UI reads this to disable a control
 * with a one-line reason instead of letting the person hit a failure.
 * Served by `GET /api/notebooks/meta/capabilities`; when it can't be reached
 * nothing is blocked up front and the server's own message is shown instead.
 */

import { useQuery } from '@hermes/plugin-sdk'

import { harvisApi } from './api'

export interface Capability {
  ready: boolean
  reason: string
}

export interface NotebookCapabilities {
  audio_sources: Capability
  deep_research: Capability
  embedder: Capability
  image_sources: Capability
  podcast_audio: Capability
  web_search: Capability
}

export const capabilitiesKey = ['harvis', 'notebooks', 'capabilities'] as const

export function useCapabilities(): NotebookCapabilities | undefined {
  return useQuery({
    queryFn: () => harvisApi<NotebookCapabilities>('/api/notebooks/meta/capabilities'),
    queryKey: capabilitiesKey,
    retry: false,
    staleTime: 60_000
  }).data
}

/** The reason a feature is off, or '' when it is on (or unknown). */
export const blockedReason = (cap?: Capability) => (cap && !cap.ready ? cap.reason : '')

const AUDIO_EXT = /\.(mp3|wav|m4a|ogg|oga|opus|webm|flac|aac)$/i
const IMAGE_EXT = /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i

/** Why this file can't be read here, or '' when it can. */
export function fileBlockedReason(name: string, caps?: NotebookCapabilities): string {
  if (AUDIO_EXT.test(name)) {
    return blockedReason(caps?.audio_sources)
  }

  if (IMAGE_EXT.test(name)) {
    return blockedReason(caps?.image_sources)
  }

  return ''
}
