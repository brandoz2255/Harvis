"use client"

import { useState, useRef } from "react"
import { cn } from "@/lib/utils"
import { Play, ChevronLeft, ChevronRight, ExternalLink, Youtube } from "lucide-react"
import { Button } from "@/components/ui/button"

export interface VideoResult {
  title: string
  url: string
  thumbnail: string
  channel?: string
  duration?: string
  views?: string
  description?: string
  published?: string
}

interface VideoCarouselProps {
  videos: VideoResult[]
  compact?: boolean
  className?: string
}

export function VideoCarousel({ videos, compact = false, className }: VideoCarouselProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(true)

  const checkScroll = () => {
    if (scrollContainerRef.current) {
      const { scrollLeft, scrollWidth, clientWidth } = scrollContainerRef.current
      setCanScrollLeft(scrollLeft > 0)
      setCanScrollRight(scrollLeft < scrollWidth - clientWidth - 10)
    }
  }

  const scroll = (direction: "left" | "right") => {
    if (scrollContainerRef.current) {
      const scrollAmount = direction === "left" ? -280 : 280
      scrollContainerRef.current.scrollBy({ left: scrollAmount, behavior: "smooth" })
      setTimeout(checkScroll, 300)
    }
  }

  if (!videos || videos.length === 0) return null

  return (
    <div className={cn("relative group w-full", className)}>
      {/* Header */}
      <div className="flex items-center space-x-2 mb-3">
        <Youtube className="w-4 h-4 text-red-500" />
        <span className="text-xs text-muted-foreground font-medium">Related Videos</span>
        <span className="text-xs text-muted-foreground/60">({videos.length})</span>
      </div>

      {/* Scroll Container */}
      <div className="relative">
        {/* Left Arrow */}
        {canScrollLeft && (
          <Button
            onClick={() => scroll("left")}
            variant="secondary"
            size="icon"
            className="absolute left-0 top-1/2 -translate-y-1/2 z-10 h-8 w-8 rounded-full
                       opacity-0 group-hover:opacity-100 transition-opacity shadow-lg"
          >
            <ChevronLeft className="w-4 h-4" />
          </Button>
        )}

        {/* Videos Container */}
        <div
          ref={scrollContainerRef}
          onScroll={checkScroll}
          className="flex space-x-3 overflow-x-auto pb-2 scrollbar-hide"
          style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
        >
          {videos.map((video, index) => (
            <VideoCard key={index} video={video} compact={compact} />
          ))}
        </div>

        {/* Right Arrow */}
        {canScrollRight && videos.length > 3 && (
          <Button
            onClick={() => scroll("right")}
            variant="secondary"
            size="icon"
            className="absolute right-0 top-1/2 -translate-y-1/2 z-10 h-8 w-8 rounded-full
                       opacity-0 group-hover:opacity-100 transition-opacity shadow-lg"
          >
            <ChevronRight className="w-4 h-4" />
          </Button>
        )}
      </div>
    </div>
  )
}

interface VideoCardProps {
  video: VideoResult
  compact?: boolean
}

function VideoCard({ video, compact }: VideoCardProps) {
  const [imageError, setImageError] = useState(false)
  const [isHovered, setIsHovered] = useState(false)

  const openVideo = () => {
    window.open(video.url, "_blank", "noopener,noreferrer")
  }

  return (
    <div
      onClick={openVideo}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className={cn(
        "flex-shrink-0 cursor-pointer group/card rounded-xl overflow-hidden",
        "bg-card border border-border hover:border-primary/50",
        "transition-all duration-200 hover:shadow-lg hover:shadow-primary/10",
        compact ? "w-48" : "w-64"
      )}
    >
      {/* Thumbnail */}
      <div className="relative aspect-video bg-muted">
        {!imageError ? (
          <img
            src={video.thumbnail}
            alt={video.title}
            onError={() => setImageError(true)}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-muted">
            <Youtube className="w-8 h-8 text-red-500/50" />
          </div>
        )}

        {/* Play Button Overlay */}
        <div
          className={cn(
            "absolute inset-0 flex items-center justify-center bg-black/40 transition-opacity",
            isHovered ? "opacity-100" : "opacity-0"
          )}
        >
          <div className="w-12 h-12 rounded-full bg-red-600 flex items-center justify-center shadow-lg">
            <Play className="w-6 h-6 text-white ml-1" fill="white" />
          </div>
        </div>

        {/* Duration Badge */}
        {video.duration && (
          <div className="absolute bottom-1 right-1 bg-black/80 px-1.5 py-0.5 rounded text-xs text-white font-medium">
            {video.duration}
          </div>
        )}
      </div>

      {/* Info */}
      <div className="p-2">
        <h4
          className={cn(
            "font-medium text-foreground line-clamp-2 group-hover/card:text-primary transition-colors",
            compact ? "text-xs" : "text-sm"
          )}
        >
          {video.title}
        </h4>

        {video.channel && (
          <p className={cn("text-muted-foreground mt-1 truncate", compact ? "text-[10px]" : "text-xs")}>
            {video.channel}
          </p>
        )}

        {video.views && !compact && (
          <p className="text-[10px] text-muted-foreground/70 mt-0.5">{video.views}</p>
        )}
      </div>
    </div>
  )
}

// Compact inline video list for smaller spaces
export function VideoList({ videos, maxShow = 3 }: { videos: VideoResult[]; maxShow?: number }) {
  if (!videos || videos.length === 0) return null

  return (
    <div className="space-y-2">
      <div className="flex items-center space-x-2">
        <Youtube className="w-3 h-3 text-red-500" />
        <span className="text-xs text-muted-foreground">Related Videos</span>
      </div>
      <div className="space-y-1">
        {videos.slice(0, maxShow).map((video, idx) => (
          <a
            key={idx}
            href={video.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center space-x-2 p-1.5 rounded-lg bg-muted/50 hover:bg-muted
                       transition-colors group"
          >
            <div className="w-16 h-9 flex-shrink-0 rounded overflow-hidden bg-muted">
              <img
                src={video.thumbnail}
                alt=""
                className="w-full h-full object-cover"
                onError={(e) => {
                  ;(e.target as HTMLImageElement).style.display = "none"
                }}
              />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-foreground line-clamp-1 group-hover:text-primary transition-colors">
                {video.title}
              </p>
              {video.channel && <p className="text-[10px] text-muted-foreground truncate">{video.channel}</p>}
            </div>
            <ExternalLink className="w-3 h-3 text-muted-foreground flex-shrink-0" />
          </a>
        ))}
        {videos.length > maxShow && (
          <p className="text-[10px] text-muted-foreground text-center">+{videos.length - maxShow} more videos</p>
        )}
      </div>
    </div>
  )
}

export default VideoCarousel
