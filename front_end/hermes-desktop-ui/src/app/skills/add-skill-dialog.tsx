import { useRef, useState } from 'react'

import { createSkill } from '@/api/skills'
import type { ProfileScope } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { notify } from '@/store/notifications'

const MAX_CONTENT = 20000

const PLACEHOLDER = `# Weekly report

Use when I ask for my weekly report.

1. Collect what I worked on since Monday.
2. Group it by project.
3. Keep it under a page.`

interface AddSkillButtonProps {
  onAdded: () => void
  profile?: ProfileScope
  size?: 'sm' | 'xs'
}

/** "Add skill": paste a SKILL.md or upload one. Adding it switches it on — the person adding it vouches for it. */
export function AddSkillButton({ onAdded, profile, size = 'xs' }: AddSkillButtonProps) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const close = () => {
    setOpen(false)
    setName('')
    setContent('')
    setError('')
  }

  const loadFile = async (file: File | undefined) => {
    if (!file) {
      return
    }

    if (file.size > MAX_CONTENT * 4) {
      setError('That file is too big for a skill.')

      return
    }

    setContent((await file.text()).slice(0, MAX_CONTENT))
    setError('')
  }

  const save = async () => {
    setSaving(true)
    setError('')

    try {
      const res = await createSkill(content, name.trim(), profile)
      notify({ kind: 'success', message: res.message, title: 'Skill added' })
      onAdded()
      close()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Button onClick={() => setOpen(true)} size={size} variant="outline">
        Add skill
      </Button>
      <Dialog onOpenChange={next => !next && close()} open={open}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Add a skill</DialogTitle>
            <DialogDescription>
              Write instructions Harvis should follow for a kind of task, or upload a SKILL.md. It is on as soon as you
              add it.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Input
              aria-label="Skill name"
              onChange={e => setName(e.target.value)}
              placeholder="Name (optional — taken from the file's name: line or first heading)"
              value={name}
            />
            <Textarea
              aria-label="Skill instructions"
              className="h-56 font-mono text-xs"
              maxLength={MAX_CONTENT}
              onChange={e => setContent(e.target.value)}
              placeholder={PLACEHOLDER}
              value={content}
            />
            <input
              accept=".md,.markdown,.txt,text/markdown,text/plain"
              className="hidden"
              onChange={e => {
                void loadFile(e.target.files?.[0])
                e.target.value = ''
              }}
              ref={fileRef}
              type="file"
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button onClick={() => fileRef.current?.click()} size="sm" variant="ghost">
              Upload SKILL.md
            </Button>
            <Button disabled={saving || !content.trim()} onClick={() => void save()} size="sm">
              {saving ? 'Adding…' : 'Add skill'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
