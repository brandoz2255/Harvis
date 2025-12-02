"use client"

import React from 'react'
import { Sparkles, Activity } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import AIAssistantPanel from './AIAssistantPanel'
import CodeExecutionPanel from './CodeExecutionPanel'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  type?: 'voice' | 'text' | 'code' | 'command'
  reasoning?: string
}

interface ExecutionResult {
  stdout: string
  stderr: string
  exit_code: number
  started_at: number
  finished_at: number
  command: string
}

interface RightTabsPanelProps {
  activeTab: 'assistant' | 'execution'
  onTabChange: (tab: 'assistant' | 'execution') => void
  sessionId: string | null
  containerStatus?: 'running' | 'stopped' | 'starting' | 'stopping'
  selectedFile?: string | null
  isContainerRunning?: boolean
  
  // AI Assistant props
  chatMessages?: ChatMessage[]
  isAIProcessing?: boolean
  selectedModel?: string
  availableModels?: Array<{ name: string; provider: string; type: string }>
  onSendMessage?: (message: string) => Promise<void>
  onModelChange?: (model: string) => void
  
  // Code Execution props
  executionHistory?: ExecutionResult[]
  isExecuting?: boolean
  onExecute?: (command: string) => Promise<void>
  
  className?: string
}

/**
 * RightTabsPanel Component
 * 
 * Manages the right sidebar with tabs for AI Assistant and Code Execution.
 * Features:
 * - Tab headers with visual highlighting
 * - Switches content based on active tab
 * - Mounts AIAssistantPanel in assistant tab
 * - Mounts CodeExecutionPanel in execution tab
 */
export default function RightTabsPanel({
  activeTab,
  onTabChange,
  sessionId,
  containerStatus = 'stopped',
  selectedFile = null,
  isContainerRunning = false,
  chatMessages = [],
  isAIProcessing = false,
  selectedModel = 'mistral',
  availableModels = [],
  onSendMessage = async () => {},
  onModelChange = () => {},
  executionHistory = [],
  isExecuting = false,
  onExecute = async () => {},
  className = ''
}: RightTabsPanelProps) {
  return (
    <Card className={`bg-gray-900/50 backdrop-blur-sm border-purple-500/30 h-full flex flex-col ${className}`}>
      {/* Tab Headers */}
      <div className="p-4 border-b border-purple-500/30 flex-shrink-0">
        <div className="flex space-x-2">
          <Button
            onClick={() => onTabChange('assistant')}
            size="sm"
            className={`flex-1 transition-all duration-200 ${
              activeTab === 'assistant'
                ? 'bg-purple-600 text-white shadow-lg shadow-purple-500/50 scale-105'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700 border border-gray-600'
            }`}
          >
            <Sparkles className="w-4 h-4 mr-2" />
            AI Assistant
          </Button>
          <Button
            onClick={() => onTabChange('execution')}
            size="sm"
            className={`flex-1 transition-all duration-200 ${
              activeTab === 'execution'
                ? 'bg-green-600 text-white shadow-lg shadow-green-500/50 scale-105'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700 border border-gray-600'
            }`}
          >
            <Activity className="w-4 h-4 mr-2" />
            Code Execution
          </Button>
        </div>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-hidden flex flex-col min-h-0">
        {activeTab === 'assistant' ? (
          // AI Assistant Tab
          <AIAssistantPanel
            sessionId={sessionId}
            containerStatus={containerStatus}
            selectedFile={selectedFile}
            onSendMessage={onSendMessage}
            messages={chatMessages}
            isProcessing={isAIProcessing}
            selectedModel={selectedModel}
            availableModels={availableModels}
            onModelChange={onModelChange}
            className="h-full"
          />
        ) : (
          // Code Execution Tab
          <CodeExecutionPanel
            sessionId={sessionId}
            isContainerRunning={isContainerRunning}
            executionHistory={executionHistory}
            onExecute={onExecute}
            isExecuting={isExecuting}
            className="h-full"
          />
        )}
      </div>
    </Card>
  )
}
