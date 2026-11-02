/**
 * Voice picker for the audio overview: choose a saved cast (who speaks, in which voice) or
 * the default voices, and edit your own casts. Profiles live behind `/onb-api/speaker-profiles`
 * (yours only); the voices on offer come from `/onb-api/podcasts/voices`, the speech service's list.
 */

import {
  Button,
  Codicon,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useState } from 'react'

import { harvisApi } from './api'
import { errorText } from './notebook-shared'

export const DEFAULT_PROFILE = 'default-duo'
const AUTO = '__default__'
const MAX_SPEAKERS = 4

export interface Voice {
  id: string
  name: string
  gender: string
  language: string
}

export interface CastMember {
  name: string
  voice_id: string
}

export interface SpeakerProfile {
  id: string
  name: string
  builtin?: boolean
  speakers: CastMember[]
}

export const profilesKey = ['harvis', 'notebooks', 'speaker-profiles'] as const
const voicesKey = ['harvis', 'notebooks', 'podcast-voices'] as const

/** Your saved casts after the built-in one. A failed load just leaves the default voices. */
export function useSpeakerProfiles() {
  return useQuery({
    queryFn: () => harvisApi<SpeakerProfile[]>('/onb-api/speaker-profiles'),
    queryKey: profilesKey,
    retry: false
  })
}

/** The cast to send with a generate request, or undefined for the default voices. */
export function castFor(profiles: SpeakerProfile[] | undefined, id: string): CastMember[] | undefined {
  const profile = id === DEFAULT_PROFILE ? undefined : profiles?.find(p => p.id === id && !p.builtin)

  return profile?.speakers.map(s => ({ name: s.name, voice_id: s.voice_id }))
}

const voiceLabel = (v: Voice) => `${v.name} (${v.gender}, ${v.language})`

function VoiceEditor({
  existing,
  onClose,
  onSaved
}: {
  existing: SpeakerProfile | undefined
  onClose: () => void
  onSaved: (id: string) => void
}) {
  const queryClient = useQueryClient()
  const voices = useQuery({
    queryFn: () => harvisApi<{ voices: Voice[] }>('/onb-api/podcasts/voices').then(r => r.voices ?? []),
    queryKey: voicesKey,
    staleTime: Infinity
  })

  const [name, setName] = useState(existing?.name ?? '')

  const [cast, setCast] = useState<CastMember[]>(
    existing?.speakers.map(s => ({ name: s.name, voice_id: s.voice_id })) ?? [
      { name: 'Alex', voice_id: AUTO },
      { name: 'Sam', voice_id: AUTO }
    ]
  )

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const change = (i: number, patch: Partial<CastMember>) =>
    setCast(list => list.map((m, j) => (j === i ? { ...m, ...patch } : m)))

  const send = async (method: 'DELETE' | 'POST' | 'PUT') => {
    setBusy(true)
    setError('')

    try {
      const url = `/onb-api/speaker-profiles${existing && method !== 'POST' ? `/${existing.id}` : ''}`

      const made = await harvisApi<{ id?: string }>(url, {
        method,
        ...(method === 'DELETE' ? {} : { body: JSON.stringify({ name, speakers: cast }) })
      })

      await queryClient.invalidateQueries({ queryKey: profilesKey })
      onSaved(method === 'DELETE' ? DEFAULT_PROFILE : (made.id ?? DEFAULT_PROFILE))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-(--ui-border) p-2">
      <Input
        aria-label="Voice set name"
        className="h-7 text-xs"
        maxLength={80}
        onChange={e => setName(e.target.value)}
        placeholder="Name this set of voices"
        value={name}
      />
      {cast.map((m, i) => (
        <div className="flex items-center gap-1.5" key={i}>
          <Input
            aria-label={`Speaker ${i + 1} name`}
            className="h-7 w-28 text-xs"
            maxLength={40}
            onChange={e => change(i, { name: e.target.value })}
            value={m.name}
          />
          <Select onValueChange={v => change(i, { voice_id: v })} value={m.voice_id || AUTO}>
            <SelectTrigger aria-label={`Speaker ${i + 1} voice`} className="h-7 w-52 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={AUTO}>Automatic</SelectItem>
              {(voices.data ?? []).map(v => (
                <SelectItem key={v.id} value={v.id}>
                  {voiceLabel(v)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {cast.length > 1 && (
            <Button
              aria-label={`Remove speaker ${i + 1}`}
              onClick={() => setCast(list => list.filter((_, j) => j !== i))}
              size="sm"
              variant="ghost"
            >
              <Codicon name="close" size="0.8rem" />
            </Button>
          )}
        </div>
      ))}
      {voices.error && <p className="text-xs text-destructive">{errorText(voices.error)}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex flex-wrap items-center gap-1.5">
        {cast.length < MAX_SPEAKERS && (
          <Button onClick={() => setCast(list => [...list, { name: '', voice_id: AUTO }])} size="sm" variant="outline">
            <Codicon name="add" size="0.8rem" /> Add speaker
          </Button>
        )}
        <Button disabled={busy || !name.trim()} onClick={() => void send(existing ? 'PUT' : 'POST')} size="sm">
          Save voices
        </Button>
        {existing && (
          <Button disabled={busy} onClick={() => void send('DELETE')} size="sm" variant="outline">
            Delete
          </Button>
        )}
        <Button onClick={onClose} size="sm" variant="ghost">
          Cancel
        </Button>
      </div>
    </div>
  )
}

export function VoicePicker({
  onChange,
  profiles,
  value
}: {
  onChange: (id: string) => void
  profiles: SpeakerProfile[] | undefined
  value: string
}) {
  const [editing, setEditing] = useState<'edit' | 'new' | null>(null)
  const mine = (profiles ?? []).filter(p => !p.builtin)
  const selected = mine.find(p => p.id === value)

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <Select onValueChange={onChange} value={selected ? value : DEFAULT_PROFILE}>
          <SelectTrigger aria-label="Voices" className="h-7 w-40 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={DEFAULT_PROFILE}>Default voices</SelectItem>
            {mine.map(p => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selected && (
          <Button onClick={() => setEditing('edit')} size="sm" variant="outline">
            Edit voices
          </Button>
        )}
        <Button onClick={() => setEditing('new')} size="sm" variant="outline">
          <Codicon name="add" size="0.8rem" /> New voices
        </Button>
      </div>
      {editing && (
        <VoiceEditor
          existing={editing === 'edit' ? selected : undefined}
          key={editing === 'edit' ? selected?.id : 'new'}
          onClose={() => setEditing(null)}
          onSaved={id => {
            setEditing(null)
            onChange(id)
          }}
        />
      )}
    </div>
  )
}
