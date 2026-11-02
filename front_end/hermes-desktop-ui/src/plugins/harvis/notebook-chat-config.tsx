/**
 * Configure chat: how this notebook answers (style or persona, length, language). Stored on the notebook
 * (`/chat-config`); the grounding rules always come first, so a persona changes tone and format only.
 */

import {
  Button,
  Codicon,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  SegmentedControl,
  Textarea,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'

import { type ChatConfig, chatConfigKey, DEFAULT_CHAT_CONFIG, fetchChatConfig, saveChatConfig } from './notebook-stream'
import { errorText } from './notebook-shared'

export const MAX_PERSONA = 2000
export const MAX_LANGUAGE = 40

const STYLES: { id: ChatConfig['style']; label: string; hint: string }[] = [
  { hint: 'Plain, direct answers.', id: 'default', label: 'Default' },
  {
    hint: 'A patient tutor: simple wording, checks your understanding.',
    id: 'learning_guide',
    label: 'Learning guide'
  },
  { hint: 'Conclusion first, then the evidence, and where the sources are thin.', id: 'analyst', label: 'Analyst' },
  { hint: 'Describe how you want it to answer.', id: 'custom', label: 'Custom' }
]

const LENGTHS: { id: ChatConfig['length']; label: string }[] = [
  { id: 'shorter', label: 'Shorter' },
  { id: 'default', label: 'Default' },
  { id: 'longer', label: 'Longer' }
]

const LANGUAGES = ['English', 'Spanish', 'French', 'German', 'Portuguese', 'Italian', 'Chinese', 'Japanese', 'Korean']

/** The body to PUT: a blank persona or language clears it; the persona only matters for the Custom style. */
export function configBody(draft: ChatConfig): ChatConfig {
  return {
    length: draft.length,
    output_language: draft.output_language?.trim().slice(0, MAX_LANGUAGE) || null,
    persona: draft.persona?.trim().slice(0, MAX_PERSONA) || null,
    style: draft.style
  }
}

export function ChatConfigButton({ notebookId }: { notebookId: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<ChatConfig>(DEFAULT_CHAT_CONFIG)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const config = useQuery({
    enabled: open,
    queryFn: () => fetchChatConfig(notebookId),
    queryKey: chatConfigKey(notebookId),
    retry: false,
    staleTime: 0
  })

  useEffect(() => {
    if (open && config.data) {
      setDraft(config.data)
    }
  }, [open, config.data])

  const save = async () => {
    setBusy(true)
    setError('')

    try {
      const saved = await saveChatConfig(notebookId, configBody(draft))
      queryClient.setQueryData(chatConfigKey(notebookId), saved)
      setOpen(false)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const style = STYLES.find(s => s.id === draft.style)

  return (
    <>
      <Button
        aria-label="Configure chat"
        onClick={() => setOpen(true)}
        size="sm"
        title="Configure chat"
        variant="ghost"
      >
        <Codicon name="settings-gear" size="0.8rem" />
      </Button>
      <Dialog onOpenChange={next => !busy && setOpen(next)} open={open}>
        <DialogContent bodyClassName="flex flex-col gap-3 p-4" className="max-w-md">
          <DialogHeader>
            <DialogTitle>Configure chat</DialogTitle>
            <DialogDescription>
              Changes how this notebook answers. It still answers only from your sources and cites them.
            </DialogDescription>
          </DialogHeader>
          {config.isLoading ? (
            <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
          ) : config.error ? (
            <p className="text-xs text-destructive">{errorText(config.error)}</p>
          ) : (
            <>
              <div className="space-y-1">
                <p className="text-xs font-medium">Style</p>
                <SegmentedControl
                  onChange={id => setDraft(d => ({ ...d, style: id }))}
                  options={STYLES}
                  value={draft.style}
                />
                <p className="text-xs text-(--ui-text-tertiary)">{style?.hint}</p>
              </div>
              {draft.style === 'custom' && (
                <div className="space-y-1">
                  <label className="text-xs font-medium" htmlFor="chat-persona">
                    Persona
                  </label>
                  <Textarea
                    className="min-h-24 text-sm"
                    id="chat-persona"
                    maxLength={MAX_PERSONA}
                    onChange={e => setDraft(d => ({ ...d, persona: e.target.value }))}
                    placeholder="For example: answer like a skeptical reviewer who checks every claim."
                    value={draft.persona ?? ''}
                  />
                  <p className="text-right text-xs text-(--ui-text-tertiary)">
                    {(draft.persona ?? '').length}/{MAX_PERSONA}
                  </p>
                </div>
              )}
              <div className="space-y-1">
                <p className="text-xs font-medium">Length</p>
                <SegmentedControl
                  onChange={id => setDraft(d => ({ ...d, length: id }))}
                  options={LENGTHS}
                  value={draft.length}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium" htmlFor="chat-language">
                  Answer language
                </label>
                <Input
                  id="chat-language"
                  list="chat-language-options"
                  maxLength={MAX_LANGUAGE}
                  onChange={e => setDraft(d => ({ ...d, output_language: e.target.value }))}
                  placeholder="Same as the question"
                  value={draft.output_language ?? ''}
                />
                <datalist id="chat-language-options">
                  {LANGUAGES.map(l => (
                    <option key={l} value={l} />
                  ))}
                </datalist>
              </div>
            </>
          )}
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-1.5">
            <Button disabled={busy} onClick={() => setOpen(false)} size="sm" variant="ghost">
              Cancel
            </Button>
            <Button disabled={busy || !config.data} onClick={() => void save()} size="sm">
              {busy ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
