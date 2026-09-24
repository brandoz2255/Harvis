/**
 * The create / edit form for one bot. Pure over a draft: the page owns the
 * draft and the save, this renders the fields and the live preview beside them.
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
  Switch,
  Textarea,
  useQuery
} from '@hermes/plugin-sdk'
import { useRef, useState } from 'react'

import { harvisApi } from './api'
import { BotAvatar } from './bot-avatar'
import type { BotDraft } from './bots-api'

const MAX_IMAGE_BYTES = 150_000
const MAX_STARTERS = 6
const QUICK_EMOJI = ['🤖', '🧠', '📚', '🔬', '🛠️', '🧭', '✍️', '🎯', '🦉', '🧪']

interface ModelOptions {
  model: string
  providers: { name: string; slug: string; models: string[] }[]
}

interface NotebookRow {
  id: string
  title: string
  emoji: null | string
}

export const modelOptionsKey = ['harvis', 'bots', 'model-options'] as const
export const notebookPickKey = ['harvis', 'bots', 'notebooks'] as const

export function BotForm({
  busy,
  draft,
  error,
  isNew,
  onChange,
  onDelete,
  onDuplicate,
  onSave
}: {
  busy: boolean
  draft: BotDraft
  error: string
  isNew: boolean
  onChange: (next: BotDraft) => void
  onDelete?: () => void
  onDuplicate?: () => void
  onSave: () => void
}) {
  const set = <K extends keyof BotDraft>(key: K, value: BotDraft[K]) => onChange({ ...draft, [key]: value })

  const models = useQuery({
    queryFn: () => harvisApi<ModelOptions>('/hermes-api/api/model/options'),
    queryKey: modelOptionsKey,
    staleTime: 60_000
  })
  const notebooks = useQuery({
    queryFn: () => harvisApi<{ notebooks: NotebookRow[] }>('/api/notebooks?limit=100').then(r => r.notebooks ?? []),
    queryKey: notebookPickKey,
    staleTime: 60_000
  })

  const canSave = draft.name.trim().length > 0 && !busy
  // One item per model name: the same model under two providers would give the Select duplicate values.
  const choices = [
    ...new Map(
      (models.data?.providers ?? []).flatMap(p => p.models.map(m => [m, { model: m, provider: p.name }] as const))
    ).values()
  ]

  return (
    <form
      className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_16rem]"
      onSubmit={event => {
        event.preventDefault()

        if (canSave) {
          onSave()
        }
      }}
    >
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold">{isNew ? 'New bot' : draft.name || 'Bot'}</h2>
          <p className="text-sm text-(--ui-text-tertiary)">
            A bot is a saved assistant: its instructions, model and knowledge apply to every message in a chat with it.
          </p>
        </div>

        <Field control label="Name" hint="Shown in the sidebar and at the top of its chats.">
          <Input
            maxLength={60}
            onChange={e => set('name', e.target.value)}
            placeholder="e.g. Paper Reader"
            required
            value={draft.name}
          />
        </Field>

        <Field label="Avatar">
          <AvatarPicker draft={draft} onChange={avatar => set('avatar', avatar)} />
        </Field>

        <Field control label="Description" hint="One line on what it is for.">
          <Input
            maxLength={300}
            onChange={e => set('description', e.target.value)}
            placeholder="Summarises research papers and answers questions about them"
            value={draft.description}
          />
        </Field>

        <Field control label="Instructions" hint="The system prompt. Who it is, how it answers, what it never does.">
          <Textarea
            className="min-h-40 font-mono text-xs"
            maxLength={12_000}
            onChange={e => set('instructions', e.target.value)}
            placeholder="You are a careful research assistant. Answer from the provided passages and cite them…"
            value={draft.instructions}
          />
        </Field>

        <Field label="Model" hint="From your connected providers. Empty means the default model.">
          <Select onValueChange={v => set('model', v === '__default__' ? '' : v)} value={draft.model || '__default__'}>
            <SelectTrigger aria-label="Model" className="w-full max-w-sm">
              <SelectValue placeholder="Default model" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__default__">
                Default model{models.data?.model ? ` (${models.data.model})` : ''}
              </SelectItem>
              {choices.map(c => (
                <SelectItem key={c.model} value={c.model}>
                  {c.model}
                  <span className="ml-2 text-xs text-(--ui-text-tertiary)">{c.provider}</span>
                </SelectItem>
              ))}
              {draft.model && !choices.some(c => c.model === draft.model) && (
                <SelectItem value={draft.model}>{draft.model}</SelectItem>
              )}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Knowledge" hint="Notebooks whose passages are pulled into every answer, with citations.">
          {notebooks.isLoading ? (
            <p className="text-xs text-(--ui-text-tertiary)">Loading notebooks…</p>
          ) : (notebooks.data ?? []).length === 0 ? (
            <p className="text-xs text-(--ui-text-tertiary)">No notebooks yet. Make one on the Notebooks page.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {(notebooks.data ?? []).map(nb => {
                const on = draft.notebook_ids.includes(nb.id)

                return (
                  <button
                    aria-pressed={on}
                    className={
                      on
                        ? 'inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-2.5 py-1 text-xs text-primary'
                        : 'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs text-(--ui-text-secondary) hover:bg-accent/60'
                    }
                    key={nb.id}
                    onClick={() =>
                      set(
                        'notebook_ids',
                        on ? draft.notebook_ids.filter(id => id !== nb.id) : [...draft.notebook_ids, nb.id].slice(0, 8)
                      )
                    }
                    type="button"
                  >
                    {nb.emoji ? <span>{nb.emoji}</span> : <Codicon name="notebook" size="0.75rem" />}
                    {nb.title}
                  </button>
                )
              })}
            </div>
          )}
        </Field>

        <Field label="Starter prompts" hint="Chips shown in an empty chat with this bot.">
          <StarterEditor onChange={list => set('starter_prompts', list)} prompts={draft.starter_prompts} />
        </Field>

        <Field label="Tools">
          <div className="space-y-2">
            <ToolRow
              checked={draft.tools.web_research}
              hint="May run a deep-research job when a message asks for one."
              label="Web research"
              onChange={v => set('tools', { ...draft.tools, web_research: v })}
            />
            <ToolRow
              checked={draft.tools.workspace_agent}
              hint="May start a workspace run with tools. Off keeps every reply in chat."
              label="Workspace agent"
              onChange={v => set('tools', { ...draft.tools, workspace_agent: v })}
            />
          </div>
        </Field>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <Button disabled={!canSave} type="submit">
            {busy ? 'Saving…' : isNew ? 'Create bot' : 'Save changes'}
          </Button>
          {onDuplicate && (
            <Button disabled={busy} onClick={onDuplicate} type="button" variant="outline">
              <Codicon name="copy" size="0.8rem" /> Duplicate
            </Button>
          )}
          {onDelete && (
            <Button className="ml-auto" disabled={busy} onClick={onDelete} type="button" variant="ghost">
              <Codicon name="trash" size="0.8rem" /> Delete
            </Button>
          )}
        </div>
      </div>

      <BotPreview draft={draft} notebooks={notebooks.data ?? []} />
    </form>
  )
}

/** A labelled field. Only a single-input field (`control`) is a <label>: wrapping
 *  a group of buttons in one would make a click on its text press the first button. */
function Field({
  children,
  control = false,
  hint,
  label
}: {
  children: React.ReactNode
  control?: boolean
  hint?: string
  label: string
}) {
  const Tag = control ? 'label' : 'div'

  return (
    <Tag aria-label={control ? undefined : label} className="block space-y-1.5" role={control ? undefined : 'group'}>
      <span className="block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="block text-xs text-(--ui-text-tertiary)">{hint}</span>}
    </Tag>
  )
}

function ToolRow({
  checked,
  hint,
  label,
  onChange
}: {
  checked: boolean
  hint: string
  label: string
  onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center gap-3">
      <Switch aria-label={label} checked={checked} onCheckedChange={onChange} />
      <span className="min-w-0">
        <span className="block text-sm">{label}</span>
        <span className="block text-xs text-(--ui-text-tertiary)">{hint}</span>
      </span>
    </div>
  )
}

function AvatarPicker({ draft, onChange }: { draft: BotDraft; onChange: (avatar: BotDraft['avatar']) => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [problem, setProblem] = useState('')

  const pickFile = (file: File | undefined) => {
    setProblem('')

    if (!file) {
      return
    }

    if (file.size > MAX_IMAGE_BYTES) {
      setProblem(`Image is ${Math.round(file.size / 1024)} KB; keep it under ${MAX_IMAGE_BYTES / 1000} KB.`)

      return
    }

    const reader = new FileReader()
    reader.onload = () => onChange({ image: String(reader.result) })
    reader.readAsDataURL(file)
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <BotAvatar avatar={draft.avatar} name={draft.name || 'Bot'} size="lg" />
      <div className="space-y-1.5">
        <div className="flex flex-wrap gap-1">
          {QUICK_EMOJI.map(e => (
            <button
              aria-label={`Use ${e}`}
              className={
                draft.avatar.emoji === e && !draft.avatar.image
                  ? 'grid size-7 place-items-center rounded-md bg-primary/15 text-base'
                  : 'grid size-7 place-items-center rounded-md text-base hover:bg-accent/60'
              }
              key={e}
              onClick={() => onChange({ emoji: e })}
              type="button"
            >
              {e}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <Input
            aria-label="Custom emoji"
            className="h-7 w-16 text-center"
            maxLength={8}
            onChange={e => onChange({ emoji: e.target.value })}
            placeholder="emoji"
            value={draft.avatar.image ? '' : (draft.avatar.emoji ?? '')}
          />
          <Button onClick={() => fileRef.current?.click()} size="sm" type="button" variant="outline">
            <Codicon name="file-media" size="0.8rem" /> Upload image
          </Button>
          <input
            accept="image/png,image/jpeg,image/gif,image/webp"
            className="hidden"
            onChange={e => pickFile(e.target.files?.[0])}
            ref={fileRef}
            type="file"
          />
        </div>
        {problem && <p className="text-xs text-destructive">{problem}</p>}
      </div>
    </div>
  )
}

function StarterEditor({ onChange, prompts }: { onChange: (list: string[]) => void; prompts: string[] }) {
  const [text, setText] = useState('')

  const add = () => {
    const t = text.trim()

    if (t && prompts.length < MAX_STARTERS) {
      onChange([...prompts, t.slice(0, 200)])
      setText('')
    }
  }

  return (
    <div className="space-y-1.5">
      {prompts.map((p, i) => (
        <div className="flex items-center gap-1.5" key={`${i}-${p}`}>
          <span className="min-w-0 flex-1 truncate rounded-md border px-2 py-1 text-xs">{p}</span>
          <button
            aria-label={`Remove starter ${i + 1}`}
            className="grid size-6 place-items-center rounded-sm text-(--ui-text-tertiary) hover:bg-accent/60 hover:text-foreground"
            onClick={() => onChange(prompts.filter((_, j) => j !== i))}
            type="button"
          >
            <Codicon name="close" size="0.75rem" />
          </button>
        </div>
      ))}
      {prompts.length < MAX_STARTERS && (
        <div className="flex gap-1.5">
          <Input
            aria-label="New starter prompt"
            className="h-8 min-w-0 flex-1"
            maxLength={200}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault()
                add()
              }
            }}
            placeholder="e.g. Summarise the attached paper in five bullets"
            value={text}
          />
          <Button disabled={!text.trim()} onClick={add} size="sm" type="button" variant="outline">
            Add
          </Button>
        </div>
      )}
    </div>
  )
}

/** What the empty chat will look like, kept in step with the fields. */
function BotPreview({ draft, notebooks }: { draft: BotDraft; notebooks: NotebookRow[] }) {
  const picked = notebooks.filter(nb => draft.notebook_ids.includes(nb.id))

  return (
    <aside className="hidden lg:block">
      <div className="sticky top-2 rounded-xl border bg-(--ui-surface-raised,var(--background)) p-4">
        <p className="mb-3 text-[0.65rem] tracking-wide text-(--ui-text-tertiary) uppercase">Preview</p>
        <div className="flex flex-col items-center gap-2 text-center">
          <BotAvatar avatar={draft.avatar} name={draft.name || 'Bot'} size="lg" />
          <p className="text-base font-semibold">{draft.name || 'Unnamed bot'}</p>
          {draft.description && <p className="text-xs text-(--ui-text-tertiary)">{draft.description}</p>}
        </div>
        <dl className="mt-4 space-y-1.5 text-xs">
          <div className="flex justify-between gap-2">
            <dt className="text-(--ui-text-tertiary)">Model</dt>
            <dd className="truncate">{draft.model || 'default'}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-(--ui-text-tertiary)">Knowledge</dt>
            <dd className="truncate">{picked.length ? picked.map(nb => nb.title).join(', ') : 'none'}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-(--ui-text-tertiary)">Tools</dt>
            <dd>
              {[draft.tools.web_research && 'research', draft.tools.workspace_agent && 'agent']
                .filter(Boolean)
                .join(', ') || 'chat only'}
            </dd>
          </div>
        </dl>
        {draft.starter_prompts.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {draft.starter_prompts.map((p, i) => (
              <span className="rounded-full border px-2.5 py-1 text-xs text-(--ui-text-secondary)" key={i}>
                {p}
              </span>
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}
