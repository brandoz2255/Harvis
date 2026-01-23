'use client'

import { useState } from 'react'
import { NotebookSource } from '@/stores/notebookStore'
import {
  File,
  FileText,
  Globe,
  Headphones,
  Youtube,
  Image,
  Loader2,
  CheckCircle,
  AlertCircle,
  Clock,
  Trash2,
  Wand2,
  MoreVertical,
  Eye,
  Download,
  ExternalLink
} from 'lucide-react'

// Source type icons mapping
const sourceTypeIcons: Record<string, { icon: React.ReactNode; color: string }> = {
  pdf: { icon: <File className="w-5 h-5" />, color: 'text-red-400' },
  text: { icon: <FileText className="w-5 h-5" />, color: 'text-blue-400' },
  url: { icon: <Globe className="w-5 h-5" />, color: 'text-green-400' },
  markdown: { icon: <FileText className="w-5 h-5" />, color: 'text-purple-400' },
  doc: { icon: <File className="w-5 h-5" />, color: 'text-blue-400' },
  transcript: { icon: <FileText className="w-5 h-5" />, color: 'text-yellow-400' },
  audio: { icon: <Headphones className="w-5 h-5" />, color: 'text-orange-400' },
  youtube: { icon: <Youtube className="w-5 h-5" />, color: 'text-red-500' },
  image: { icon: <Image className="w-5 h-5" />, color: 'text-pink-400' },
}

// Status indicators
const getStatusIndicator = (status: string) => {
  switch (status) {
    case 'pending':
      return { icon: <Clock className="w-3.5 h-3.5" />, color: 'text-gray-400', label: 'Pending' }
    case 'processing':
      return { icon: <Loader2 className="w-3.5 h-3.5 animate-spin" />, color: 'text-blue-400', label: 'Processing' }
    case 'ready':
      return { icon: <CheckCircle className="w-3.5 h-3.5" />, color: 'text-green-400', label: 'Ready' }
    case 'error':
      return { icon: <AlertCircle className="w-3.5 h-3.5" />, color: 'text-red-400', label: 'Error' }
    default:
      return { icon: <Clock className="w-3.5 h-3.5" />, color: 'text-gray-400', label: status }
  }
}

interface SourceCardProps {
  source: NotebookSource
  isSelected?: boolean
  viewMode?: 'grid' | 'list'
  onSelect?: () => void
  onDelete?: () => void
  onTransform?: () => void
  onView?: () => void
}

export default function SourceCard({
  source,
  isSelected = false,
  viewMode = 'grid',
  onSelect,
  onDelete,
  onTransform,
  onView,
}: SourceCardProps) {
  const [showMenu, setShowMenu] = useState(false)

  const typeInfo = sourceTypeIcons[source.type] || { icon: <FileText className="w-5 h-5" />, color: 'text-gray-400' }
  const statusInfo = getStatusIndicator(source.status)

  const title = source.title || source.original_filename || 'Untitled'

  // Format date
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }

  if (viewMode === 'list') {
    return (
      <div
        onClick={onSelect}
        className={`group flex items-center gap-4 p-3 rounded-lg cursor-pointer transition-all ${
          isSelected
            ? 'bg-blue-600/20 border border-blue-500/50'
            : 'bg-[#111111] border border-gray-800 hover:border-gray-700'
        }`}
      >
        {/* Checkbox */}
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onSelect}
          className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-blue-500"
          onClick={(e) => e.stopPropagation()}
        />

        {/* Icon */}
        <div className={`p-2 rounded-lg bg-gray-800/50 ${typeInfo.color}`}>
          {typeInfo.icon}
        </div>

        {/* Title and Info */}
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium text-white truncate">{title}</h3>
          <div className="flex items-center gap-3 mt-1">
            <span className={`flex items-center gap-1 text-xs ${statusInfo.color}`}>
              {statusInfo.icon}
              {statusInfo.label}
            </span>
            {source.status === 'ready' && source.chunk_count > 0 && (
              <span className="text-xs text-gray-500">{source.chunk_count} chunks</span>
            )}
            <span className="text-xs text-gray-500">{formatDate(source.created_at)}</span>
          </div>
          {source.error_message && (
            <p className="text-xs text-red-400 mt-1 truncate">{source.error_message}</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {source.status === 'ready' && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onTransform?.()
              }}
              className="p-1.5 text-gray-400 hover:text-purple-400 hover:bg-gray-800 rounded transition-colors"
              title="Transform with AI"
            >
              <Wand2 className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDelete?.()
            }}
            className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-gray-800 rounded transition-colors"
            title="Delete source"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    )
  }

  // Grid View
  return (
    <div
      onClick={onSelect}
      className={`group relative p-4 rounded-xl cursor-pointer transition-all ${
        isSelected
          ? 'bg-blue-600/20 border-2 border-blue-500'
          : 'bg-[#111111] border border-gray-800 hover:border-gray-700'
      }`}
    >
      {/* Selection Checkbox */}
      <div className="absolute top-3 left-3">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onSelect}
          className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-blue-500"
          onClick={(e) => e.stopPropagation()}
        />
      </div>

      {/* Menu Button */}
      <div className="absolute top-3 right-3">
        <button
          onClick={(e) => {
            e.stopPropagation()
            setShowMenu(!showMenu)
          }}
          className="p-1 text-gray-500 hover:text-white hover:bg-gray-800 rounded opacity-0 group-hover:opacity-100 transition-all"
        >
          <MoreVertical className="w-4 h-4" />
        </button>

        {showMenu && (
          <>
            <div
              className="fixed inset-0 z-10"
              onClick={(e) => {
                e.stopPropagation()
                setShowMenu(false)
              }}
            />
            <div className="absolute right-0 top-full mt-1 bg-[#1a1a1a] border border-gray-800 rounded-lg shadow-xl py-1 z-20 min-w-[140px]">
              {source.status === 'ready' && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onTransform?.()
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-2"
                >
                  <Wand2 className="w-4 h-4 text-purple-400" />
                  Transform
                </button>
              )}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onView?.()
                  setShowMenu(false)
                }}
                className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-2"
              >
                <Eye className="w-4 h-4" />
                View
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onDelete?.()
                  setShowMenu(false)
                }}
                className="w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-gray-800 flex items-center gap-2"
              >
                <Trash2 className="w-4 h-4" />
                Delete
              </button>
            </div>
          </>
        )}
      </div>

      {/* Icon */}
      <div className="flex justify-center pt-6 pb-4">
        <div className={`p-4 rounded-2xl bg-gray-800/50 ${typeInfo.color}`}>
          {typeInfo.icon}
        </div>
      </div>

      {/* Title */}
      <h3 className="text-sm font-medium text-white text-center truncate px-2">
        {title}
      </h3>

      {/* Status and Info */}
      <div className="flex items-center justify-center gap-2 mt-2">
        <span className={`flex items-center gap-1 text-xs ${statusInfo.color}`}>
          {statusInfo.icon}
          {statusInfo.label}
        </span>
        {source.status === 'ready' && source.chunk_count > 0 && (
          <>
            <span className="text-gray-600">|</span>
            <span className="text-xs text-gray-500">{source.chunk_count} chunks</span>
          </>
        )}
      </div>

      {/* Error Message */}
      {source.error_message && (
        <p className="text-xs text-red-400 text-center mt-2 truncate px-2">
          {source.error_message}
        </p>
      )}

      {/* Type Badge */}
      <div className="flex justify-center mt-3">
        <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded capitalize">
          {source.type}
        </span>
      </div>
    </div>
  )
}
