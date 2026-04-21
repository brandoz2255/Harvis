"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import {
  ChevronLeft,
  ChevronRight,
  Terminal,
  CheckCircle,
  AlertCircle,
  Loader2,
  FileCode,
  Search,
  Globe,
  Database,
  FolderOpen,
  Code,
  Save,
  ExternalLink,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Highlight, themes } from "prism-react-renderer"

const TOOL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  run_code: FileCode,
  local_rag: Search,
  repo_read: FolderOpen,
  repo_write: Code,
  create_docx: FileCode,
  create_pdf: FileCode,
  web_fetch: Globe,
  run_code_python: FileCode,
  run_code_bash: Terminal,
  default: Terminal,
}

function getToolIcon(name: string): React.ComponentType<{ className?: string }> {
  return TOOL_ICONS[name] ?? TOOL_ICONS["default"]
}

interface ToolStreamEntry {
  toolCallId: string
  name: string
  args?: unknown
  text?: string
  kind: "call" | "result"
}

interface ToolStreamSidebarProps {
  entries: ToolStreamEntry[]
  isOpen: boolean
  onToggle: () => void
  splitRatio: number
  onSplitChange: (ratio: number) => void
}

export function ToolStreamSidebar({
  entries,
  isOpen,
  onToggle,
  splitRatio,
  onSplitChange,
}: ToolStreamSidebarProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggleExpand = (toolCallId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(toolCallId)) {
        next.delete(toolCallId)
      } else {
        next.add(toolCallId)
      }
      return next
    })
  }

  if (!isOpen) {
    return (
      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 absolute right-2 top-2 z-10"
        onClick={onToggle}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    )
  }

  return (
    <div
      className="relative flex flex-col border-l bg-muted/30"
      style={{ width: `${splitRatio * 100}%` }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <span className="text-sm font-medium">Tool Calls</span>
        <div className="flex items-center gap-1">
          <Badge variant="secondary" className="text-xs">
            {entries.length}
          </Badge>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onToggle}>
            <ChevronLeft className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {/* Entries */}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-2">
          {entries.length === 0 && (
            <div className="text-center text-sm text-muted-foreground py-8">
              No tool calls yet
            </div>
          )}
          {entries.map((entry) => {
            const isExpanded = expanded.has(entry.toolCallId)
            const Icon = getToolIcon(entry.name)
            const isResult = entry.kind === "result"
            const isCall = entry.kind === "call"

            return (
              <div
                key={entry.toolCallId}
                className={cn(
                  "rounded-lg border overflow-hidden transition-colors",
                  isResult ? "bg-green-500/5 border-green-500/20" : "bg-blue-500/5 border-blue-500/20"
                )}
              >
                <button
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-muted/50"
                  onClick={() => toggleExpand(entry.toolCallId)}
                >
                  <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="truncate flex-1 font-mono text-xs">{entry.name}</span>
                  {isCall && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
                  {isResult && <CheckCircle className="h-3 w-3 text-green-500 shrink-0" />}
                </button>

                {isExpanded && (
                  <div className="px-3 pb-2 space-y-2">
                    {entry.args != null && (
                      <div>
                        <div className="text-xs text-muted-foreground mb-1">Args</div>
                        <pre className="text-xs bg-muted/50 rounded p-2 overflow-x-auto font-mono">
                          {JSON.stringify(entry.args, null, 2)}
                        </pre>
                      </div>
                    )}
                    {entry.text && (
                      <div>
                        <div className="text-xs text-muted-foreground mb-1">Output</div>
                        <div className="text-xs bg-muted/50 rounded p-2 overflow-x-auto">
                          {String(entry.text)}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </ScrollArea>

      {/* Resize handle */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/20 transition-colors"
        onMouseDown={(e) => {
          const startX = e.clientX
          const startRatio = splitRatio
          const handleMouseMove = (e2: MouseEvent) => {
            const dx = e2.clientX - startX
            const newRatio = Math.max(0.15, Math.min(0.5, startRatio + dx / 800))
            onSplitChange(newRatio)
          }
          const handleMouseUp = () => {
            document.removeEventListener("mousemove", handleMouseMove)
            document.removeEventListener("mouseup", handleMouseUp)
          }
          document.addEventListener("mousemove", handleMouseMove)
          document.addEventListener("mouseup", handleMouseUp)
        }}
      />
    </div>
  )
}
