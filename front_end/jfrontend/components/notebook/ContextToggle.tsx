'use client'

import * as React from 'react'
import { EyeOff, Lightbulb, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { ContextMode } from '@/stores/openNotebookUiStore'

interface ContextToggleProps {
  mode: ContextMode
  hasInsights?: boolean // For sources - determines if 'insights' mode is available
  onChange: (mode: ContextMode) => void
  className?: string
}

const MODE_CONFIG = {
  off: {
    icon: EyeOff,
    label: 'Not included in chat',
    color: 'text-muted-foreground',
    bgColor: 'hover:bg-muted',
  },
  insights: {
    icon: Lightbulb,
    label: 'Insights only',
    color: 'text-amber-500',
    bgColor: 'hover:bg-amber-500/10',
  },
  full: {
    icon: FileText,
    label: 'Full content',
    color: 'text-primary',
    bgColor: 'hover:bg-primary/10',
  },
} as const

export function ContextToggle({
  mode,
  hasInsights = false,
  onChange,
  className,
}: ContextToggleProps) {
  const config = MODE_CONFIG[mode]
  const Icon = config.icon

  // Determine available modes based on whether item has insights
  const availableModes: ContextMode[] = hasInsights
    ? ['off', 'insights', 'full']
    : ['off', 'full']

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation() // Prevent card click

    // Cycle to next mode
    const currentIndex = availableModes.indexOf(mode)
    const nextIndex = (currentIndex + 1) % availableModes.length
    onChange(availableModes[nextIndex])
  }

  return (
    <Tooltip content={<span>{config.label}<br /><span className="text-muted-foreground">Click to cycle</span></span>} side="left">
      <Button
        variant="ghost"
        size="sm"
        className={cn(
          'h-8 w-8 p-0 transition-colors',
          config.bgColor,
          className
        )}
        onClick={handleClick}
      >
        <Icon className={cn('h-4 w-4', config.color)} />
      </Button>
    </Tooltip>
  )
}

// Helper to get context description
export function getContextModeLabel(mode: ContextMode): string {
  return MODE_CONFIG[mode].label
}

// Helper to get the icon component
export function getContextModeIcon(mode: ContextMode) {
  return MODE_CONFIG[mode].icon
}
