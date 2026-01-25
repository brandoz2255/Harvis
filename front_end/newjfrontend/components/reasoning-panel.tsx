"use client"

import { useState } from "react"
import { Brain, ChevronDown, ChevronUp } from "lucide-react"
import { Button } from "@/components/ui/button"

interface ReasoningPanelProps {
  reasoning: string
}

export function ReasoningPanel({ reasoning }: ReasoningPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!reasoning) return null

  return (
    <div className="mt-3 border border-purple-500/30 rounded-lg bg-purple-500/5">
      <Button
        variant="ghost"
        className="w-full flex items-center justify-between p-3 hover:bg-purple-500/10"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-purple-500" />
          <span className="text-sm font-medium text-purple-500">
            AI Reasoning Process
          </span>
        </div>
        {isExpanded ? (
          <ChevronUp className="h-4 w-4 text-purple-500" />
        ) : (
          <ChevronDown className="h-4 w-4 text-purple-500" />
        )}
      </Button>

      {isExpanded && (
        <div className="px-3 pb-3 pt-1">
          <div className="text-sm text-muted-foreground whitespace-pre-wrap font-mono bg-black/20 rounded p-3 max-h-96 overflow-y-auto">
            {reasoning}
          </div>
        </div>
      )}
    </div>
  )
}
