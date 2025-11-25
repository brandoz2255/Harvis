"use client"

import React, { useRef, useEffect } from "react"
import { X, Plus, Circle } from "lucide-react"

export interface EditorTab {
  id: string
  name: string
  path: string
  content: string
  isDirty: boolean
  language: string
}

interface EditorTabBarProps {
  tabs: EditorTab[]
  activeTabId: string | null
  onTabClick: (tabId: string) => void
  onTabClose: (tabId: string) => void
  onNewTab?: () => void
  className?: string
}

export default function EditorTabBar({
  tabs,
  activeTabId,
  onTabClick,
  onTabClose,
  onNewTab,
  className = ""
}: EditorTabBarProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to active tab when it changes
  useEffect(() => {
    if (activeTabId && scrollContainerRef.current) {
      const activeTabElement = scrollContainerRef.current.querySelector(
        `[data-tab-id="${activeTabId}"]`
      )
      if (activeTabElement) {
        activeTabElement.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
      }
    }
  }, [activeTabId])

  return (
    <div className={`flex items-center bg-gray-800 border-b border-gray-700 min-w-0 ${className}`}>
      {/* Tabs container with horizontal scroll */}
      <div
        ref={scrollContainerRef}
        className="flex-1 flex overflow-x-auto overscroll-contain scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-gray-800 min-w-0"
        style={{ scrollbarWidth: 'thin' }}
      >
        {tabs.map((tab) => (
          <div
            key={tab.id}
            data-tab-id={tab.id}
            className={`
              flex items-center gap-2 px-3 py-2 border-r border-gray-700 cursor-pointer
              min-w-[120px] max-w-[200px] flex-shrink-0
              ${activeTabId === tab.id 
                ? 'bg-gray-900 text-white border-b-2 border-b-blue-500' 
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
              }
            `}
            onClick={() => onTabClick(tab.id)}
          >
            {/* File icon or dirty indicator */}
            {tab.isDirty ? (
              <Circle className="w-3 h-3 fill-yellow-400 text-yellow-400 flex-shrink-0" />
            ) : (
              <div className="w-3 h-3 flex-shrink-0" />
            )}
            
            {/* Tab name */}
            <span className="flex-1 truncate text-sm">
              {tab.name}
            </span>
            
            {/* Close button */}
            <button
              onClick={(e) => {
                e.stopPropagation()
                onTabClose(tab.id)
              }}
              className="p-0.5 hover:bg-gray-600 rounded transition-colors flex-shrink-0"
              title="Close"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>

      {/* New tab button */}
      {onNewTab && (
        <button
          onClick={onNewTab}
          className="px-3 py-2 text-gray-400 hover:bg-gray-700 hover:text-gray-200 transition-colors border-l border-gray-700"
          title="New File"
        >
          <Plus className="w-4 h-4" />
        </button>
      )}
    </div>
  )
}
