"use client"

import { useState, useEffect } from "react"
import { Clock, Globe, FileText, ChevronDown, Search } from "lucide-react"
import { cn } from "@/lib/utils"

// Types for research chain steps
import {
    ThinkingStep,
    SearchStep,
    ReadStep,
    ResearchStep,
    ResearchChainData
} from "@/types/message"

export interface ResearchChainProps {
    /** Summary text shown in the collapsed header */
    summary: string
    /** Array of research steps to display */
    steps: ResearchStep[]
    /** Whether the chain is expanded by default */
    defaultExpanded?: boolean
    /** Whether the chain is currently loading/in progress */
    isLoading?: boolean
    /** Additional CSS class names */
    className?: string
}

/**
 * ResearchChain Component
 * 
 * A collapsible card that visualizes AI's step-by-step research process.
 * Supports three step types: Thinking, Search, and Read.
 */
export function ResearchChain({
    summary,
    steps,
    defaultExpanded = false,
    isLoading = false,
    className,
}: ResearchChainProps) {
    // Auto-expand when loading to show live progress
    const [isExpanded, setIsExpanded] = useState(defaultExpanded || isLoading)

    // Auto-expand when loading starts (for streaming research)
    useEffect(() => {
        if (isLoading) {
            setIsExpanded(true)
        }
    }, [isLoading])

    return (
        <div
            className={cn(
                "overflow-hidden rounded-xl border border-white/5 bg-[#111]",
                className
            )}
        >
            {/* Collapsible Header */}
            <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-white/[0.02]"
            >
                <div className="flex items-center gap-3 min-w-0">
                    {/* Animated loading indicator or search icon */}
                    {isLoading ? (
                        <div className="flex items-center gap-1">
                            <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.3s]" />
                            <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.15s]" />
                            <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400" />
                        </div>
                    ) : (
                        <Search className="h-4 w-4 text-gray-400 shrink-0" />
                    )}

                    {/* Summary text */}
                    <span className="text-sm text-gray-300 truncate">
                        {isLoading ? "Researching..." : summary}
                    </span>
                </div>

                {/* Chevron that rotates on expand */}
                <ChevronDown
                    className={cn(
                        "h-4 w-4 text-gray-500 shrink-0 transition-transform duration-200",
                        isExpanded && "rotate-180"
                    )}
                />
            </button>

            {/* Expandable Content with smooth animation */}
            <div
                className={cn(
                    "grid transition-all duration-300 ease-in-out",
                    isExpanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                )}
            >
                <div className="overflow-hidden">
                    <div className="border-t border-white/5 px-4 py-3 space-y-3">
                        {steps.map((step, index) => (
                            <ResearchStepItem key={index} step={step} />
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

/**
 * Renders individual research steps based on their type
 */
function ResearchStepItem({ step }: { step: ResearchStep }) {
    switch (step.type) {
        case "thinking":
            return <ThinkingStepComponent step={step} />
        case "search":
            return <SearchStepComponent step={step} />
        case "read":
            return <ReadStepComponent step={step} />
        default:
            return null
    }
}

/**
 * Thinking Step - Shows AI's internal reasoning
 */
function ThinkingStepComponent({ step }: { step: ThinkingStep }) {
    return (
        <div className="flex items-start gap-3">
            <Clock className="h-4 w-4 text-gray-500 mt-0.5 shrink-0" />
            <p className="text-sm text-gray-400 italic leading-relaxed">
                {step.content}
            </p>
        </div>
    )
}

/**
 * Search Step - Shows web search query and results
 */
function SearchStepComponent({ step }: { step: SearchStep }) {
    const [showAll, setShowAll] = useState(false)
    const visibleResults = showAll ? step.results : step.results.slice(0, 5)
    const hasMore = step.results.length > 5

    return (
        <div className="flex items-start gap-3">
            <Globe className="h-4 w-4 text-gray-400 mt-0.5 shrink-0" />

            <div className="flex-1 min-w-0">
                {/* Header row: query + result count */}
                <div className="flex items-center justify-between gap-2 mb-2">
                    <span className="text-sm text-gray-200 font-medium truncate">
                        {step.query}
                    </span>
                    <span className="text-xs text-gray-500 shrink-0">
                        {step.resultCount} results
                    </span>
                </div>

                {/* Results list */}
                {step.results.length > 0 && (
                    <div className="relative">
                        <div
                            className={cn(
                                "rounded-lg border border-white/5 bg-[#0a0a0a] overflow-hidden",
                                !showAll && hasMore && "max-h-[200px] overflow-y-auto"
                            )}
                        >
                            <div className="divide-y divide-white/5">
                                {visibleResults.map((result, idx) => (
                                    <a
                                        key={idx}
                                        href={result.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex items-center gap-2.5 px-3 py-2 hover:bg-white/[0.03] transition-colors"
                                    >
                                        {/* Favicon */}
                                        <img
                                            src={`https://www.google.com/s2/favicons?domain=${result.domain}&sz=16`}
                                            alt=""
                                            className="w-4 h-4 rounded-sm shrink-0"
                                            onError={(e) => {
                                                // Fallback to globe icon if favicon fails
                                                e.currentTarget.style.display = 'none'
                                            }}
                                        />

                                        {/* Title */}
                                        <span className="text-sm text-gray-300 truncate flex-1">
                                            {result.title}
                                        </span>

                                        {/* Domain */}
                                        <span className="text-xs text-gray-500 shrink-0">
                                            {result.domain}
                                        </span>
                                    </a>
                                ))}
                            </div>
                        </div>

                        {/* Bottom fade gradient when scrollable */}
                        {!showAll && hasMore && (
                            <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-[#0a0a0a] to-transparent pointer-events-none rounded-b-lg" />
                        )}
                    </div>
                )}

                {/* Show more/less toggle */}
                {hasMore && (
                    <button
                        onClick={() => setShowAll(!showAll)}
                        className="mt-2 text-xs text-gray-500 hover:text-gray-400 transition-colors flex items-center gap-1"
                    >
                        {showAll ? "Show less" : `Show ${step.results.length - 5} more`}
                        <ChevronDown
                            className={cn(
                                "h-3 w-3 transition-transform",
                                showAll && "rotate-180"
                            )}
                        />
                    </button>
                )}
            </div>
        </div>
    )
}

/**
 * Read Step - Shows AI reading a webpage
 */
function ReadStepComponent({ step }: { step: ReadStep }) {
    return (
        <div className="flex items-start gap-3">
            <FileText className="h-4 w-4 text-gray-400 mt-0.5 shrink-0" />

            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm text-gray-300">Reading</span>
                    <span className="text-sm text-gray-200 font-medium">{step.domain}</span>
                </div>
                <p className="text-sm text-gray-400 leading-relaxed">
                    {step.summary}
                </p>
            </div>
        </div>
    )
}

export default ResearchChain
