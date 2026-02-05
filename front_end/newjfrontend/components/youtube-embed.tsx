"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Maximize2, Minimize2, ExternalLink, X, FileText } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"

interface YouTubeEmbedProps {
  videoId: string
  title: string
  transcript?: string
  hasTranscript?: boolean
  onClose?: () => void
  className?: string
}

export function YouTubeEmbed({
  videoId,
  title,
  transcript,
  hasTranscript,
  onClose,
  className
}: YouTubeEmbedProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [showTranscript, setShowTranscript] = useState(false)

  if (!videoId) {
    return null
  }

  return (
    <div
      className={cn(
        "relative rounded-xl overflow-hidden border border-border bg-card transition-all duration-300",
        isExpanded ? "max-w-4xl" : "max-w-xl",
        className
      )}
    >
      {/* Header with controls */}
      <div className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-border">
        <span className="text-sm font-medium text-foreground truncate max-w-[60%]">
          {title}
        </span>
        <div className="flex items-center gap-1">
          {hasTranscript && transcript && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setShowTranscript(!showTranscript)}
              title={showTranscript ? "Hide transcript" : "Show transcript"}
            >
              <FileText className={cn("h-4 w-4", showTranscript && "text-primary")} />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? "Collapse" : "Expand"}
          >
            {isExpanded ? (
              <Minimize2 className="h-4 w-4" />
            ) : (
              <Maximize2 className="h-4 w-4" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => window.open(`https://youtube.com/watch?v=${videoId}`, "_blank")}
            title="Open in YouTube"
          >
            <ExternalLink className="h-4 w-4" />
          </Button>
          {onClose && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={onClose}
              title="Close player"
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Video iframe */}
      <div className="relative aspect-video bg-black">
        <iframe
          src={`https://www.youtube.com/embed/${videoId}?rel=0&modestbranding=1`}
          title={title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowFullScreen
          className="absolute inset-0 w-full h-full"
        />
      </div>

      {/* Transcript panel (collapsible) */}
      {showTranscript && transcript && (
        <div className="border-t border-border bg-muted/30">
          <div className="px-3 py-2 flex items-center justify-between border-b border-border/50">
            <span className="text-xs font-medium text-muted-foreground">Transcript</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-xs"
              onClick={() => {
                navigator.clipboard.writeText(transcript)
              }}
            >
              Copy
            </Button>
          </div>
          <ScrollArea className="h-40">
            <p className="p-3 text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">
              {transcript}
            </p>
          </ScrollArea>
        </div>
      )}
    </div>
  )
}

export default YouTubeEmbed
