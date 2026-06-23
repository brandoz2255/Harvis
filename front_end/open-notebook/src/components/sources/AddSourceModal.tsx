'use client'

import { useRef, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import {
  Upload,
  Link2,
  HardDrive,
  ClipboardPaste,
  Loader2,
  ArrowLeft,
  FilePlus2,
} from 'lucide-react'
import { useCreateSource, useFileUpload } from '@/lib/hooks/use-sources'
import { useToast } from '@/lib/hooks/use-toast'
import { SourceWebSearch } from './SourceWebSearch'
import { cn } from '@/lib/utils'

// Cosmetic source cap shown in the capacity bar (mirrors NotebookLM's 50). The
// backend doesn't hard-cap, so this is a soft visual indicator only.
const SOURCE_CAP = 50

interface AddSourceModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  notebookId: string
  /** Current source count for the capacity bar. */
  sourceCount?: number
  /** Fired after any source is added so the column can refresh. */
  onAdded?: () => void
  /** Opens the "link an existing source" flow (kept reachable from here). */
  onAddExisting?: () => void
}

type View = 'home' | 'website' | 'text'

export function AddSourceModal({
  open,
  onOpenChange,
  notebookId,
  sourceCount = 0,
  onAdded,
  onAddExisting,
}: AddSourceModalProps) {
  const createSource = useCreateSource()
  const fileUpload = useFileUpload()
  const { toast } = useToast()

  const [view, setView] = useState<View>('home')
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)

  // website + text inputs
  const [urls, setUrls] = useState('')
  const [textTitle, setTextTitle] = useState('')
  const [textBody, setTextBody] = useState('')

  const fileInputRef = useRef<HTMLInputElement>(null)

  const reset = () => {
    setView('home')
    setUrls('')
    setTextTitle('')
    setTextBody('')
    setDragging(false)
    setBusy(false)
  }

  const handleOpenChange = (next: boolean) => {
    if (!next) reset()
    onOpenChange(next)
  }

  // ── ingest paths ───────────────────────────────────────────────────────────
  const uploadFiles = async (files: FileList | File[]) => {
    const list = Array.from(files)
    if (list.length === 0) return
    setBusy(true)
    for (const file of list) {
      try {
        await fileUpload.mutateAsync({ file, notebookId })
      } catch {
        // toast handled by the hook
      }
    }
    setBusy(false)
    onAdded?.()
  }

  const addWebsites = async () => {
    const parsed = urls
      .split(/[\n,\s]+/)
      .map((u) => u.trim())
      .filter(Boolean)
    if (parsed.length === 0) return
    setBusy(true)
    for (const url of parsed) {
      try {
        await createSource.mutateAsync({ type: 'link', url, notebook_id: notebookId })
      } catch {
        // toast handled by the hook
      }
    }
    setBusy(false)
    onAdded?.()
    setUrls('')
    setView('home')
  }

  const addText = async () => {
    const content = textBody.trim()
    if (!content) return
    setBusy(true)
    try {
      await createSource.mutateAsync({
        type: 'text',
        content,
        title: textTitle.trim() || 'Pasted text',
        notebook_id: notebookId,
      })
      onAdded?.()
      setTextTitle('')
      setTextBody('')
      setView('home')
    } catch {
      // toast handled by the hook
    } finally {
      setBusy(false)
    }
  }

  const driveUnavailable = () =>
    toast({
      title: 'Google Drive isn’t available yet',
      description: 'Use Upload, a website link, or pasted text for now.',
    })

  // ── method buttons ───────────────────────────────────────────────────────────
  const METHODS = [
    { label: 'Upload files', icon: Upload, onClick: () => fileInputRef.current?.click() },
    { label: 'Websites', icon: Link2, onClick: () => setView('website') },
    { label: 'Drive', icon: HardDrive, onClick: driveUnavailable },
    { label: 'Copied text', icon: ClipboardPaste, onClick: () => setView('text') },
  ]

  const pct = Math.min(100, Math.round((sourceCount / SOURCE_CAP) * 100))

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        style={{ width: '600px', maxWidth: 'calc(100vw - 2rem)' }}
        className="p-0 overflow-hidden gap-0"
        showCloseButton={true}
      >
        {/* Accent top edge (Harvis primary) */}
        <div className="h-1 w-full bg-gradient-to-r from-primary/60 via-primary/25 to-transparent" />

        <div className="px-6 pt-5 pb-6">
          <DialogHeader className="items-center text-center">
            <DialogTitle className="text-2xl leading-tight font-semibold tracking-tight">
              Add sources
            </DialogTitle>
            <DialogDescription className="text-center max-w-xs">
              Sources let Harvis ground its answers in what matters to you.
            </DialogDescription>
          </DialogHeader>

          {view === 'home' && (
            <div className="mt-4 space-y-3">
              {/* Web search for new sources (Fast / Deep research) */}
              <SourceWebSearch notebookId={notebookId} onImported={onAdded} />

              {/* Drop zone */}
              <div
                role="button"
                tabIndex={0}
                onClick={() => fileInputRef.current?.click()}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && fileInputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragging(false)
                  if (e.dataTransfer.files?.length) uploadFiles(e.dataTransfer.files)
                }}
                className={cn(
                  'rounded-xl border-2 border-dashed px-6 py-8 text-center cursor-pointer transition outline-none',
                  dragging
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:border-primary/50 hover:bg-muted/40'
                )}
              >
                <FilePlus2 className="mx-auto h-7 w-7 text-muted-foreground" />
                <p className="mt-2 text-sm font-medium">
                  {busy ? 'Uploading…' : 'or drop your files'}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  pdf, images, docs, audio,{' '}
                  <span
                    className="text-foreground/70"
                    title="PDF, TXT, Markdown, DOCX, images, audio, video, EPUB, web links, YouTube"
                  >
                    and more
                  </span>
                </p>
              </div>

              {/* Four method buttons */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {METHODS.map((m) => (
                  <button
                    key={m.label}
                    type="button"
                    onClick={m.onClick}
                    className="flex items-center justify-center gap-2 rounded-full border border-border px-3 py-2 text-xs font-medium text-foreground/80 hover:bg-muted hover:text-foreground transition"
                  >
                    <m.icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{m.label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {view === 'website' && (
            <div className="mt-4 space-y-3">
              <BackRow onBack={() => setView('home')} label="Add website or YouTube links" />
              <textarea
                autoFocus
                value={urls}
                onChange={(e) => setUrls(e.target.value)}
                placeholder={'https://example.com/article\nhttps://youtube.com/watch?v=…\n(one per line)'}
                className="w-full h-32 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary resize-none"
              />
              <div className="flex justify-end">
                <Button onClick={addWebsites} disabled={busy || !urls.trim()} className="min-w-[96px]">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Add'}
                </Button>
              </div>
            </div>
          )}

          {view === 'text' && (
            <div className="mt-4 space-y-3">
              <BackRow onBack={() => setView('home')} label="Paste text as a source" />
              <input
                value={textTitle}
                onChange={(e) => setTextTitle(e.target.value)}
                placeholder="Title (optional)"
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
              />
              <textarea
                autoFocus
                value={textBody}
                onChange={(e) => setTextBody(e.target.value)}
                placeholder="Paste your text here…"
                className="w-full h-32 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary resize-none"
              />
              <div className="flex justify-end">
                <Button onClick={addText} disabled={busy || !textBody.trim()} className="min-w-[96px]">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Add'}
                </Button>
              </div>
            </div>
          )}

          {/* Capacity footer */}
          <div className="mt-6 pt-4 border-t border-border/60">
            <div className="mb-1.5 flex items-center justify-between text-xs text-muted-foreground">
              {onAddExisting ? (
                <button
                  type="button"
                  className="hover:text-foreground transition"
                  onClick={() => {
                    handleOpenChange(false)
                    onAddExisting()
                  }}
                >
                  Link an existing source
                </button>
              ) : (
                <span />
              )}
              <span className="tabular-nums">
                {sourceCount} / {SOURCE_CAP} sources
              </span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        </div>

        {/* Hidden file input for Upload files + drop zone click */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) uploadFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </DialogContent>
    </Dialog>
  )
}

function BackRow({ onBack, label }: { onBack: () => void; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={onBack}
        className="rounded-md p-1 hover:bg-muted transition"
        aria-label="Back"
      >
        <ArrowLeft className="h-4 w-4" />
      </button>
      <span className="text-sm font-medium">{label}</span>
    </div>
  )
}
