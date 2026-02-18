"use client"

import { useState, useEffect, useCallback, useRef } from 'react'
import { Brain, RefreshCw, CheckCircle, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiClient, getAuthHeaders } from '@/lib/api'

interface ModelInfo {
    name: string
    displayName: string
    status: 'available' | 'loading' | 'error' | 'offline'
    size?: string
}

interface ModelSelectorProps {
    selectedModel?: string
    onModelChange: (model: string) => void
    className?: string
}

export default function ModelSelector({
    selectedModel,
    onModelChange,
    className = ''
}: ModelSelectorProps) {
    const [models, setModels] = useState<ModelInfo[]>([])
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const isFetchingModels = useRef(false)

    const fetchModels = useCallback(async () => {
        if (isFetchingModels.current) return
        isFetchingModels.current = true
        setIsLoading(true)
        setError(null)

        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 10000) // 10s timeout for model list

        try {
            const response = await fetch('/api/models', {
                signal: controller.signal,
                headers: {
                    ...getAuthHeaders(),
                }
            })

            if (!response.ok) throw new Error('Failed to fetch models')
            const data = await response.json()

            const modelInfos: ModelInfo[] = (Array.isArray(data) ? data : data.models || []).map((model: any) => ({
                name: model.name || model,
                displayName: model.displayName || model.name || model,
                status: model.status || 'available',
                size: model.size,
            }))

            setModels(modelInfos)

            // Auto-select first available model if none selected
            if (!selectedModel && modelInfos.length > 0) {
                const firstAvailable = modelInfos.find(m => m.status === 'available')
                if (firstAvailable) {
                    onModelChange(firstAvailable.name)
                }
            }

        } catch (err) {
            if ((err as Error).name === 'AbortError') {
                console.warn('[ModelSelector] Fetch aborted or timed out')
            } else {
                setError(err instanceof Error ? err.message : 'Failed to load models')
            }
            if (models.length === 0) {
                setModels([
                    {
                        name: 'offline-mode',
                        displayName: 'Offline Mode',
                        status: 'offline',
                    }
                ])
            }
        } finally {
            clearTimeout(timeoutId)
            setIsLoading(false)
            isFetchingModels.current = false
        }
    }, [selectedModel, onModelChange, models.length])

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
        </div>
    )
}
