'use client'

import * as React from 'react'
import {
  FileText,
  Globe,
  File,
  Headphones,
  Youtube,
  Image as ImageIcon,
  Clock,
  Loader2,
  CheckCircle,
  AlertCircle,
  MoreVertical,
  Trash2,
  RefreshCw,
  Wand2,
  ExternalLink,
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
import { NotebookSource } from '@/stores/notebookStore'

// Source type icons mapping
const SOURCE_TYPE_ICONS: Record<string, React.ElementType> = {
  pdf: File,
  text: FileText,
  url: Globe,
  markdown: FileText,
  doc: File,
  transcript: FileText,
  audio: Headphones,
  youtube: Youtube,
  image: ImageIcon,
}

// Status configuration
const STATUS_CONFIG = {
  pending: {
    icon: Clock,
    label: 'Pending',
    color: 'text-muted-foreground',
    bgColor: 'bg-muted',
  },
  processing: {
    icon: Loader2,
    label: 'Processing',
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
    animate: true,
  },
  ready: {
    icon: CheckCircle,
    label: 'Ready',
    color: 'text-green-500',
    bgColor: 'bg-green-500/10',
  },
  error: {
    icon: AlertCircle,
    label: 'Failed',
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
}

interface SourceCardProps {
  source: NotebookSource
  contextMode?: ContextMode
  onContextModeChange?: (mode: ContextMode) => void
  onDelete?: () => void
  onRetry?: () => void
  onTransform?: () => void
  onView?: () => void
  isSelected?: boolean
  onClick?: () => void
  showContextToggle?: boolean
  className?: string
}

export function SourceCard({
  source,
  contextMode = 'full',
  onContextModeChange,
  onDelete,
  onRetry,
  onTransform,
  onView,
  isSelected,
  onClick,
  showContextToggle = true,
  className,
}: SourceCardProps) {
  const TypeIcon = SOURCE_TYPE_ICONS[source.type] || FileText
  const statusConfig = STATUS_CONFIG[source.status]
  const StatusIcon = statusConfig.icon

  const handleCardClick = () => {
    if (onClick) {
      onClick()
    } else if (onView && source.status === 'ready') {
      onView()
    }
  }

  // Check if source has insights (for context toggle)
  const hasInsights = source.chunk_count > 0

  return (
    <div
      className={cn(
        'group relative p-3 border rounded-lg transition-all cursor-pointer card-hover',
        isSelected && 'ring-2 ring-primary bg-primary/5',
        className
      )}
      onClick={handleCardClick}
    >
      {/* Header Row */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {/* Type Icon */}
          <div
            className={cn(
              'flex items-center justify-center w-8 h-8 rounded-lg',
              source.type === 'youtube' ? 'bg-red-500/10' : 'bg-muted'
            )}
          >
            <TypeIcon
              className={cn(
                'h-4 w-4',
                source.type === 'youtube' ? 'text-red-500' : 'text-muted-foreground'
              )}
            />
          </div>

          {/* Title */}
          <div className="flex-1 min-w-0">
            <h4 className="text-sm font-medium truncate">
              {source.title || source.original_filename || 'Untitled'}
            </h4>
            <p className="text-xs text-muted-foreground truncate">
              {source.type}
              {source.chunk_count > 0 && ` • ${source.chunk_count} chunks`}
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1">
          {showContextToggle && onContextModeChange && (
            <ContextToggle
              mode={contextMode}
              hasInsights={hasInsights}
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
              {onView && source.status === 'ready' && (
                <DropdownMenuItem
                  onSelect={(e) => {
                    e.preventDefault()
                    onView()
                  }}
                >
                  <ExternalLink className="h-4 w-4 mr-2" />
                  View Source
                </DropdownMenuItem>
              )}
              {onTransform && source.status === 'ready' && (
                <DropdownMenuItem
                  onSelect={(e) => {
                    e.preventDefault()
                    onTransform()
                  }}
                >
                  <Wand2 className="h-4 w-4 mr-2" />
                  Transform with AI
                </DropdownMenuItem>
              )}
              {onRetry && source.status === 'error' && (
                <DropdownMenuItem
                  onSelect={(e) => {
                    e.preventDefault()
                    onRetry()
                  }}
                >
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Retry Processing
                </DropdownMenuItem>
              )}
              {(onView || onTransform || onRetry) && onDelete && <DropdownMenuSeparator />}
              {onDelete && (
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
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Status Row */}
      <div className="flex items-center gap-2">
        <Badge
          variant="secondary"
          className={cn('text-xs', statusConfig.bgColor, statusConfig.color)}
        >
          <StatusIcon
            className={cn('h-3 w-3 mr-1', statusConfig.animate && 'animate-spin')}
          />
          {statusConfig.label}
        </Badge>

        {source.status === 'error' && source.error_message && (
          <span className="text-xs text-red-500 truncate flex-1">
            {source.error_message}
          </span>
        )}
      </div>
    </div>
  )
}

// Compact version for lists
export function SourceCardCompact({
  source,
  isSelected,
  onClick,
}: {
  source: NotebookSource
  isSelected?: boolean
  onClick?: () => void
}) {
  const TypeIcon = SOURCE_TYPE_ICONS[source.type] || FileText
  const statusConfig = STATUS_CONFIG[source.status]

  return (
    <div
      className={cn(
        'flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-colors',
        'hover:bg-muted',
        isSelected && 'bg-primary/10 ring-1 ring-primary'
      )}
      onClick={onClick}
    >
      <TypeIcon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
      <span className="text-sm truncate flex-1">
        {source.title || source.original_filename || 'Untitled'}
      </span>
      <statusConfig.icon
        className={cn(
          'h-3 w-3 flex-shrink-0',
          statusConfig.color,
          statusConfig.animate && 'animate-spin'
        )}
      />
    </div>
  )
}

// Also export as default for backward compatibility
export default SourceCard
