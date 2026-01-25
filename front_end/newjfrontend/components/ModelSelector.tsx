"use client"

import { useState, useEffect, useCallback } from 'react'
import { Brain, RefreshCw, CheckCircle, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api'

interface ModelInfo {
    name: string
    displayName: string
    status: 'available' | 'loading' | 'error' | 'offline'
    size?: string
}

interface ModelSelectorProps {
    selectedModel?: string
    onModelChange: (model: string) => void
    lowVram: boolean
    onLowVramChange: (enabled: boolean) => void
    textOnly: boolean
    onTextOnlyChange: (enabled: boolean) => void
    className?: string
}

export default function ModelSelector({
    selectedModel,
    onModelChange,
    lowVram,
    onLowVramChange,
    textOnly,
    onTextOnlyChange,
    className = ''
}: ModelSelectorProps) {
    const [models, setModels] = useState<ModelInfo[]>([])
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const fetchModels = useCallback(async () => {
        setIsLoading(true)
        setError(null)

        try {
            const data = await apiClient.getAvailableModels()

            const modelInfos: ModelInfo[] = data.models?.map((model: any) => ({
                name: model.name || model,
                displayName: model.displayName || model.name || model,
                status: model.status || 'available',
                size: model.size,
            })) || []

            setModels(modelInfos)

            // Auto-select first available model if none selected
            if (!selectedModel && modelInfos.length > 0) {
                const firstAvailable = modelInfos.find(m => m.status === 'available')
                if (firstAvailable) {
                    onModelChange(firstAvailable.name)
                }
            }

        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load models')
            setModels([
                {
                    name: 'offline-mode',
                    displayName: 'Offline Mode',
                    status: 'offline',
                }
            ])
        } finally {
            setIsLoading(false)
        }
    }, [selectedModel, onModelChange])

    useEffect(() => {
        fetchModels()
        const interval = setInterval(fetchModels, 30000) // Refresh every 30 seconds
        return () => clearInterval(interval)
    }, [fetchModels])

    const availableModels = models.filter(m => m.status === 'available')

    return (
        <div className={`flex items-center gap-2 ${className}`}>
            <Brain className="h-4 w-4 text-muted-foreground" />
            <select
                value={selectedModel || ''}
                onChange={(e) => onModelChange(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isLoading}
            >
                {isLoading ? (
                    <option disabled>Loading models...</option>
                ) : error ? (
                    <option disabled>{error}</option>
                ) : (
                    <>
                        <option value="" disabled>Select a model</option>
                        {models.map((model) => (
                            <option
                                key={model.name}
                                value={model.name}
                                disabled={model.status !== 'available'}
                            >
                                {model.displayName} {model.size && `(${model.size})`}
                            </option>
                        ))}
                    </>
                )}
            </select>
            <Button
                onClick={fetchModels}
                disabled={isLoading}
                size="icon"
                variant="ghost"
                className="h-9 w-9"
            >
                <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            </Button>
            {availableModels.length > 0 && (
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                    <CheckCircle className="h-3 w-3 text-green-500" />
                    <span>{availableModels.length} available</span>
                </div>
            )}
            {error && (
                <div className="flex items-center gap-1 text-xs text-destructive">
                    <AlertCircle className="h-3 w-3" />
                    <span>Offline</span>
                </div>
            )}
            <div className="flex items-center gap-4 ml-4 border-l pl-4 border-border">
                <label className="flex items-center gap-2 cursor-pointer text-sm" title="Unloads LLM before loading TTS to prevent crashes on low memory devices">
                    <input
                        type="checkbox"
                        checked={lowVram}
                        onChange={(e) => onLowVramChange(e.target.checked)}
                        className="rounded border-input"
                    />
                    <span className="hidden sm:inline">Low VRAM</span>
                    <span className="sm:hidden">L-VRAM</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer text-sm" title="Disables TTS for faster responses and no audio">
                    <input
                        type="checkbox"
                        checked={textOnly}
                        onChange={(e) => onTextOnlyChange(e.target.checked)}
                        className="rounded border-input"
                    />
                    <span className="hidden sm:inline">Text Only</span>
                    <span className="sm:hidden">Text</span>
                </label>
            </div>
        </div>
    )
}
