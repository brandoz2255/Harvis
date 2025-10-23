"use client"

import React, { useState } from "react"
import { motion } from "framer-motion"
import {
  FolderOpen,
  Search,
  GitBranch,
  Bot,
  ChevronLeft,
  ChevronRight,
  X
} from "lucide-react"
import MonacoVibeFileTree from "./MonacoVibeFileTree"
import AIChatPanel from "./AIChatPanel"

interface LeftSidebarProps {
  sessionId: string | null
  isContainerRunning: boolean
  onFileSelect: (filePath: string, content: string) => void
  chatMessages: Array<{
    role: 'user' | 'assistant'
    content: string
    timestamp: Date
    reasoning?: string
  }>
  isAIProcessing: boolean
  selectedModel: string
  availableModels: Array<{
    name: string
    provider: string
    type: string
  }>
  onSendMessage: (message: string) => void
  onModelChange: (model: string) => void
  newFileButton?: React.ReactNode
  className?: string
}

type SidebarTab = 'explorer' | 'search' | 'git' | 'ai'

export default function LeftSidebar({
  sessionId,
  isContainerRunning,
  onFileSelect,
  chatMessages,
  isAIProcessing,
  selectedModel,
  availableModels,
  onSendMessage,
  onModelChange,
  newFileButton,
  className = ""
}: LeftSidebarProps) {
  const [activeTab, setActiveTab] = useState<SidebarTab>('explorer')
  const [isCollapsed, setIsCollapsed] = useState(false)

  const tabs = [
    { id: 'explorer' as const, icon: FolderOpen, label: 'Explorer' },
    { id: 'search' as const, icon: Search, label: 'Search' },
    { id: 'git' as const, icon: GitBranch, label: 'Source Control' },
    { id: 'ai' as const, icon: Bot, label: 'AI Chat' }
  ]

  const renderTabContent = () => {
    switch (activeTab) {
      case 'explorer':
        return (
          <div className="h-full">
            {sessionId ? (
              <MonacoVibeFileTree
                sessionId={sessionId}
                isContainerRunning={isContainerRunning}
                onFileSelect={onFileSelect}
                currentDir=""
                newFileButton={newFileButton}
                className="h-full"
              />
            ) : (
              <div className="h-full flex items-center justify-center text-gray-400 text-sm">
                <p>No session selected</p>
              </div>
            )}
          </div>
        )
      
      case 'search':
        return (
          <div className="h-full flex items-center justify-center text-gray-400">
            <div className="text-center">
              <Search className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p className="text-sm">Search functionality</p>
              <p className="text-xs mt-2">Coming soon</p>
            </div>
          </div>
        )
      
      case 'git':
        return (
          <div className="h-full flex items-center justify-center text-gray-400">
            <div className="text-center">
              <GitBranch className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p className="text-sm">Source Control</p>
              <p className="text-xs mt-2">Coming soon</p>
            </div>
          </div>
        )
      
      case 'ai':
        return (
          <div className="h-full">
            <AIChatPanel
              chatMessages={chatMessages}
              isAIProcessing={isAIProcessing}
              selectedModel={selectedModel}
              availableModels={availableModels}
              onSendMessage={onSendMessage}
              onModelChange={onModelChange}
              className="h-full"
            />
          </div>
        )
      
      default:
        return null
    }
  }

  if (isCollapsed) {
    return (
      <div className={`h-full bg-gray-800 border-r border-gray-700 flex flex-col ${className}`}>
        {/* Collapsed sidebar with just icons */}
        <div className="flex flex-col">
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`
                  p-3 border-b border-gray-700 transition-colors
                  ${activeTab === tab.id 
                    ? 'bg-blue-600 text-white' 
                    : 'text-gray-400 hover:text-white hover:bg-gray-700'
                  }
                `}
                title={tab.label}
              >
                <Icon className="w-5 h-5" />
              </button>
            )
          })}
        </div>
        
        {/* Expand button */}
        <button
          onClick={() => setIsCollapsed(false)}
          className="p-3 border-t border-gray-700 text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
          title="Expand sidebar"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
      </div>
    )
  }

  return (
    <div className={`h-full bg-gray-800 border-r border-gray-700 flex flex-col ${className}`}>
      {/* Tab Navigation */}
      <div className="flex border-b border-gray-700">
        {tabs.map((tab) => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                flex-1 flex items-center justify-center p-3 transition-colors
                ${activeTab === tab.id 
                  ? 'bg-blue-600 text-white' 
                  : 'text-gray-400 hover:text-white hover:bg-gray-700'
                }
              `}
              title={tab.label}
            >
              <Icon className="w-4 h-4" />
            </button>
          )
        })}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-hidden">
        {renderTabContent()}
      </div>

      {/* Collapse button */}
      <button
        onClick={() => setIsCollapsed(true)}
        className="p-3 border-t border-gray-700 text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
        title="Collapse sidebar"
      >
        <ChevronLeft className="w-5 h-5" />
      </button>
    </div>
  )
}
