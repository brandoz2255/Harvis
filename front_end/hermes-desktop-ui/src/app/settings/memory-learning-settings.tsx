import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Brain, Loader2, Trash2, Wrench } from '@/lib/icons'
import { notifyError } from '@/store/notifications'

import { SKILLS_ROUTE } from '../routes'

import { addMemory, deleteMemory, fetchMemory, type LearnSettings, saveLearnSettings } from './harvis-api'
import { ListRow, ListRowSkeleton, Pill, SettingsContent, SettingsSection, ToggleRow } from './primitives'

const memoryKey = ['harvis', 'settings', 'memory'] as const

const SOURCE_LABEL: Record<string, string> = { 'hermes-chat': 'from a chat', manual: 'added by you' }

function when(iso: null | string) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : ''
}

/**
 * What Harvis remembers about you and what it learns from chats: saved facts it
 * reads before every answer, and skill drafts it writes after real work.
 */
export function MemoryLearningSettings({ onClose }: { onClose?: () => void }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [removing, setRemoving] = useState<null | number>(null)

  const memory = useQuery({ queryFn: fetchMemory, queryKey: memoryKey })
  const settings = memory.data?.settings
  const refresh = () => void queryClient.invalidateQueries({ queryKey: memoryKey })

  const toggle = async (patch: Partial<LearnSettings>) => {
    try {
      const next = await saveLearnSettings(patch)
      queryClient.setQueryData(memoryKey, old => (old ? { ...(old as object), settings: next } : old))
    } catch (err) {
      notifyError(err, 'Could not save the setting')
    }
  }

  const add = async () => {
    setSaving(true)

    try {
      await addMemory(draft.trim())
      setDraft('')
      refresh()
    } catch (err) {
      notifyError(err, 'Could not save the memory')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (id: number) => {
    setRemoving(id)

    try {
      await deleteMemory(id)
      refresh()
    } catch (err) {
      notifyError(err, 'Could not forget that')
    } finally {
      setRemoving(null)
    }
  }

  const entries = memory.data?.entries ?? []

  return (
    <SettingsContent>
      <SettingsSection icon={Brain} meta={memory.data?.model} title="Learning">
        <ToggleRow
          checked={settings?.memory ?? true}
          description="Harvis reads your saved facts before answering, and after each chat a small local model saves up to three new ones. Nothing leaves this machine."
          disabled={!settings}
          label="Remember things from chats"
          onChange={on => void toggle({ memory: on })}
        />
        <ToggleRow
          checked={settings?.skills ?? true}
          description="After a workspace run, or when you ask it to save a skill, Harvis writes a draft skill. Drafts stay switched off until you turn them on."
          disabled={!settings}
          label="Draft skills from finished work"
          onChange={on => void toggle({ skills: on })}
        />
        <ListRow
          action={
            <Button
              onClick={() => {
                onClose?.()
                navigate(SKILLS_ROUTE)
              }}
              size="sm"
              variant="outline"
            >
              <Wrench /> Open Skills
            </Button>
          }
          description="Review drafts in the Drafts category, edit them, and switch on the ones you want."
          title="Skill drafts"
        />
      </SettingsSection>

      <SettingsSection
        icon={Brain}
        meta={memory.data ? String(entries.length) : undefined}
        title="What Harvis remembers"
      >
        <form
          className="mb-2 flex gap-1.5"
          onSubmit={event => {
            event.preventDefault()

            if (draft.trim()) {
              void add()
            }
          }}
        >
          <Input
            aria-label="New memory"
            className="min-w-0 flex-1"
            maxLength={2000}
            onChange={event => setDraft(event.target.value)}
            placeholder="Tell Harvis something to remember, e.g. “I prefer short answers.”"
            value={draft}
          />
          <Button disabled={!draft.trim() || saving} type="submit">
            {saving && <Loader2 className="animate-spin" />}
            Remember
          </Button>
        </form>

        {memory.isLoading ? (
          <ListRowSkeleton />
        ) : memory.error ? (
          <p className="py-3 text-sm text-destructive">Could not load memories: {String(memory.error)}</p>
        ) : entries.length === 0 ? (
          <p className="py-6 text-center text-sm text-(--ui-text-tertiary)">
            Nothing yet. Chat normally and Harvis will pick up facts about you, or add one above.
          </p>
        ) : (
          <div className="divide-y">
            {entries.map(entry => (
              <ListRow
                action={
                  <Button
                    aria-label="Forget"
                    disabled={removing === entry.id}
                    onClick={() => void remove(entry.id)}
                    size="sm"
                    variant="ghost"
                  >
                    {removing === entry.id ? <Loader2 className="animate-spin" /> : <Trash2 />}
                    Forget
                  </Button>
                }
                description={
                  <span className="flex items-center gap-2">
                    <Pill>{SOURCE_LABEL[entry.source] ?? entry.source}</Pill>
                    {when(entry.created_at)}
                  </span>
                }
                key={entry.id}
                title={<span className="font-normal">{entry.content}</span>}
              />
            ))}
          </div>
        )}
      </SettingsSection>
    </SettingsContent>
  )
}
