"use client"

import React from 'react'
import { Plus, X, Terminal } from 'lucide-react'

export interface TerminalTab {
  id: string
  name: string
  instanceId: string
}

interface TerminalTabBarProps {
  tabs: TerminalTab[]
  activeTabId: string | null
  onTabClick: (tabId: string) => void
  onTabClose: (tabId: string) => void
  onNewTab: () => void
  className?: string
}

export default function TerminalTabBar({
  tabs,
  activeTabId,
  onTabClick,
  onTabClose,
  onNewTab,
  className = ""
}: TerminalTabBarProps) {
  return (
    <div className={`flex items-center bg-gray-800 border-b border-gray-700 overflow-x-auto ${className}`}>
      {/* Terminal Tabs */}
      <div className="flex items-center flex-1 overflow-x-auto scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-gray-800">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`
              group flex items-center gap-2 px-3 py-2 border-r border-gray-700 cursor-pointer
              transition-colors min-w-[120px] max-w-[200px]
              ${activeTabId === tab.id 
                ? 'bg-gray-900 text-white' 
                : 'bg-gray-800 text-gray-400 hover:bg-gray-750 hover:text-gray-300'
              }
            `}
            onClick={() => onTabClick(tab.id)}
          >
            <Terminal className="w-3 h-3 flex-shrink-0" />
            <span className="text-sm truncate flex-1">{tab.name}</span>
            <button
              onClick={(e) => {
                e.stopPropagation()
                onTabClose(tab.id)
              }}
              className={`
                flex-shrink-0 p-0.5 rounded hover:bg-gray-700 transition-colors
                ${activeTabId === tab.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}
              `}
              title="Close terminal"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>

      {/* New Terminal Button */}
      <button
        onClick={onNewTab}
        className="flex items-center gap-1 px-3 py-2 text-gray-400 hover:text-white hover:bg-gray-700 transition-colors border-l border-gray-700"
        title="New Terminal"
      >
        <Plus className="w-4 h-4" />
        <span className="text-sm">New</span>
      </button>
    </div>
  )
}
