"use client"

import React, { useState, useEffect, useCallback } from 'react'
import {
  Bot,
  Brain,
  CheckCircle,
  AlertCircle,
  Clock,
  RefreshCw,
  Sparkles
} from 'lucide-react'
import { Button } from '@/components/ui/button'

interface ModelInfo {
  name: string
  displayName: string
  status: 'available' | 'loading' | 'error' | 'offline'
  size?: string
  description?: string
  capabilities: string[]
}

interface AgentMode {
  id: 'assistant' | 'vibe'
  name: string
  description: string
  icon: React.ReactNode
  color: string
}

interface VibeModelSelectorProps {
  selectedModel?: string
  selectedAgent?: 'assistant' | 'vibe'
  onModelChange: (model: string) => void
  onAgentChange: (agent: 'assistant' | 'vibe') => void
  autoRefresh?: boolean
  className?: string
}

const agentModes: AgentMode[] = [
  {
    id: 'assistant',
    name: 'Assistant',
    description: 'General AI assistant for questions and help',
    icon: <Bot className="w-4 h-4" />,
    color: 'blue'
  },
  {
    id: 'vibe',
    name: 'Vibe Coder',
    description: 'Specialized coding agent for development tasks',
    icon: <Sparkles className="w-4 h-4" />,
    color: 'purple'
  }
]

export default function VibeModelSelector({
  selectedModel,
  selectedAgent = 'assistant',
  onModelChange,
  onAgentChange,
  autoRefresh = true,
  className = ''
}: VibeModelSelectorProps) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchModels = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const token = localStorage.getItem('token')
      if (!token) {
        throw new Error('Authentication required')
      }

      const response = await fetch('/api/models/available', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })

      if (!response.ok) {
        throw new Error('Failed to fetch models')
      }

      const data = await response.json()

      const modelInfos: ModelInfo[] = data.models?.map((model: Record<string, unknown>) => ({
        name: model.name || model,
        displayName: model.displayName || model.name || model,
        status: model.status || 'available',
        size: model.size,
        description: model.description,
        capabilities: model.capabilities || ['text-generation'],
      })) || []

      setModels(modelInfos)

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
          description: 'Limited functionality when backend is unavailable',
          capabilities: ['basic-editing']
        }
      ])
    } finally {
      setIsLoading(false)
    }
  }, [selectedModel, onModelChange])

  useEffect(() => {
    fetchModels()

    if (autoRefresh) {
      const interval = setInterval(fetchModels, 30000)
      return () => clearInterval(interval)
    }
  }, [autoRefresh, fetchModels])

  const availableModels = models.filter(m => m.status === 'available')
  const selectedModelInfo = models.find(m => m.name === selectedModel)

  return (
    <div className={`bg-background/50 backdrop-blur-sm border border-primary/30 rounded-lg p-3 ${className}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2">
          <Brain className="w-4 h-4 text-purple-400" />
          <h4 className="text-sm font-medium text-purple-300">AI Model</h4>
        </div>
        <Button
          onClick={fetchModels}
          disabled={isLoading}
          size="sm"
          variant="outline"
          className="bg-secondary border-border text-muted-foreground hover:bg-muted h-6 w-6 p-0"
        >
          <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {/* Agent Mode Selection */}
      <div className="mb-3">
        <div className="flex rounded-lg border border-border overflow-hidden">
          {agentModes.map((agent) => (
            <button
              key={agent.id}
              onClick={() => onAgentChange(agent.id)}
              className={`flex-1 py-1.5 px-2 text-xs font-medium transition-all flex items-center justify-center space-x-1 ${
                selectedAgent === agent.id
                  ? 'bg-purple-600 text-white'
                  : 'bg-muted text-muted-foreground hover:bg-secondary'
              }`}
            >
              {agent.icon}
              <span>{agent.name}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Model Dropdown */}
      <div className="mb-2">
        <select
          value={selectedModel || ''}
          onChange={(e) => onModelChange(e.target.value)}
          className="w-full bg-muted border border-border text-foreground text-sm rounded px-2 py-1.5 focus:outline-none focus:border-purple-500"
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
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {availableModels.length} available
        </span>
        {selectedModelInfo && (
          <span className="text-purple-400">
            {selectedModelInfo.displayName}
          </span>
        )}
      </div>
    </div>
  )
}
