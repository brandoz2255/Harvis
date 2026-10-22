import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useI18n } from '@/i18n'
import { exportFormats, type HarvisDocExportFormat, type HarvisDocKind } from '@/lib/harvis-doc'
import { exportHarvisDoc, saveBlob } from '@/lib/harvis-doc-export'
import { AlertCircle, Check, ChevronDown, Download, Loader2 } from '@/lib/icons'

const DONE_RESET_MS = 2_000

type ExportState =
  | { format: HarvisDocExportFormat['ext']; phase: 'converting' }
  | { format: HarvisDocExportFormat['ext']; message: string; phase: 'error' }
  | { phase: 'done' }
  | { phase: 'idle' }

interface DocExportControlProps {
  kind: HarvisDocKind
  source: string
  streaming: boolean
  title: string
}

/**
 * Download button for a document: the kind's main format up front and the rest
 * behind a chevron. Disabled while the document is still being written, since
 * an export of half a document is never what anyone wants. A failed export
 * keeps the preview and offers a retry of the same format.
 */
export function DocExportControl({ kind, source, streaming, title }: DocExportControlProps) {
  const { t } = useI18n()
  const copy = t.docPreview.export
  const formats = exportFormats(kind)
  const [state, setState] = useState<ExportState>({ phase: 'idle' })
  const mounted = useRef(true)
  const timer = useRef<null | number>(null)

  useEffect(() => {
    mounted.current = true

    return () => {
      mounted.current = false

      if (timer.current !== null) {
        window.clearTimeout(timer.current)
      }
    }
  }, [])

  const run = async (format: HarvisDocExportFormat['ext']) => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current)
    }

    setState({ format, phase: 'converting' })

    try {
      const { blob, filename } = await exportHarvisDoc(source, format, title)

      saveBlob(filename, blob)

      if (!mounted.current) {
        return
      }

      setState({ phase: 'done' })
      timer.current = window.setTimeout(() => mounted.current && setState({ phase: 'idle' }), DONE_RESET_MS)
    } catch (error) {
      if (mounted.current) {
        setState({ format, message: error instanceof Error ? error.message : String(error), phase: 'error' })
      }
    }
  }

  const primary = formats[0]
  const converting = state.phase === 'converting'
  const failed = state.phase === 'error' ? state : null
  const disabled = streaming || converting

  let label: string
  let icon = <Download className="size-3" />

  if (streaming) {
    label = copy.writing
  } else if (converting) {
    label = copy.converting
    icon = <Loader2 className="size-3 animate-spin motion-reduce:animate-none" />
  } else if (state.phase === 'done') {
    label = copy.downloaded
    icon = <Check className="size-3" />
  } else if (failed) {
    label = `${copy.failed} · ${copy.retry}`
    icon = <AlertCircle className="size-3 text-destructive" />
  } else {
    label = copy.download(primary.ext)
  }

  return (
    <div className="flex shrink-0 items-center" data-slot="doc-export">
      <Button
        className="h-6 gap-1 rounded-r-none px-2 text-[0.6875rem]"
        disabled={disabled}
        onClick={() => void run(failed?.format ?? primary.ext)}
        size="sm"
        title={failed?.message}
        variant="outline"
      >
        {icon}
        <span>{label}</span>
      </Button>
      {formats.length > 1 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              aria-label={copy.moreFormats}
              className="h-6 rounded-l-none border-l-0 px-1"
              disabled={disabled}
              size="sm"
              variant="outline"
            >
              <ChevronDown className="size-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40" sideOffset={6}>
            {formats.map(format => (
              <DropdownMenuItem key={format.ext} onSelect={() => void run(format.ext)}>
                <span className="min-w-0 flex-1 truncate">{format.label}</span>
                <span className="text-[0.625rem] text-muted-foreground">.{format.ext}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}
