"use client"

import React, { useState, useEffect } from "react"
import JSZip from "jszip"
import { Loader2, AlertCircle, ChevronLeft, ChevronRight, Presentation } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"

interface Slide {
  number: number
  title: string
  content: string[]
}

interface PptxPreviewProps {
  downloadUrl: string
  className?: string
}

export function PptxPreview({ downloadUrl, className = "" }: PptxPreviewProps) {
  const [slides, setSlides] = useState<Slide[]>([])
  const [currentSlide, setCurrentSlide] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [presentationTitle, setPresentationTitle] = useState<string>("Presentation")

  useEffect(() => {
    const loadPresentation = async () => {
      try {
        setIsLoading(true)
        setError(null)

        // Fetch the PPTX file
        const token = localStorage.getItem("token")
        const response = await fetch(downloadUrl, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })

        if (!response.ok) {
          throw new Error(`Failed to load presentation: ${response.statusText}`)
        }

        const arrayBuffer = await response.arrayBuffer()

        // PPTX is a ZIP file - extract content
        const zip = await JSZip.loadAsync(arrayBuffer)

        // Get presentation properties for title
        const coreXml = await zip.file("docProps/core.xml")?.async("text")
        if (coreXml) {
          const titleMatch = coreXml.match(/<dc:title>([^<]*)<\/dc:title>/)
          if (titleMatch) {
            setPresentationTitle(titleMatch[1] || "Presentation")
          }
        }

        // Extract slides
        const extractedSlides: Slide[] = []
        const slideFiles = Object.keys(zip.files)
          .filter(name => name.match(/ppt\/slides\/slide\d+\.xml$/))
          .sort((a, b) => {
            const numA = parseInt(a.match(/slide(\d+)/)?.[1] || "0")
            const numB = parseInt(b.match(/slide(\d+)/)?.[1] || "0")
            return numA - numB
          })

        for (let i = 0; i < slideFiles.length; i++) {
          const slideXml = await zip.file(slideFiles[i])?.async("text")
          if (slideXml) {
            const slide = parseSlideXml(slideXml, i + 1)
            extractedSlides.push(slide)
          }
        }

        if (extractedSlides.length === 0) {
          throw new Error("No slides found in presentation")
        }

        setSlides(extractedSlides)
      } catch (err) {
        console.error("Error loading PPTX:", err)
        setError(err instanceof Error ? err.message : "Failed to load presentation")
      } finally {
        setIsLoading(false)
      }
    }

    if (downloadUrl) {
      loadPresentation()
    }
  }, [downloadUrl])

  // Parse slide XML to extract text content
  const parseSlideXml = (xml: string, slideNumber: number): Slide => {
    const texts: string[] = []
    let title = `Slide ${slideNumber}`

    // Extract all text content from <a:t> tags
    const textMatches = xml.matchAll(/<a:t>([^<]*)<\/a:t>/g)
    let isFirst = true

    for (const match of textMatches) {
      const text = match[1].trim()
      if (text) {
        if (isFirst) {
          title = text
          isFirst = false
        } else {
          texts.push(text)
        }
      }
    }

    return {
      number: slideNumber,
      title,
      content: texts,
    }
  }

  const goToPrevSlide = () => setCurrentSlide((prev) => Math.max(prev - 1, 0))
  const goToNextSlide = () => setCurrentSlide((prev) => Math.min(prev + 1, slides.length - 1))

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center h-[400px] bg-slate-900/50 rounded-lg ${className}`}>
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin text-orange-400 mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">Loading presentation...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`${className}`}>
        <Alert variant="destructive" className="bg-red-500/10 border-red-500/20">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    )
  }

  const slide = slides[currentSlide]

  return (
    <div className={`pptx-preview bg-slate-900 rounded-lg overflow-hidden ${className}`}>
      {/* Presentation Header */}
      <div className="flex items-center gap-2 px-4 py-2 bg-orange-500/10 border-b border-orange-500/20">
        <Presentation className="h-4 w-4 text-orange-400" />
        <span className="text-sm text-orange-300 font-medium">{presentationTitle}</span>
        <span className="text-xs text-muted-foreground ml-auto">{slides.length} slides</span>
      </div>

      {/* Slide Content */}
      <div
        className="bg-gradient-to-br from-slate-800 to-slate-900 min-h-[350px] p-8 flex flex-col"
        style={{ aspectRatio: "16/9", maxHeight: "450px" }}
      >
        {slide && (
          <>
            {/* Slide Title */}
            <h2 className="text-2xl font-bold text-white mb-6 text-center">
              {slide.title}
            </h2>

            {/* Slide Content */}
            <div className="flex-1 overflow-auto">
              {slide.content.length > 0 ? (
                <ul className="space-y-3 text-slate-300">
                  {slide.content.map((text, idx) => (
                    <li key={idx} className="flex items-start gap-2">
                      <span className="text-orange-400 mt-1">•</span>
                      <span>{text}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground text-center italic">
                  No additional content on this slide
                </p>
              )}
            </div>
          </>
        )}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-800/50 border-t border-slate-700">
        <Button
          variant="ghost"
          size="sm"
          onClick={goToPrevSlide}
          disabled={currentSlide === 0}
          className="text-orange-300 hover:text-orange-200 hover:bg-orange-500/10 disabled:opacity-50"
        >
          <ChevronLeft className="h-4 w-4 mr-1" />
          Previous
        </Button>

        {/* Slide Indicators */}
        <div className="flex items-center gap-1.5">
          {slides.map((_, idx) => (
            <button
              key={idx}
              onClick={() => setCurrentSlide(idx)}
              className={`w-2 h-2 rounded-full transition-colors ${
                idx === currentSlide
                  ? "bg-orange-400"
                  : "bg-slate-600 hover:bg-slate-500"
              }`}
              aria-label={`Go to slide ${idx + 1}`}
            />
          ))}
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={goToNextSlide}
          disabled={currentSlide === slides.length - 1}
          className="text-orange-300 hover:text-orange-200 hover:bg-orange-500/10 disabled:opacity-50"
        >
          Next
          <ChevronRight className="h-4 w-4 ml-1" />
        </Button>
      </div>

      {/* Slide Counter */}
      <div className="text-center py-2 text-xs text-muted-foreground bg-slate-800/30">
        Slide {currentSlide + 1} of {slides.length}
      </div>
    </div>
  )
}

export default PptxPreview
