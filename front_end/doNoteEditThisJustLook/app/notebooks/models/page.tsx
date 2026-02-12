"use client"

import { useEffect, useMemo, useState } from "react"
import { Bot, Plus, Star, Loader2, Check } from "lucide-react"
import { Button } from "@/components/ui/button"

export default function NotebookModelsPage() {
  const [models, setModels] = useState<any[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [defaultNotebookModel, setDefaultNotebookModel] = useState<string>("")
  const [customModel, setCustomModel] = useState<string>("")
  const [customModels, setCustomModels] = useState<string[]>([])

  const load = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const token = localStorage.getItem("token")
      const res = await fetch("/api/models/available", {
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `Failed (${res.status})`)
      }
      const data = await res.json()
      setModels(data.models || [])
    } catch (e: any) {
      setError(e?.message || "Failed to load models")
      setModels([])
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    const saved = localStorage.getItem("notebook_default_model") || ""
    setDefaultNotebookModel(saved)
    const savedCustom = JSON.parse(localStorage.getItem("notebook_custom_models") || "[]")
    setCustomModels(Array.isArray(savedCustom) ? savedCustom : [])
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const allModelNames = useMemo(() => {
    const fromBackend = (models || []).map((m: any) => m.name).filter(Boolean)
    const set = new Set<string>([...fromBackend, ...customModels])
    return Array.from(set)
  }, [models, customModels])

  const handleSetDefault = (name: string) => {
    setDefaultNotebookModel(name)
    localStorage.setItem("notebook_default_model", name)
  }

  const handleAddCustom = () => {
    const v = customModel.trim()
    if (!v) return
    const next = Array.from(new Set([...customModels, v]))
    setCustomModels(next)
    localStorage.setItem("notebook_custom_models", JSON.stringify(next))
    setCustomModel("")
  }

  return (
    <div className="h-full w-full overflow-y-auto p-6 bg-[#0a0a0a]">
      <div className="max-w-4xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-white">Models</h1>
            <p className="text-sm text-gray-400">
              This page exists to manage which AI models HARVIS can see, and which model notebooks use by default.
            </p>
          </div>
          <Button
            className="bg-blue-600 hover:bg-blue-700"
            onClick={load}
            disabled={isLoading}
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Refresh"}
          </Button>
        </div>

        {error && (
          <div className="p-3 bg-red-900/30 border border-red-800 rounded text-sm text-red-200">
            {error}
          </div>
        )}

        <div className="border border-gray-800 rounded-lg p-4 bg-gray-900/40 space-y-3">
          <div className="text-sm font-semibold text-white">Notebook defaults</div>
          <div className="text-xs text-gray-400">
            Default model used when chatting in notebooks.
          </div>
          <select
            value={defaultNotebookModel}
            onChange={(e) => handleSetDefault(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white"
          >
            <option value="">(use app default)</option>
            {allModelNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>

        <div className="border border-gray-800 rounded-lg p-4 bg-gray-900/40 space-y-3">
          <div className="text-sm font-semibold text-white">Available models (from system)</div>
          {isLoading ? (
            <div className="text-sm text-gray-400 flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          ) : models.length === 0 ? (
            <div className="text-sm text-gray-500">
              No models reported by the system.
            </div>
          ) : (
            <div className="space-y-2">
              {models.map((m: any) => (
                <div
                  key={m.name}
                  className="flex items-center justify-between border border-gray-800 rounded px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="text-sm text-white truncate">
                      {m.displayName || m.name}
                    </div>
                    <div className="text-xs text-gray-500">
                      {m.name} {m.size ? `• ${m.size}` : ""} {m.status ? `• ${m.status}` : ""}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-blue-300 hover:text-blue-200"
                    onClick={() => handleSetDefault(m.name)}
                  >
                    {defaultNotebookModel === m.name ? (
                      <>
                        <Check className="h-4 w-4 mr-1" /> Default
                      </>
                    ) : (
                      "Set default"
                    )}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="border border-gray-800 rounded-lg p-4 bg-gray-900/40 space-y-3">
          <div className="text-sm font-semibold text-white">Add custom model name</div>
          <div className="flex gap-2">
            <input
              value={customModel}
              onChange={(e) => setCustomModel(e.target.value)}
              placeholder="e.g. llama3.2:latest"
              className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-500"
            />
            <Button onClick={handleAddCustom} className="bg-blue-600 hover:bg-blue-700">
              <Plus className="h-4 w-4 mr-2" />
              Add
            </Button>
          </div>
          {customModels.length > 0 && (
            <div className="text-xs text-gray-400">
              Saved custom models: {customModels.join(", ")}
            </div>
          )}
          <div className="text-xs text-gray-500">
            Note: “custom models” are stored in your browser for now; provider/API-key management will be wired next.
          </div>
        </div>
      </div>
    </div>
  )
}

