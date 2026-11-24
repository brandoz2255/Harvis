/** Drop or pick any number of files and upload each one as a notebook source, one after another. */

import { cn, Codicon } from '@hermes/plugin-sdk'
import { useRef, useState } from 'react'

import { harvisApi } from './api'
import { fileBlockedReason, type NotebookCapabilities, useCapabilities } from './notebook-capabilities'
import { errorText } from './notebook-shared'
import { UPLOAD_ACCEPT, UPLOAD_HINT } from './notebook-source-meta'

export interface UploadResult {
  added: string[]
  refused: { name: string; reason: string }[]
}

/** Uploads one at a time so a big batch doesn't swamp the reader; a refused file never stops the rest. */
export async function uploadFiles(
  notebookId: string,
  files: readonly File[],
  caps?: NotebookCapabilities,
  onProgress?: (done: number) => void
): Promise<UploadResult> {
  const result: UploadResult = { added: [], refused: [] }

  for (const [i, file] of files.entries()) {
    const why = fileBlockedReason(file.name, caps)

    if (why) {
      result.refused.push({ name: file.name, reason: why })
    } else {
      const form = new FormData()
      form.append('file', file)

      try {
        await harvisApi(`/api/notebooks/${notebookId}/sources/upload`, { body: form, method: 'POST' })
        result.added.push(file.name)
      } catch (err) {
        result.refused.push({ name: file.name, reason: errorText(err) })
      }
    }

    onProgress?.(i + 1)
  }

  return result
}

export function SourceDropZone({
  compact,
  notebookId,
  onAdded
}: {
  compact?: boolean
  notebookId: string
  /** Called once a batch finishes with at least one file added; `clean` is true when none were refused. */
  onAdded: (clean: boolean) => void
}) {
  const caps = useCapabilities()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState<null | { done: number; total: number }>(null)
  const [result, setResult] = useState<null | UploadResult>(null)

  const send = async (list: FileList | null) => {
    const files = Array.from(list ?? [])

    if (files.length === 0 || progress) {
      return
    }

    setResult(null)
    setProgress({ done: 0, total: files.length })
    const done = await uploadFiles(notebookId, files, caps, n => setProgress({ done: n, total: files.length }))
    setProgress(null)
    setResult(done)

    if (done.added.length > 0) {
      onAdded(done.refused.length === 0)
    }
  }

  return (
    <div className="space-y-1.5">
      <input
        accept={UPLOAD_ACCEPT}
        className="hidden"
        data-testid="source-file-input"
        multiple
        onChange={e => {
          void send(e.target.files)
          e.target.value = ''
        }}
        ref={inputRef}
        type="file"
      />
      <div
        aria-label="Drop files here or choose files to upload"
        className={cn(
          'cursor-pointer rounded-xl border-2 border-dashed text-center transition-colors outline-none focus-visible:border-(--ui-accent)',
          compact ? 'px-3 py-4' : 'px-6 py-8',
          dragging ? 'border-(--ui-accent) bg-(--ui-bg-tertiary)' : 'hover:bg-(--ui-bg-tertiary)'
        )}
        data-testid="source-drop-zone"
        onClick={() => inputRef.current?.click()}
        onDragLeave={() => setDragging(false)}
        onDragOver={e => {
          e.preventDefault()
          setDragging(true)
        }}
        onDrop={e => {
          e.preventDefault()
          setDragging(false)
          void send(e.dataTransfer.files)
        }}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            inputRef.current?.click()
          }
        }}
        role="button"
        tabIndex={0}
      >
        <Codicon className="text-(--ui-text-tertiary)" name="cloud-upload" size={compact ? '1rem' : '1.5rem'} />
        <p className="mt-1 text-sm font-medium">
          {progress ? `Uploading ${progress.done + 1} of ${progress.total}…` : 'Drop files here, or click to choose'}
        </p>
        <p className="mt-0.5 text-xs text-(--ui-text-tertiary)">{UPLOAD_HINT}</p>
      </div>
      {result && result.added.length > 0 && (
        <p className="text-xs text-(--ui-text-tertiary)">
          Added {result.added.length} file{result.added.length === 1 ? '' : 's'}; they are being read now.
        </p>
      )}
      {result && result.refused.length > 0 && (
        <ul className="space-y-0.5 text-xs text-destructive">
          {result.refused.map(r => (
            <li key={r.name}>
              {r.name}: {r.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
