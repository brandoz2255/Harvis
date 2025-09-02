"use client"

import { useState, useRef, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Search, Globe, BookOpen, ExternalLink, Download, Copy, Trash2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

interface SearchResult {
  title: string
  url: string
  snippet: string
  timestamp: string
  domain: string
}

interface ResearchSession {
  id: string
  query: string
  results: SearchResult[]
  timestamp: Date
  summary?: string
}

export default function ResearchAssistant() {
  const [searchQuery, setSearchQuery] = useState("")
  const [isSearching, setIsSearching] = useState(false)
  const [currentResults, setCurrentResults] = useState<SearchResult[]>([])
  const [researchSessions, setResearchSessions] = useState<ResearchSession[]>([])
  const [selectedSession, setSelectedSession] = useState<ResearchSession | null>(null)
  const [isGeneratingSummary, setIsGeneratingSummary] = useState(false)

  const resultsEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    resultsEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [currentResults])

  const performSearch = async () => {
    if (!searchQuery.trim() || isSearching) return

    setIsSearching(true)

    try {
      const response = await fetch("/api/web-search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: searchQuery,
          model: "mistral",
          maxResults: 10,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        const results = data.results || []

        setCurrentResults(results)

        // Create new research session
        const newSession: ResearchSession = {
          id: Date.now().toString(),
          query: searchQuery,
          results,
          timestamp: new Date(),
        }

        setResearchSessions((prev) => [newSession, ...prev.slice(0, 9)]) // Keep last 10 sessions
        setSelectedSession(newSession)
        setSearchQuery("")
      }
    } catch (error) {
      console.error("Search failed:", error)
    } finally {
      setIsSearching(false)
    }
  }

  const generateSummary = async (session: ResearchSession) => {
    if (!session.results.length || isGeneratingSummary) return

    setIsGeneratingSummary(true)

    try {
      // Extended timeout for research requests (5 minutes)
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 300000) // 5 minutes

      const response = await fetch("/api/research-chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        signal: controller.signal,
        body: JSON.stringify({
          message: `Please provide a comprehensive summary of the following search results for the query "${session.query}": ${JSON.stringify(session.results.map((r) => ({ title: r.title, snippet: r.snippet })))}`,
          history: [],
          model: "mistral",
          enableWebSearch: false,
        }),
      })

      clearTimeout(timeoutId)

      if (response.ok) {
        const data = await response.json()
        const summary = data.history.find((msg: any) => msg.role === "assistant")?.content

        if (summary) {
          // Update session with summary
          setResearchSessions((prev) => prev.map((s) => (s.id === session.id ? { ...s, summary } : s)))

          if (selectedSession?.id === session.id) {
            setSelectedSession({ ...session, summary })
          }
        }
      }
    } catch (error) {
      console.error("Summary generation failed:", error)
      if (error.name === 'AbortError') {
        console.warn("Research request timed out after 5 minutes")
      }
    } finally {
      setIsGeneratingSummary(false)
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
  }

  const exportSession = (session: ResearchSession) => {
    const exportData = {
      query: session.query,
      timestamp: session.timestamp,
      summary: session.summary,
      results: session.results,
    }

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `research-${session.query.replace(/[^a-zA-Z0-9]/g, "-")}-${Date.now()}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const deleteSession = (sessionId: string) => {
    setResearchSessions((prev) => prev.filter((s) => s.id !== sessionId))
    if (selectedSession?.id === sessionId) {
      setSelectedSession(null)
      setCurrentResults([])
    }
  }

  return (
    <Card className="bg-gray-900/50 backdrop-blur-sm border-green-500/30 h-[700px] flex flex-col">
      <div className="p-4 border-b border-green-500/30">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <Globe className="w-5 h-5 text-green-400" />
            <h2 className="text-xl font-semibold text-green-300">Research Assistant</h2>
          </div>
          <Badge variant="outline" className="border-green-500 text-green-400">
            {researchSessions.length} Sessions
          </Badge>
        </div>

        {/* Search Input */}
        <div className="flex space-x-2">
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyPress={(e) => e.key === "Enter" && performSearch()}
            placeholder="Enter research query..."
            className="flex-1 bg-gray-800 border-gray-600 text-white placeholder-gray-400 focus:border-green-500"
            disabled={isSearching}
          />
          <Button
            onClick={performSearch}
            disabled={isSearching || !searchQuery.trim()}
            className="bg-green-600 hover:bg-green-700 text-white"
          >
            {isSearching ? (
              <div className="w-4 h-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <Search className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Sessions Sidebar */}
        <div className="w-1/3 border-r border-gray-700 p-4 overflow-y-auto">
          <h3 className="text-sm font-medium text-gray-300 mb-3">Research Sessions</h3>
          <div className="space-y-2">
            {researchSessions.map((session) => (
              <motion.div
                key={session.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className={`p-3 rounded-lg cursor-pointer transition-colors ${
                  selectedSession?.id === session.id
                    ? "bg-green-600/20 border border-green-500/50"
                    : "bg-gray-800/50 hover:bg-gray-800/70"
                }`}
                onClick={() => {
                  setSelectedSession(session)
                  setCurrentResults(session.results)
                }}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">{session.query}</p>
                    <p className="text-xs text-gray-400 mt-1">
                      {session.results.length} results • {session.timestamp.toLocaleDateString()}
                    </p>
                    {session.summary && (
                      <Badge variant="outline" className="mt-1 text-xs border-blue-500 text-blue-400">
                        <BookOpen className="w-2 h-2 mr-1" />
                        Summary
                      </Badge>
                    )}
                  </div>
                  <Button
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteSession(session.id)
                    }}
                    size="sm"
                    variant="ghost"
                    className="text-gray-400 hover:text-red-400 h-6 w-6 p-0"
                  >
                    <Trash2 className="w-3 h-3" />
                  </Button>
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Results Panel */}
        <div className="flex-1 flex flex-col">
          {selectedSession ? (
            <>
              {/* Session Header */}
              <div className="p-4 border-b border-gray-700">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-medium text-white">{selectedSession.query}</h3>
                    <p className="text-sm text-gray-400">
                      {selectedSession.results.length} results • {selectedSession.timestamp.toLocaleString()}
                    </p>
                  </div>
                  <div className="flex space-x-2">
                    <Button
                      onClick={() => generateSummary(selectedSession)}
                      disabled={isGeneratingSummary || !!selectedSession.summary}
                      size="sm"
                      className="bg-blue-600 hover:bg-blue-700 text-white"
                    >
                      {isGeneratingSummary ? (
                        <RefreshCw className="w-3 h-3 animate-spin" />
                      ) : (
                        <BookOpen className="w-3 h-3" />
                      )}
                    </Button>
                    <Button
                      onClick={() => exportSession(selectedSession)}
                      size="sm"
                      variant="outline"
                      className="bg-gray-800 border-gray-600 text-gray-300"
                    >
                      <Download className="w-3 h-3" />
                    </Button>
                  </div>
                </div>
              </div>

              {/* Summary Section */}
              {selectedSession.summary && (
                <div className="p-4 border-b border-gray-700 bg-blue-900/10">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-medium text-blue-300">AI Summary</h4>
                    <Button
                      onClick={() => copyToClipboard(selectedSession.summary!)}
                      size="sm"
                      variant="ghost"
                      className="text-gray-400 hover:text-white h-6 w-6 p-0"
                    >
                      <Copy className="w-3 h-3" />
                    </Button>
                  </div>
                  <p className="text-sm text-gray-300 leading-relaxed">{selectedSession.summary}</p>
                </div>
              )}

              {/* Results List */}
              <div className="flex-1 overflow-y-auto p-4">
                <div className="space-y-3">
                  <AnimatePresence>
                    {currentResults.map((result, index) => (
                      <motion.div
                        key={index}
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: index * 0.1 }}
                        className="bg-gray-800/50 rounded-lg p-4 border border-gray-700 hover:border-gray-600 transition-colors"
                      >
                        <div className="flex items-start justify-between mb-2">
                          <h4 className="text-sm font-medium text-white line-clamp-2 flex-1">{result.title}</h4>
                          <Button
                            onClick={() => copyToClipboard(`${result.title}\n${result.snippet}\n${result.url}`)}
                            size="sm"
                            variant="ghost"
                            className="text-gray-400 hover:text-white h-6 w-6 p-0 ml-2"
                          >
                            <Copy className="w-3 h-3" />
                          </Button>
                        </div>
                        <p className="text-sm text-gray-400 mb-3 line-clamp-3">{result.snippet}</p>
                        <div className="flex items-center justify-between">
                          <a
                            href={result.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm text-green-400 hover:text-green-300 flex items-center space-x-1 truncate"
                          >
                            <span className="truncate max-w-64">{result.domain || result.url}</span>
                            <ExternalLink className="w-3 h-3 flex-shrink-0" />
                          </a>
                          <Badge variant="outline" className="text-xs border-gray-600 text-gray-400">
                            #{index + 1}
                          </Badge>
                        </div>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
                <div ref={resultsEndRef} />
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-gray-400">
                <Search className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p className="text-lg font-medium mb-2">Start Your Research</p>
                <p className="text-sm">Enter a search query to begin researching any topic</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}
