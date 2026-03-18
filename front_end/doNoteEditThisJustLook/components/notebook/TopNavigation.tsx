'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  ArrowLeft,
  FileText,
  MessageSquare,
  Mic,
  Settings,
  Share2,
  MoreVertical,
  Edit2,
  Check,
  X
} from 'lucide-react'

export type NotebookView = 'sources' | 'chat' | 'podcast' | 'settings'

interface TopNavigationProps {
  notebookTitle: string
  currentView: NotebookView
  onViewChange: (view: NotebookView) => void
  onTitleChange?: (title: string) => void
  onShare?: () => void
  sourceCount?: number
}

const TABS = [
  { id: 'sources' as NotebookView, label: 'Sources', icon: FileText },
  { id: 'chat' as NotebookView, label: 'Chat', icon: MessageSquare },
  { id: 'podcast' as NotebookView, label: 'Podcast', icon: Mic },
  { id: 'settings' as NotebookView, label: 'Settings', icon: Settings },
]

export default function TopNavigation({
  notebookTitle,
  currentView,
  onViewChange,
  onTitleChange,
  onShare,
  sourceCount = 0,
}: TopNavigationProps) {
  const router = useRouter()
  const [isEditingTitle, setIsEditingTitle] = useState(false)
  const [titleInput, setTitleInput] = useState(notebookTitle)
  const [showMenu, setShowMenu] = useState(false)

  const handleTitleSave = () => {
    if (titleInput.trim() && titleInput !== notebookTitle) {
      onTitleChange?.(titleInput.trim())
    }
    setIsEditingTitle(false)
  }

  const handleTitleCancel = () => {
    setTitleInput(notebookTitle)
    setIsEditingTitle(false)
  }

  return (
    <div className="border-b border-gray-800 bg-[#0a0a0a]">
      {/* Top Row - Notebook Title and Actions */}
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          {/* Back Button */}
          <button
            onClick={() => router.push('/notebooks')}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
            title="Back to notebooks"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>

          {/* Notebook Title */}
          {isEditingTitle ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={titleInput}
                onChange={(e) => setTitleInput(e.target.value)}
                className="text-lg font-medium text-white bg-transparent border-b-2 border-blue-500 focus:outline-none px-1"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleTitleSave()
                  if (e.key === 'Escape') handleTitleCancel()
                }}
              />
              <button
                onClick={handleTitleSave}
                className="p-1 text-green-400 hover:text-green-300"
              >
                <Check className="w-4 h-4" />
              </button>
              <button
                onClick={handleTitleCancel}
                className="p-1 text-gray-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setIsEditingTitle(true)}
              className="flex items-center gap-2 group"
            >
              <h1 className="text-lg font-medium text-white group-hover:text-gray-300 transition-colors">
                {notebookTitle}
              </h1>
              <Edit2 className="w-3.5 h-3.5 text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
          )}

          {/* Source Count Badge */}
          <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
            {sourceCount} {sourceCount === 1 ? 'source' : 'sources'}
          </span>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={onShare}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-300 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
          >
            <Share2 className="w-4 h-4" />
            Share
          </button>

          <div className="relative">
            <button
              onClick={() => setShowMenu(!showMenu)}
              className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
            >
              <MoreVertical className="w-5 h-5" />
            </button>

            {showMenu && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setShowMenu(false)}
                />
                <div className="absolute right-0 top-full mt-1 bg-[#1a1a1a] border border-gray-800 rounded-lg shadow-xl py-1 z-20 min-w-[160px]">
                  <button
                    onClick={() => {
                      setIsEditingTitle(true)
                      setShowMenu(false)
                    }}
                    className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-2"
                  >
                    <Edit2 className="w-4 h-4" />
                    Rename notebook
                  </button>
                  <button
                    onClick={() => {
                      onShare?.()
                      setShowMenu(false)
                    }}
                    className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-2"
                  >
                    <Share2 className="w-4 h-4" />
                    Share notebook
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="flex items-center px-4">
        {TABS.map((tab) => {
          const Icon = tab.icon
          const isActive = currentView === tab.id

          return (
            <button
              key={tab.id}
              onClick={() => onViewChange(tab.id)}
              className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors relative ${
                isActive
                  ? 'text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}

              {/* Active Indicator */}
              {isActive && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500" />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
