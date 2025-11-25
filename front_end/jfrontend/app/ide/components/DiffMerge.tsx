'use client'

/**
 * Diff/Merge View
 * Side-by-side comparison of original and AI-proposed changes
 * Using Monaco DiffEditor
 */

import React, { useEffect, useRef, useState } from 'react'
import * as monaco from 'monaco-editor'
import { Button } from '@/components/ui/button'
import { X, Check, Edit, Loader2 } from 'lucide-react'
import { IDEDiffAPI } from '../lib/ide-api'
import { useToast } from '@/app/ide/components/Toast'

interface DiffMergeProps {
  sessionId: string
  filepath: string
  originalContent: string
  draftContent: string
  stats: {
    lines_added: number
    lines_removed: number
    hunks: number
  }
  baseEtag?: string
  onClose: () => void
  onApply: (content: string) => void
  onRebase?: () => void
}

export function DiffMerge({
  sessionId,
  filepath,
  originalContent,
  draftContent,
  stats,
  baseEtag,
  onClose,
  onApply,
  onRebase,
}: DiffMergeProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sliderContainerRef = useRef<HTMLDivElement>(null)
  const originalEditorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
  const modifiedEditorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
  const diffEditorRef = useRef<monaco.editor.IStandaloneDiffEditor | null>(null)
  const [isApplying, setIsApplying] = useState(false)
  const [editedContent, setEditedContent] = useState(draftContent)
  const [conflict, setConflict] = useState<{ current_etag: string; current_content: string } | null>(null)
  const [viewMode, setViewMode] = useState<'diff' | 'slider'>('diff')
  const [sliderPosition, setSliderPosition] = useState(50) // 0-100 percentage
  const toast = useToast()

  // Initialize diff editor
  useEffect(() => {
    if (!containerRef.current) return

    const originalModel = monaco.editor.createModel(
      originalContent,
      undefined,
      monaco.Uri.file(`original-${filepath}`)
    )
    const modifiedModel = monaco.editor.createModel(
      draftContent,
      undefined,
      monaco.Uri.file(`modified-${filepath}`)
    )

    if (viewMode === 'diff') {
      // Diff mode: use DiffEditor
      const diffEditor = monaco.editor.createDiffEditor(containerRef.current, {
        theme: 'vs-dark',
        automaticLayout: true,
        readOnly: false, // Allow editing in right pane
        renderSideBySide: true,
        scrollBeyondLastLine: false,
        minimap: { enabled: false },
        fontSize: 14,
        lineNumbers: 'on',
      })

      diffEditor.setModel({
        original: originalModel,
        modified: modifiedModel,
      })

      // Track changes to modified content
      modifiedModel.onDidChangeContent(() => {
        setEditedContent(modifiedModel.getValue())
      })

      diffEditorRef.current = diffEditor

      return () => {
        diffEditor.dispose()
        originalModel.dispose()
        modifiedModel.dispose()
      }
    } else {
      // Slider mode: use two stacked editors
      if (!sliderContainerRef.current) return

      const originalEditor = monaco.editor.create(containerRef.current, {
        theme: 'vs-dark',
        automaticLayout: true,
        readOnly: true,
        scrollBeyondLastLine: false,
        minimap: { enabled: false },
        fontSize: 14,
        lineNumbers: 'on',
      })
      originalEditor.setModel(originalModel)

      const modifiedEditor = monaco.editor.create(sliderContainerRef.current, {
        theme: 'vs-dark',
        automaticLayout: true,
        readOnly: false,
        scrollBeyondLastLine: false,
        minimap: { enabled: false },
        fontSize: 14,
        lineNumbers: 'on',
      })
      modifiedEditor.setModel(modifiedModel)

      // Track changes to modified content
      modifiedModel.onDidChangeContent(() => {
        setEditedContent(modifiedModel.getValue())
      })

      // Sync scrolling
      originalEditor.onDidScrollChange(() => {
        const scrollTop = originalEditor.getScrollTop()
        modifiedEditor.setScrollTop(scrollTop)
      })
      modifiedEditor.onDidScrollChange(() => {
        const scrollTop = modifiedEditor.getScrollTop()
        originalEditor.setScrollTop(scrollTop)
      })

      originalEditorRef.current = originalEditor
      modifiedEditorRef.current = modifiedEditor

      return () => {
        originalEditor.dispose()
        modifiedEditor.dispose()
        originalModel.dispose()
        modifiedModel.dispose()
      }
    }
  }, [originalContent, draftContent, filepath, viewMode])

  const handleAcceptAll = async () => {
    setIsApplying(true)
    setConflict(null)
    try {
      await IDEDiffAPI.apply(sessionId, filepath, editedContent, baseEtag)
      toast.success(`Changes applied to ${filepath}`)
      onApply(editedContent)
      onClose()
    } catch (error: any) {
      console.error('Failed to apply diff:', error)
      
      // Handle 409 conflict
      if (error.status === 409 && error.conflict) {
        setConflict(error.conflict)
        toast.error('File changed since proposal. Please review conflicts.')
        return
      }
      
      toast.error(`Failed to apply changes: ${error.message}`)
    } finally {
      setIsApplying(false)
    }
  }

  const handleRebase = () => {
    if (onRebase) {
      onRebase()
      setConflict(null)
    }
  }

  const handleReject = () => {
    onClose()
  }

  return (
    <div className="flex flex-col h-full bg-gray-900 border-l border-gray-700">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700 bg-gray-800">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Edit className="w-4 h-4 text-blue-400" />
            <span className="font-semibold text-white text-sm">
              Compare & Merge
            </span>
          </div>
          <div className="text-xs text-gray-400">
            {filepath.split('/').pop()}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* View Mode Toggle */}
          <div className="flex items-center gap-1 bg-gray-700 rounded p-1">
            <button
              onClick={() => setViewMode('diff')}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                viewMode === 'diff'
                  ? 'bg-gray-600 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
              title="Side-by-side diff view"
            >
              Diff
            </button>
            <button
              onClick={() => setViewMode('slider')}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                viewMode === 'slider'
                  ? 'bg-gray-600 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
              title="Slider compare view"
            >
              Slider
            </button>
          </div>

          {/* Stats */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-green-400">+{stats.lines_added}</span>
            <span className="text-red-400">-{stats.lines_removed}</span>
            <span className="text-gray-500">
              {stats.hunks} {stats.hunks === 1 ? 'hunk' : 'hunks'}
            </span>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={handleReject}
              className="h-7 px-2 text-xs"
              disabled={isApplying}
            >
              <X className="w-3 h-3 mr-1" />
              Reject
            </Button>
            <Button
              size="sm"
              onClick={handleAcceptAll}
              disabled={isApplying}
              className="h-7 px-2 text-xs bg-green-600 hover:bg-green-700"
            >
              {isApplying ? (
                <Loader2 className="w-3 h-3 mr-1 animate-spin" />
              ) : (
                <Check className="w-3 h-3 mr-1" />
              )}
              Accept All
            </Button>
          </div>
        </div>
      </div>

      {/* Labels */}
      <div className="flex border-b border-gray-700 bg-gray-850">
        <div className="flex-1 px-4 py-2 text-xs text-gray-400 border-r border-gray-700">
          Original
        </div>
        <div className="flex-1 px-4 py-2 text-xs text-gray-400">
          AI Proposed (Editable)
        </div>
      </div>

      {/* Diff Editor or Slider */}
      {viewMode === 'diff' ? (
        <div ref={containerRef} className="flex-1 overflow-hidden" />
      ) : (
        <div className="flex-1 overflow-hidden relative">
          {/* Original (left, clipped) */}
          <div
            ref={containerRef}
            className="absolute inset-0 overflow-hidden"
            style={{
              clipPath: `inset(0 ${100 - sliderPosition}% 0 0)`,
            }}
          />
          {/* Modified (right, clipped) */}
          <div
            ref={sliderContainerRef}
            className="absolute inset-0 overflow-hidden"
            style={{
              clipPath: `inset(0 0 0 ${sliderPosition}%)`,
            }}
          />
          {/* Slider handle */}
          <div
            className="absolute top-0 bottom-0 w-1 bg-blue-500 cursor-col-resize hover:bg-blue-400 z-10"
            style={{ left: `${sliderPosition}%` }}
            onMouseDown={(e) => {
              e.preventDefault()
              const startX = e.clientX
              const startPos = sliderPosition
              
              const handleMouseMove = (moveEvent: MouseEvent) => {
                const container = containerRef.current?.parentElement
                if (!container) return
                const rect = container.getBoundingClientRect()
                const newPos = Math.max(0, Math.min(100, ((moveEvent.clientX - rect.left) / rect.width) * 100))
                setSliderPosition(newPos)
              }
              
              const handleMouseUp = () => {
                document.removeEventListener('mousemove', handleMouseMove)
                document.removeEventListener('mouseup', handleMouseUp)
              }
              
              document.addEventListener('mousemove', handleMouseMove)
              document.addEventListener('mouseup', handleMouseUp)
            }}
          />
        </div>
      )}

      {/* Conflict Dialog */}
      {conflict && (
        <div className="px-4 py-3 border-t border-red-700 bg-red-950/30">
          <div className="flex items-start gap-3">
            <div className="flex-1">
              <div className="text-sm font-semibold text-red-400 mb-1">
                Conflict: File changed since proposal
              </div>
              <div className="text-xs text-gray-400 mb-2">
                The file has been modified. You can rebase the draft with the current content or manually merge.
              </div>
              <div className="flex gap-2">
                {onRebase && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleRebase}
                    className="h-7 px-2 text-xs border-yellow-600 text-yellow-400 hover:bg-yellow-600/20"
                  >
                    Rebase Draft
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConflict(null)}
                  className="h-7 px-2 text-xs"
                >
                  Dismiss
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      {!conflict && (
        <div className="px-4 py-2 border-t border-gray-700 bg-gray-800">
          <div className="text-xs text-gray-400">
            Edit the right pane to manually merge changes, then click Accept All
          </div>
        </div>
      )}
    </div>
  )
}



