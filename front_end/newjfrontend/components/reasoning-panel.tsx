"use client"

import { useState, useEffect, useRef } from "react"
import { Brain, ChevronDown, ChevronUp, Sparkles, Clock, Copy, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface ReasoningPanelProps {
  reasoning: string
  defaultExpanded?: boolean
}

export function ReasoningPanel({ reasoning, defaultExpanded = false }: ReasoningPanelProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)
  const [copied, setCopied] = useState(false)
  const [wordCount, setWordCount] = useState(0)
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (reasoning) {
      setWordCount(reasoning.split(/\s+/).filter(Boolean).length)
    }
  }, [reasoning])

  if (!reasoning || reasoning.trim() === '') return null

  // Clean the reasoning text (remove any remaining think/thinking tags)
  const cleanReasoning = reasoning
    .replace(/<\/?think>/gi, '')
    .replace(/<\/?thinking>/gi, '')
    .replace(/^[\s\n]+|[\s\n]+$/g, '')

  if (!cleanReasoning) return null

  const handleCopy = async () => {
    await navigator.clipboard.writeText(cleanReasoning)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // Calculate estimated read time (average 200 words per minute)
  const readTimeMinutes = Math.max(1, Math.ceil(wordCount / 200))

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-violet-500/20 bg-gradient-to-br from-violet-950/30 via-purple-950/20 to-fuchsia-950/30 backdrop-blur-sm">
      {/* Header */}
      <button
        className="w-full flex items-center justify-between p-3 hover:bg-violet-500/10 transition-all duration-200"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          {/* Animated Brain Icon */}
          <div className="relative">
            <div className="absolute inset-0 bg-violet-500/30 rounded-lg blur-md animate-pulse" />
            <div className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 shadow-lg shadow-violet-500/20">
              <Brain className="h-4 w-4 text-white" />
            </div>
          </div>

          <div className="flex flex-col items-start">
            <span className="text-sm font-semibold bg-gradient-to-r from-violet-400 to-purple-400 bg-clip-text text-transparent">
              AI Reasoning Process
            </span>
            <div className="flex items-center gap-2 text-xs text-violet-400/70">
              <Sparkles className="h-3 w-3" />
              <span>{wordCount} words</span>
              <span className="text-violet-500/50">•</span>
              <Clock className="h-3 w-3" />
              <span>~{readTimeMinutes} min read</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Collapse indicator */}
          <div className={cn(
            "flex items-center gap-1 px-2 py-1 rounded-full text-xs transition-all duration-200",
            isExpanded
              ? "bg-violet-500/20 text-violet-300"
              : "bg-violet-500/10 text-violet-400"
          )}>
            {isExpanded ? "Hide" : "Show"}
            {isExpanded ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
          </div>
        </div>
      </button>

      {/* Content */}
      <div className={cn(
        "overflow-hidden transition-all duration-300 ease-in-out",
        isExpanded ? "max-h-[600px] opacity-100" : "max-h-0 opacity-0"
      )}>
        <div className="relative px-4 pb-4">
          {/* Copy button */}
          <div className="absolute top-2 right-4 z-10">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCopy}
              className="h-7 text-xs text-violet-400 hover:text-violet-300 hover:bg-violet-500/20"
            >
              {copied ? (
                <>
                  <Check className="mr-1 h-3 w-3" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="mr-1 h-3 w-3" />
                  Copy
                </>
              )}
            </Button>
          </div>

          {/* Reasoning content */}
          <div
            ref={contentRef}
            className="rounded-lg bg-black/30 p-4 max-h-96 overflow-y-auto scrollbar-thin scrollbar-thumb-violet-500/30 scrollbar-track-transparent"
          >
            {/* Decorative elements */}
            <div className="absolute top-6 left-6 w-px h-full bg-gradient-to-b from-violet-500/50 via-purple-500/30 to-transparent pointer-events-none" />

            <div className="relative pl-4">
              {/* Format reasoning with visual hierarchy */}
              <div className="text-sm text-violet-200/80 leading-relaxed whitespace-pre-wrap font-mono">
                {cleanReasoning.split('\n').map((line, i) => {
                  // Highlight numbered steps or bullet points
                  const isStep = /^[\d]+[.)]|^[-•*]/.test(line.trim())
                  const isHeading = line.trim().length < 50 && (line.trim().endsWith(':') || /^[A-Z]/.test(line.trim()))

                  return (
                    <div
                      key={i}
                      className={cn(
                        "py-0.5",
                        isStep && "text-violet-300 font-medium",
                        isHeading && !isStep && "text-purple-300 font-semibold mt-2"
                      )}
                    >
                      {line || '\u00A0'}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* Gradient fade at bottom when content is long */}
          <div className="pointer-events-none absolute bottom-4 left-4 right-4 h-8 bg-gradient-to-t from-black/30 to-transparent rounded-b-lg" />
        </div>
      </div>

      {/* Collapsed preview */}
      {!isExpanded && (
        <div className="px-4 pb-3">
          <div className="text-xs text-violet-400/60 italic truncate">
            {cleanReasoning.slice(0, 100)}...
          </div>
        </div>
      )}
    </div>
  )
}
