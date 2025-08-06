"use client"

import React, { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Bot,
  Brain,
  Cpu,
  Zap,
  AlertCircle,
  CheckCircle,
  Clock,
  RefreshCw,
  Settings,
  ChevronDown,
  Sparkles
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'

interface ModelInfo {
  name: string
  displayName: string
  status: 'available' | 'loading' | 'error' | 'offline'
  size?: string
  description?: string
  capabilities: string[]
  performance?: {
    speed: number // 1-5 scale
    quality: number // 1-5 scale
    memory: number // MB
  }
  lastChecked?: Date
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
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showDetails, setShowDetails] = useState(false)

  // Fetch available models
  const fetchModels = async () => {
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
      
      // Transform backend data to ModelInfo format
      const modelInfos: ModelInfo[] = data.models?.map((model: any) => ({
        name: model.name || model,
        displayName: model.displayName || model.name || model,
        status: model.status || 'available',
        size: model.size,
        description: model.description,
        capabilities: model.capabilities || ['text-generation'],
        performance: model.performance || {
          speed: Math.floor(Math.random() * 5) + 1,
          quality: Math.floor(Math.random() * 5) + 1,
          memory: Math.floor(Math.random() * 2000) + 500
        },
        lastChecked: new Date()
      })) || []

      setModels(modelInfos)
      setLastUpdate(new Date())
      
      // Auto-select first available model if none selected
      if (!selectedModel && modelInfos.length > 0) {
        const firstAvailable = modelInfos.find(m => m.status === 'available')
        if (firstAvailable) {
          onModelChange(firstAvailable.name)
        }
      }
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load models')
      // Fallback models for offline/error state
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
  }

  // Auto-refresh models
  useEffect(() => {
    fetchModels()

    if (autoRefresh) {
      const interval = setInterval(fetchModels, 30000) // Refresh every 30 seconds
      return () => clearInterval(interval)
    }
  }, [autoRefresh])

  const getStatusColor = (status: ModelInfo['status']) => {
    switch (status) {
      case 'available': return 'text-green-400'
      case 'loading': return 'text-yellow-400'
      case 'error': return 'text-red-400'
      case 'offline': return 'text-gray-400'
      default: return 'text-gray-400'
    }
  }

  const getStatusIcon = (status: ModelInfo['status']) => {
    switch (status) {
      case 'available': return CheckCircle
      case 'loading': return Clock
      case 'error': return AlertCircle
      case 'offline': return AlertCircle
      default: return AlertCircle
    }
  }

  const renderPerformanceBar = (value: number, max: number = 5) => (
    <div className="flex space-x-1">
      {[...Array(max)].map((_, i) => (
        <div
          key={i}
          className={`w-2 h-2 rounded-full ${
            i < value ? 'bg-purple-400' : 'bg-gray-600'
          }`}
        />
      ))}
    </div>
  )

  const availableModels = models.filter(m => m.status === 'available')
  const selectedModelInfo = models.find(m => m.name === selectedModel)
  const selectedAgentInfo = agentModes.find(a => a.id === selectedAgent)

  return (
    <div className={`bg-gray-900/50 backdrop-blur-sm border border-purple-500/30 rounded-lg p-3 ${className}`}>
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
          className="bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600 h-6 w-6 p-0"
        >
          <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {/* Compact Agent Mode Selection */}
      <div className="mb-3">
        <div className="flex rounded-lg border border-gray-600 overflow-hidden">
          {agentModes.map((agent) => (
            <button
              key={agent.id}
              onClick={() => onAgentChange(agent.id)}
              className={`flex-1 py-1.5 px-2 text-xs font-medium transition-all flex items-center justify-center space-x-1 ${
                selectedAgent === agent.id
                  ? 'bg-purple-600 text-white'
                  : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              }`}
            >
              {agent.icon}
              <span>{agent.name}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Compact Model Dropdown */}
      <div className="mb-2">
        <select
          value={selectedModel || ''}
          onChange={(e) => onModelChange(e.target.value)}
          className="w-full bg-gray-800 border border-gray-600 text-gray-200 text-sm rounded px-2 py-1.5 focus:outline-none focus:border-purple-500"
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

      {/* Status and model info */}
      <div className="flex items-center justify-between text-xs text-gray-400">
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