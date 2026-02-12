'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'

// Simple tooltip implementation without Radix UI dependency
// Uses CSS-based positioning for simplicity

interface TooltipProps {
  children: React.ReactNode
  content: React.ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
  delayDuration?: number
  className?: string
}

export function Tooltip({
  children,
  content,
  side = 'top',
  delayDuration = 200,
  className,
}: TooltipProps) {
  const [isVisible, setIsVisible] = React.useState(false)
  const timeoutRef = React.useRef<NodeJS.Timeout | null>(null)

  const handleMouseEnter = () => {
    timeoutRef.current = setTimeout(() => {
      setIsVisible(true)
    }, delayDuration)
  }

  const handleMouseLeave = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }
    setIsVisible(false)
  }

  const positionClasses = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
  }

  return (
    <div
      className="relative inline-flex"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
      {isVisible && content && (
        <div
          className={cn(
            'absolute z-50 px-3 py-1.5 text-xs font-medium text-popover-foreground bg-popover border rounded-md shadow-md whitespace-nowrap animate-in fade-in-0 zoom-in-95',
            positionClasses[side],
            className
          )}
          role="tooltip"
        >
          {content}
        </div>
      )}
    </div>
  )
}

// Provider wrapper for consistent delay across nested tooltips
interface TooltipProviderProps {
  children: React.ReactNode
  delayDuration?: number
}

export function TooltipProvider({ children, delayDuration = 200 }: TooltipProviderProps) {
  return <>{children}</>
}

// Trigger wrapper
export function TooltipTrigger({ children, asChild }: { children: React.ReactNode; asChild?: boolean }) {
  return <>{children}</>
}

// Content wrapper
export function TooltipContent({ children, side }: { children: React.ReactNode; side?: string }) {
  return <>{children}</>
}
