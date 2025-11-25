'use client'

/**
 * Right Panel
 * Tabbed interface for AI Assistant and Code Execution
 */

import React, { useState } from 'react'
import { Code, Bot } from 'lucide-react'
import { AIAssistant } from './AIAssistant'

interface RightPanelProps {
  sessionId: string | null
  currentFilePath?: string
  codeOutput?: string
  onInsertAtCursor?: (text: string) => void
  copilotModel?: string
  onCopilotModelChange?: (model: string) => void
  copilotEnabled?: boolean
  onCopilotToggle?: () => void
}

type TabType = 'assistant' | 'execution'

export function RightPanel({
  sessionId,
  currentFilePath,
  codeOutput,
  onInsertAtCursor,
  copilotModel,
  onCopilotModelChange,
  copilotEnabled,
  onCopilotToggle,
}: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('assistant')

  return (
    <div className="flex flex-col h-full bg-gray-900">
      {/* Tab Bar */}
      <div className="flex border-b border-gray-700 bg-gray-850">
        <button
          onClick={() => setActiveTab('assistant')}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'assistant'
              ? 'text-white border-b-2 border-purple-500 bg-gray-900'
              : 'text-gray-400 hover:text-gray-300 hover:bg-gray-800'
          }`}
        >
          <Bot className="w-4 h-4" />
          AI Assistant
        </button>
        <button
          onClick={() => setActiveTab('execution')}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'execution'
              ? 'text-white border-b-2 border-purple-500 bg-gray-900'
              : 'text-gray-400 hover:text-gray-300 hover:bg-gray-800'
          }`}
        >
          <Code className="w-4 h-4" />
          Code Execution
        </button>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'assistant' && (
          <AIAssistant
            sessionId={sessionId}
            currentFilePath={currentFilePath}
            onInsertAtCursor={onInsertAtCursor}
            copilotModel={copilotModel}
            onCopilotModelChange={onCopilotModelChange}
            copilotEnabled={copilotEnabled}
            onCopilotToggle={onCopilotToggle}
          />
        )}
        {activeTab === 'execution' && (
          <div className="h-full p-4 overflow-auto">
            <div className="bg-black rounded p-3 font-mono text-sm text-green-400 min-h-[200px] whitespace-pre-wrap">
              {codeOutput || 'No output yet. Run some code to see results here.'}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}




