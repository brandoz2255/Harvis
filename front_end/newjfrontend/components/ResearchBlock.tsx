"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import {
  ChevronDown,
  Clock,
  Globe,
  ExternalLink,
  BookOpen,
  Loader2,
} from "lucide-react"
import { Button } from "@/components/ui/button"

export interface SearchResult {
  title: string
  url: string
  domain: string
  snippet?: string
}

export interface ResearchBlockProps {
  summary: string
  thinking: string
  query: string
  resultCount: number
  totalSources?: number
  results: SearchResult[]
  className?: string
  isLoading?: boolean
  isComplete?: boolean
  onSourceClick?: (url: string) => void
}

export function ResearchBlock({
  summary,
  thinking,
  query,
  resultCount,
  totalSources,
  results,
  className,
  isLoading = false,
  isComplete = false,
  onSourceClick,
}: ResearchBlockProps) {
  // Collapse when complete, expand while loading
  const [expanded, setExpanded] = useState(!isComplete)

  // Auto-collapse when complete
  if (isComplete && expanded) {
    setExpanded(false)
  }

  return (
    <div
      className={cn(
        "w-full overflow-hidden rounded-xl border border-border/60 bg-[oklch(0.1_0.005_260)]",
        className
      )}
    >
      {/* Collapsible Summary Header */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-[oklch(0.12_0.005_260)]"
      >
        <div className="flex items-center gap-2">
          {isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
          ) : (
            <BookOpen className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-sm text-muted-foreground">
            {isLoading 
              ? `Reading sources ${resultCount}${totalSources ? `/${totalSources}` : ""}...` 
              : summary}
          </span>
        </div>
        <ChevronDown
          className={cn(
            "ml-2 h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-180"
          )}
        />
      </button>

      {expanded && (
        <div className="border-t border-border/40 px-4 py-4 space-y-4">
          {/* Thinking Step */}
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border/50 bg-[oklch(0.14_0.005_260)]">
              <Clock className="h-3.5 w-3.5 text-muted-foreground" />
            </div>
            <p className="text-sm leading-relaxed text-foreground/80">
              {thinking}
            </p>
          </div>

          {/* Search Results */}
          <div className="space-y-2">
            {/* Query Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border/50 bg-[oklch(0.14_0.005_260)]">
                  <Globe className="h-3.5 w-3.5 text-muted-foreground" />
                </div>
                <span className="text-sm font-medium text-foreground">
                  {query}
                </span>
              </div>
              <span className="text-xs text-muted-foreground">
                {resultCount}{totalSources ? `/${totalSources}` : ""} sources
              </span>
            </div>

            {/* Results List */}
            <div className="ml-8 overflow-hidden rounded-lg border border-border/40 bg-[oklch(0.08_0.005_260)]">
              {results.map((result, index) => (
                <div
                  key={`result-${index}`}
                  onClick={() => onSourceClick?.(result.url)}
                  className={cn(
                    "flex items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-[oklch(0.12_0.005_260)] cursor-pointer",
                    index < results.length - 1 &&
                      "border-b border-border/30"
                  )}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <Globe className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="truncate text-sm text-foreground/90">
                      {result.title}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-muted-foreground">
                      {result.domain}
                    </span>
                    <ExternalLink className="h-3 w-3 text-muted-foreground/50" />
                  </div>
                </div>
              ))}
              
              {/* Loading indicator for more sources */}
              {isLoading && (
                <div className="flex items-center justify-center gap-2 px-4 py-3 border-t border-border/30">
                  <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">
                    Discovering more sources...
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
