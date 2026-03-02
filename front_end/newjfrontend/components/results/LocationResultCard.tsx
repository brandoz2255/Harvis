"use client"

import React, { useState, useCallback } from "react"
import { 
  MapPin, 
  Phone, 
  Globe, 
  ExternalLink, 
  Star, 
  Clock, 
  DollarSign,
  Navigation,
  Copy,
  Check,
  Share2,
  Info
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { LocationResult } from "@/types/results"

interface LocationResultCardProps {
  location: LocationResult
  showMap?: boolean
  mapHeight?: number
  onDirectionsClick?: (location: LocationResult) => void
  onShareClick?: (location: LocationResult) => void
  className?: string
}

/**
 * Static Map Component using Google Maps Static API
 * 
 * Displays a static map image with a marker at the location.
 * Falls back gracefully if API key is not configured.
 */
function StaticMap({ 
  latitude, 
  longitude, 
  height = 200 
}: { 
  latitude: number
  longitude: number
  height?: number 
}) {
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)

  // Use the backend proxy for the static map
  // This keeps the API key secure on the server
  const mapUrl = `/api/maps/static?center=${latitude},${longitude}&zoom=15&size=600x${height}&markers=${latitude},${longitude}`

  if (error) {
    return (
      <div 
        className="w-full flex items-center justify-center bg-muted rounded-lg"
        style={{ height }}
      >
        <div className="text-center p-4">
          <MapPin className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
          <p className="text-sm text-muted-foreground">
            {latitude.toFixed(6)}, {longitude.toFixed(6)}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="relative w-full rounded-lg overflow-hidden" style={{ height }}>
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-muted">
          <div className="animate-pulse flex space-x-2">
            <div className="h-2 w-2 bg-primary rounded-full animate-bounce" />
            <div className="h-2 w-2 bg-primary rounded-full animate-bounce [animation-delay:0.1s]" />
            <div className="h-2 w-2 bg-primary rounded-full animate-bounce [animation-delay:0.2s]" />
          </div>
        </div>
      )}
      <img
        src={mapUrl}
        alt={`Map showing location at ${latitude}, ${longitude}`}
        className="w-full h-full object-cover"
        onError={() => {
          setError(true)
          setLoading(false)
        }}
        onLoad={() => setLoading(false)}
      />
      <a
        href={`https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`}
        target="_blank"
        rel="noopener noreferrer"
        className="absolute bottom-2 right-2 bg-white/90 dark:bg-black/90 px-2 py-1 rounded text-xs font-medium shadow-sm hover:bg-white dark:hover:bg-black transition-colors"
      >
        View on Google Maps
      </a>
    </div>
  )
}

/**
 * Price Level Indicator
 * Shows dollar signs based on price level (1-4)
 */
function PriceLevel({ level }: { level?: number }) {
  if (!level) return null
  
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center text-muted-foreground">
            <DollarSign className="h-3.5 w-3.5 mr-0.5" />
            <span className="text-xs">
              {Array(level).fill('$').join('')}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <p>Price level: {['', 'Inexpensive', 'Moderate', 'Expensive', 'Very Expensive'][level]}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

/**
 * Rating Display
 * Shows star rating with review count
 */
function RatingDisplay({ 
  rating, 
  totalRatings 
}: { 
  rating?: number
  totalRatings?: number 
}) {
  if (!rating) return null

  const fullStars = Math.floor(rating)
  const hasHalfStar = rating % 1 >= 0.5
  const emptyStars = 5 - fullStars - (hasHalfStar ? 1 : 0)

  return (
    <div className="flex items-center gap-1.5">
      <div className="flex items-center">
        {/* Full stars */}
        {Array(fullStars).fill(null).map((_, i) => (
          <Star key={`full-${i}`} className="h-3.5 w-3.5 fill-yellow-400 text-yellow-400" />
        ))}
        {/* Half star */}
        {hasHalfStar && (
          <div className="relative">
            <Star className="h-3.5 w-3.5 text-muted" />
            <div className="absolute inset-0 overflow-hidden w-1/2">
              <Star className="h-3.5 w-3.5 fill-yellow-400 text-yellow-400" />
            </div>
          </div>
        )}
        {/* Empty stars */}
        {Array(emptyStars).fill(null).map((_, i) => (
          <Star key={`empty-${i}`} className="h-3.5 w-3.5 text-muted" />
        ))}
      </div>
      <span className="text-sm font-medium">{rating.toFixed(1)}</span>
      {totalRatings !== undefined && totalRatings > 0 && (
        <span className="text-xs text-muted-foreground">
          ({totalRatings.toLocaleString()} reviews)
        </span>
      )}
    </div>
  )
}

/**
 * Opening Hours Badge
 * Shows if place is currently open
 */
function OpeningHoursBadge({ openNow }: { openNow?: boolean }) {
  if (openNow === undefined) return null

  return (
    <Badge 
      variant={openNow ? "default" : "secondary"}
      className={openNow ? "bg-green-500/20 text-green-600 hover:bg-green-500/30" : ""}
    >
      <Clock className="h-3 w-3 mr-1" />
      {openNow ? "Open now" : "Closed"}
    </Badge>
  )
}

/**
 * Copy Button
 * Copies text to clipboard with visual feedback
 */
function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [text])

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopy}
            className="h-7 px-2"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-green-500" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {label && <span className="ml-1 text-xs">{label}</span>}
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{copied ? "Copied!" : "Copy to clipboard"}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

/**
 * LocationResultCard Component
 * 
 * Displays a location result with an interactive map, ratings,
 * contact info, and action buttons.
 */
export function LocationResultCard({
  location,
  showMap = true,
  mapHeight = 200,
  onDirectionsClick,
  onShareClick,
  className,
}: LocationResultCardProps) {
  const [imageError, setImageError] = useState(false)

  // Build place types string
  const placeTypes = location.types
    ?.filter(type => !['point_of_interest', 'establishment'].includes(type))
    .slice(0, 3)
    .map(type => type.replace(/_/g, ' '))
    .join(' • ') || ''

  // Handle getting directions
  const handleDirections = useCallback(() => {
    const url = `https://www.google.com/maps/dir/?api=1&destination=${location.latitude},${location.longitude}`
    window.open(url, '_blank', 'noopener,noreferrer')
    onDirectionsClick?.(location)
  }, [location, onDirectionsClick])

  // Handle sharing
  const handleShare = useCallback(async () => {
    const shareData = {
      title: location.name,
      text: `Check out ${location.name} at ${location.address}`,
      url: location.url || `https://www.google.com/maps/search/?api=1&query=${location.latitude},${location.longitude}`,
    }

    if (navigator.share) {
      try {
        await navigator.share(shareData)
      } catch (err) {
        // User cancelled or share failed
        console.log('Share cancelled')
      }
    } else {
      // Fallback: copy link to clipboard
      await navigator.clipboard.writeText(shareData.url)
    }
    
    onShareClick?.(location)
  }, [location, onShareClick])

  return (
    <Card className={`overflow-hidden ${className || ''}`}>
      {/* Photo/Map Header */}
      {(location.photoUrl || showMap) && (
        <div className="relative">
          {location.photoUrl && !imageError ? (
            <div className="relative h-48 w-full">
              <img
                src={location.photoUrl}
                alt={location.name}
                className="w-full h-full object-cover"
                onError={() => setImageError(true)}
              />
              <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
              <div className="absolute bottom-3 left-3 right-3">
                <h3 className="text-white font-semibold text-lg leading-tight">
                  {location.name}
                </h3>
                {placeTypes && (
                  <p className="text-white/80 text-sm capitalize">{placeTypes}</p>
                )}
              </div>
            </div>
          ) : showMap ? (
            <StaticMap
              latitude={location.latitude}
              longitude={location.longitude}
              height={mapHeight}
            />
          ) : null}
        </div>
      )}

      <CardHeader className={location.photoUrl ? "pt-3" : undefined}>
        {!location.photoUrl && (
          <CardTitle className="text-lg flex items-start gap-2">
            <MapPin className="h-5 w-5 text-primary shrink-0 mt-0.5" />
            <div>
              <div>{location.name}</div>
              {placeTypes && (
                <p className="text-sm text-muted-foreground capitalize font-normal">
                  {placeTypes}
                </p>
              )}
            </div>
          </CardTitle>
        )}

        {/* Rating and Price */}
        <div className="flex items-center gap-3 flex-wrap">
          <RatingDisplay rating={location.rating} totalRatings={location.totalRatings} />
          <PriceLevel level={location.priceLevel} />
          <OpeningHoursBadge openNow={location.openNow} />
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Address */}
        <div className="flex items-start gap-2">
          <MapPin className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm">{location.address}</p>
            <div className="flex items-center gap-1 mt-1">
              <CopyButton text={location.address} />
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={handleDirections}
              >
                <Navigation className="h-3.5 w-3.5 mr-1" />
                Directions
              </Button>
            </div>
          </div>
        </div>

        {/* Phone */}
        {location.phoneNumber && (
          <div className="flex items-center gap-2">
            <Phone className="h-4 w-4 text-muted-foreground shrink-0" />
            <a 
              href={`tel:${location.phoneNumber}`}
              className="text-sm hover:underline text-primary"
            >
              {location.phoneNumber}
            </a>
          </div>
        )}

        {/* Website */}
        {location.website && (
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-muted-foreground shrink-0" />
            <a 
              href={location.website}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm hover:underline text-primary truncate"
            >
              {new URL(location.website).hostname.replace('www.', '')}
            </a>
          </div>
        )}

        {/* Coordinates (collapsible) */}
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1">
            <Info className="h-3.5 w-3.5" />
            Coordinates
          </summary>
          <div className="mt-2 pl-5 text-xs text-muted-foreground font-mono">
            {location.latitude.toFixed(6)}, {location.longitude.toFixed(6)}
          </div>
        </details>

        {/* Distance/Duration (if available) */}
        {(location.distance || location.duration) && (
          <>
            <Separator />
            <div className="flex items-center gap-4 text-sm">
              {location.distance && (
                <div>
                  <span className="text-muted-foreground">Distance: </span>
                  <span className="font-medium">{location.distance.text}</span>
                </div>
              )}
              {location.duration && (
                <div>
                  <span className="text-muted-foreground">Duration: </span>
                  <span className="font-medium">{location.duration.text}</span>
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>

      <CardFooter className="flex gap-2">
        <Button
          variant="default"
          size="sm"
          className="flex-1"
          onClick={handleDirections}
        >
          <Navigation className="h-4 w-4 mr-2" />
          Get Directions
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleShare}
        >
          <Share2 className="h-4 w-4" />
        </Button>
        {location.url && (
          <Button
            variant="outline"
            size="sm"
            asChild
          >
            <a
              href={location.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          </Button>
        )}
      </CardFooter>
    </Card>
  )
}

export default LocationResultCard
