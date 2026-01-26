'use client'

import * as React from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface CollapsibleColumnProps {
  title: string
  icon: React.ReactNode
  isCollapsed: boolean
  onToggle: () => void
  children: React.ReactNode
  headerActions?: React.ReactNode
  className?: string
}

export function CollapsibleColumn({
  title,
  icon,
  isCollapsed,
  onToggle,
  children,
  headerActions,
  className,
}: CollapsibleColumnProps) {
  if (isCollapsed) {
    return (
      <div
        className={cn(
          'collapsible-column collapsed flex flex-col items-center py-4 bg-card border rounded-lg cursor-pointer',
          className
        )}
        onClick={onToggle}
      >
        <Tooltip content={`Expand ${title}`} side="right">
          <div className="flex flex-col items-center gap-3">
            <div className="text-muted-foreground">{icon}</div>
            <span
              className="text-xs font-medium text-muted-foreground"
              style={{
                writingMode: 'vertical-rl',
                textOrientation: 'mixed',
              }}
            >
              {title}
            </span>
            <ChevronRight className="h-4 w-4 text-muted-foreground mt-2" />
          </div>
        </Tooltip>
      </div>
    )
  }

  return (
    <Card className={cn('collapsible-column expanded h-full flex flex-col', className)}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <div className="flex items-center gap-2">
          <CardTitle className="text-sm font-medium">{title}</CardTitle>
        </div>
        <div className="flex items-center gap-1">
          {headerActions}
          <Tooltip content={`Collapse ${title}`} side="left">
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onToggle}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
          </Tooltip>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-4 pt-0">{children}</CardContent>
    </Card>
  )
}

// Simplified version for inline use
interface SimpleCollapsibleProps {
  isCollapsed: boolean
  onToggle: () => void
  collapsedIcon: React.ReactNode
  collapsedLabel: string
  children: React.ReactNode
  className?: string
}

export function SimpleCollapsible({
  isCollapsed,
  onToggle,
  collapsedIcon,
  collapsedLabel,
  children,
  className,
}: SimpleCollapsibleProps) {
  if (isCollapsed) {
    return (
      <div
        className={cn(
          'w-12 flex-shrink-0 flex flex-col items-center py-4 bg-card border rounded-lg cursor-pointer transition-all duration-150',
          className
        )}
        onClick={onToggle}
      >
        <div className="text-muted-foreground">{collapsedIcon}</div>
        <span
          className="text-xs font-medium text-muted-foreground mt-2"
          style={{
            writingMode: 'vertical-rl',
            textOrientation: 'mixed',
          }}
        >
          {collapsedLabel}
        </span>
        <ChevronRight className="h-4 w-4 text-muted-foreground mt-auto" />
      </div>
    )
  }

  return (
    <div
      className={cn(
        'flex-none basis-1/3 transition-all duration-150',
        className
      )}
    >
      {children}
    </div>
  )
}
