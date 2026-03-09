'use client'

import { useEffect, useState } from 'react'
import { Settings, CheckCircle2, XCircle, ExternalLink, RefreshCw } from 'lucide-react'
import { useNotebookStore } from '@/stores/notebookStore'
import OpenNotebookAPI from '@/lib/openNotebookApi'

export default function SettingsCompact() {
  const { isOpenNotebookAvailable, checkServiceHealth } = useNotebookStore()
  const [models, setModels] = useState<{ name: string; type: string }[]>([])
  const [isLoadingModels, setIsLoadingModels] = useState(false)
  const [isChecking, setIsChecking] = useState(false)

  useEffect(() => {
    handleRefresh()
    loadModels()
  }, [])

  const handleRefresh = async () => {
    setIsChecking(true)
    await checkServiceHealth()
    setIsChecking(false)
  }

  const loadModels = async () => {
    setIsLoadingModels(true)
    try {
      const resp = await OpenNotebookAPI.models.list()
      setModels(resp.models || [])
    } catch {
      setModels([])
    } finally {
      setIsLoadingModels(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 space-y-4">
        {/* Service Status */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-foreground">Service Status</h3>
            <button
              onClick={handleRefresh}
              disabled={isChecking}
              className="p-1 rounded text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isChecking ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <div className="flex items-center gap-2 px-3 py-2 bg-secondary rounded-md">
            {isOpenNotebookAvailable ? (
              <>
                <CheckCircle2 className="w-4 h-4 text-green-400" />
                <span className="text-sm text-green-400">Open Notebook service connected</span>
              </>
            ) : (
              <>
                <XCircle className="w-4 h-4 text-destructive" />
                <span className="text-sm text-destructive">Service unavailable</span>
              </>
            )}
          </div>
        </div>

        {/* Available Models */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-2">Available Models</h3>
          {isLoadingModels ? (
            <p className="text-xs text-muted-foreground">Loading models...</p>
          ) : models.length === 0 ? (
            <p className="text-xs text-muted-foreground">No models available</p>
          ) : (
            <div className="space-y-1">
              {models.map((m) => (
                <div key={m.name} className="flex items-center justify-between px-3 py-1.5 bg-secondary rounded-md">
                  <span className="text-sm text-foreground">{m.name}</span>
                  <span className="text-[10px] text-muted-foreground uppercase">{m.type}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Full Settings Link */}
        <a
          href="/open-notebook/settings"
          className="flex items-center gap-2 px-3 py-2 text-sm text-primary hover:underline"
        >
          <Settings className="w-4 h-4" />
          Open full settings
          <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </div>
  )
}
