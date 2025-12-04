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
  X,
  Circle,
  Github
} from "lucide-react"
import MonacoVibeFileTree from "./MonacoVibeFileTree"
import AIChatPanel from "./AIChatPanel"
import { GitHubStatus } from "./GitHubStatus"
import { GitHubRepoList } from "./GitHubRepoList"

interface LeftSidebarProps {
  sessionId: string | null
  sessionName?: string
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
  className?: string
}

type SidebarTab = 'explorer' | 'search' | 'git' | 'ai'

export default function LeftSidebar({
  sessionId,
  sessionName,
  isContainerRunning,
  onFileSelect,
  chatMessages,
  isAIProcessing,
  selectedModel,
  availableModels,
  onSendMessage,
  onModelChange,
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
          <div className="h-full flex flex-col">
            <div className="flex flex-col gap-3 p-4 border-b border-gray-700">
              <div className="flex items-center gap-2">
                <GitBranch className="w-5 h-5 text-gray-400" />
                <h3 className="font-medium text-gray-200">Source Control</h3>
              </div>
              <div className="flex items-center">
                <GitHubStatus />
              </div>
            </div>

            {/* GitHub Repository List */}
            <div className="flex-1 overflow-hidden">
              {sessionId ? (
                <GitHubRepoList
                  sessionId={sessionId}
                  onRepoCloned={() => {
                    // Optionally refresh file tree or show notification
                    console.log('Repository cloned successfully')
                  }}
                />
              ) : (
                <div className="h-full flex items-center justify-center text-gray-400 text-sm">
                  <p>No session selected</p>
                </div>
              )}
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
      <div className={`h-full bg-gray-800 border-r border-gray-700 flex flex-col w-12 ${className}`}>
        {/* Collapsed sidebar with just icons */}
        <div className="flex flex-col">
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => {
                  setActiveTab(tab.id)
                  setIsCollapsed(false) // Expand when clicking a tab
                }}
                className={`
                  p-3 border-b border-gray-700 transition-colors relative group
                  ${activeTab === tab.id
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-gray-700'
                  }
                `}
                title={tab.label}
              >
                <Icon className="w-5 h-5" />
                {/* Tooltip */}
                <div className="absolute left-full ml-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-50 pointer-events-none">
                  {tab.label}
                </div>
              </button>
            )
          })}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Session status indicator */}
        {sessionId && (
          <div className="p-2 border-t border-gray-700 flex flex-col items-center gap-1" title={sessionName || 'Session active'}>
            <Circle className={`w-3 h-3 ${isContainerRunning ? 'text-green-400 fill-green-400' : 'text-gray-500 fill-gray-500'}`} />
            <span className="text-[10px] text-gray-400 writing-mode-vertical transform rotate-180" style={{ writingMode: 'vertical-rl' }}>
              {sessionName ? (sessionName.length > 12 ? sessionName.slice(0, 12) + '…' : sessionName) : 'Session'}
            </span>
          </div>
        )}

        {/* Expand button */}
        <button
          onClick={() => setIsCollapsed(false)}
          className="p-3 border-t border-gray-700 text-gray-400 hover:text-white hover:bg-gray-700 transition-colors flex items-center justify-center"
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
