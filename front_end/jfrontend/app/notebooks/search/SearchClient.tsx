"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Search, Loader2 } from "lucide-react"

export default function SearchClient() {
  const searchParams = useSearchParams()
  const urlQuery = searchParams.get("q") || ""

  const [query, setQuery] = useState(urlQuery)
  const [searchType, setSearchType] = useState<"text" | "vector">("text")
  const [searchSources, setSearchSources] = useState(true)
  const [searchNotes, setSearchNotes] = useState(true)
  const [minimumScore, setMinimumScore] = useState(0.2)

  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<any[]>([])

  const runSearch = useCallback(async () => {
    const q = query.trim()
    if (!q) return

    setIsLoading(true)
    setError(null)
    try {
      const token = localStorage.getItem("token")
      const res = await fetch("/api/notebooks/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          query: q,
          type: searchType,
          limit: 100,
          search_sources: searchSources,
          search_notes: searchNotes,
          minimum_score: minimumScore,
        }),
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `Search failed (${res.status})`)
      }

      const data = await res.json()
      setResults(data.results || [])
    } catch (e: any) {
      setError(e?.message || "Search failed")
      setResults([])
    } finally {
      setIsLoading(false)
    }
  }, [query, searchType, searchSources, searchNotes, minimumScore])

  useEffect(() => {
    if (urlQuery && urlQuery !== query) {
      setQuery(urlQuery)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery])

  useEffect(() => {
    if (urlQuery) {
      runSearch()
    }
  }, [urlQuery, runSearch])

  const resultsLabel = useMemo(() => {
    if (isLoading) return "Searching…"
    if (!query.trim()) return "Enter a query to search."
    return `Results (${results.length})`
  }, [isLoading, query, results.length])

  return (
    <div className="h-full w-full overflow-y-auto p-6 bg-[#0a0a0a]">
      <div className="max-w-4xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">Search</h1>
          <p className="text-sm text-gray-400">
            Query across your notebooks using text or vector search.
          </p>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="flex items-center gap-3 mb-4">
            <Search className="h-4 w-4 text-gray-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="What are you looking for?"
              className="flex-1 bg-transparent text-white placeholder-gray-500 focus:outline-none"
              onKeyDown={(e) => {
                if (e.key === "Enter") runSearch()
              }}
            />
            <button
              onClick={runSearch}
              className="px-3 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50"
              disabled={!query.trim() || isLoading}
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
            </button>
          </div>

          <div className="flex flex-wrap gap-4 text-xs text-gray-400">
            <div className="flex items-center gap-2">
              <span>Search type:</span>
              <button
                onClick={() => setSearchType("text")}
                className={`px-2 py-1 rounded ${
                  searchType === "text" ? "bg-blue-600 text-white" : "bg-gray-800"
                }`}
              >
                Text
              </button>
              <button
                onClick={() => setSearchType("vector")}
                className={`px-2 py-1 rounded ${
                  searchType === "vector" ? "bg-blue-600 text-white" : "bg-gray-800"
                }`}
              >
                Vector
              </button>
            </div>

            <div className="flex items-center gap-3">
              <span>Search in:</span>
              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={searchSources}
                  onChange={(e) => setSearchSources(e.target.checked)}
                />
                Sources
              </label>
              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={searchNotes}
                  onChange={(e) => setSearchNotes(e.target.checked)}
                />
                Notes
              </label>
            </div>

            {searchType === "vector" && (
              <div className="flex items-center gap-2">
                <span>Min score:</span>
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  value={minimumScore}
                  onChange={(e) => setMinimumScore(Number(e.target.value))}
                  className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white"
                />
              </div>
            )}
          </div>
        </div>

        {error && (
          <div className="p-3 bg-red-900/30 border border-red-800 rounded text-sm text-red-200">
            {error}
          </div>
        )}

        <div className="space-y-3">
          <div className="text-sm text-gray-300">{resultsLabel}</div>
          {results.map((r, idx) => (
            <div
              key={`${r.kind}-${r.source_id || r.note_id || idx}`}
              className="border border-gray-800 rounded-lg p-4 bg-gray-900/40"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium text-white">
                  {r.title || "Untitled"}
                </div>
                <div className="text-xs text-gray-500">
                  {r.kind} • {r.notebook_title || r.notebook_id}
                  {typeof r.score === "number" ? ` • score ${r.score.toFixed(3)}` : ""}
                </div>
              </div>
              {r.snippet && (
                <div className="mt-2 text-sm text-gray-400 line-clamp-3">
                  {r.snippet}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}









