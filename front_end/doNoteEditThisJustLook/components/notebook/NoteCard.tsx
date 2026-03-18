'use client'

import * as React from 'react'
import {
  StickyNote,
  Sparkles,
  FileText,
  Highlighter,
  Pin,
  MoreVertical,
  Trash2,
  Edit2,
  Copy,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { ContextToggle } from './ContextToggle'
import { cn } from '@/lib/utils'
import { ContextMode } from '@/stores/openNotebookUiStore'
import { NotebookNote } from '@/stores/notebookStore'

// Note type icons mapping
const NOTE_TYPE_ICONS: Record<string, React.ElementType> = {
  user_note: StickyNote,
  ai_note: Sparkles,
  summary: FileText,
  highlight: Highlighter,
}

// Note type colors
const NOTE_TYPE_COLORS: Record<string, string> = {
  user_note: 'text-blue-500 bg-blue-500/10',
  ai_note: 'text-purple-500 bg-purple-500/10',
  summary: 'text-green-500 bg-green-500/10',
  highlight: 'text-yellow-500 bg-yellow-500/10',
}

interface NoteCardProps {
  note: NotebookNote
  contextMode?: ContextMode
  onContextModeChange?: (mode: ContextMode) => void
  onDelete?: () => void
  onEdit?: () => void
  onTogglePin?: () => void
  onCopy?: () => void
  onClick?: () => void
  showContextToggle?: boolean
  className?: string
}

export function NoteCard({
  note,
  contextMode = 'full',
  onContextModeChange,
  onDelete,
  onEdit,
  onTogglePin,
  onCopy,
  onClick,
  showContextToggle = true,
  className,
}: NoteCardProps) {
  const TypeIcon = NOTE_TYPE_ICONS[note.type] || StickyNote
  const typeColor = NOTE_TYPE_COLORS[note.type] || 'text-muted-foreground bg-muted'

  // Format date
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined,
    })
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(note.content)
    onCopy?.()
  }

  return (
    <div
      className={cn(
        'group relative p-3 border rounded-lg transition-all cursor-pointer card-hover',
        note.is_pinned && 'ring-1 ring-yellow-500/50 bg-yellow-500/5',
        className
      )}
      onClick={onClick}
    >
      {/* Header Row */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {/* Type Badge */}
          <Badge variant="secondary" className={cn('text-xs', typeColor)}>
            <TypeIcon className="h-3 w-3 mr-1" />
            {note.type.replace('_', ' ')}
          </Badge>

          {/* Pinned indicator */}
          {note.is_pinned && (
            <Pin className="h-3 w-3 text-yellow-500 fill-yellow-500" />
          )}

          {/* Title if exists */}
          {note.title && (
            <h4 className="text-sm font-medium truncate">{note.title}</h4>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1">
          {showContextToggle && onContextModeChange && (
            <ContextToggle
              mode={contextMode}
              hasInsights={false}
              onChange={onContextModeChange}
              className="opacity-0 group-hover:opacity-100"
            />
          )}

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {onEdit && (
                <DropdownMenuItem
                  onSelect={(e) => {
                    e.preventDefault()
                    onEdit()
                  }}
                >
                  <Edit2 className="h-4 w-4 mr-2" />
                  Edit
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault()
                  handleCopy()
                }}
              >
                <Copy className="h-4 w-4 mr-2" />
                Copy
              </DropdownMenuItem>
              {onTogglePin && (
                <DropdownMenuItem
                  onSelect={(e) => {
                    e.preventDefault()
                    onTogglePin()
                  }}
                >
                  <Pin className={cn('h-4 w-4 mr-2', note.is_pinned && 'fill-current')} />
                  {note.is_pinned ? 'Unpin' : 'Pin'}
                </DropdownMenuItem>
              )}
              {onDelete && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onSelect={(e) => {
                      e.preventDefault()
                      onDelete()
                    }}
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    Delete
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Content Preview */}
      <p className="text-sm text-muted-foreground line-clamp-3 mb-2">
        {note.content}
      </p>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{formatDate(note.created_at)}</span>
        {note.source_meta?.source_ids?.length > 0 && (
          <span className="flex items-center gap-1">
            <FileText className="h-3 w-3" />
            {note.source_meta.source_ids.length} sources
          </span>
        )}
      </div>
    </div>
  )
}

// Compact version for lists
export function NoteCardCompact({
  note,
  onClick,
}: {
  note: NotebookNote
  onClick?: () => void
}) {
  const TypeIcon = NOTE_TYPE_ICONS[note.type] || StickyNote

  return (
    <div
      className="flex items-start gap-2 p-2 rounded-lg cursor-pointer transition-colors hover:bg-muted"
      onClick={onClick}
    >
      <TypeIcon className="h-4 w-4 text-muted-foreground flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-sm line-clamp-2">{note.content}</p>
        <span className="text-xs text-muted-foreground">
          {new Date(note.created_at).toLocaleDateString()}
        </span>
      </div>
      {note.is_pinned && (
        <Pin className="h-3 w-3 text-yellow-500 fill-yellow-500 flex-shrink-0" />
      )}
    </div>
  )
}
