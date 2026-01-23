'use client'

import { useState, useRef } from 'react'
import {
  X,
  Upload,
  Link,
  Globe,
  Youtube,
  Clipboard,
  FileText,
  Copy,
  Sparkles,
  BookOpen,
  Loader2
} from 'lucide-react'

interface AddSourceModalProps {
  isOpen: boolean
  onClose: () => void
  sourcesCount: number
  onFileUpload: (files: FileList) => Promise<void>
  onAddUrl: (url: string) => Promise<void>
  onAddText: (title: string, content: string) => Promise<void>
  onAddYouTube?: (url: string) => Promise<void>
}

export default function AddSourceModal({
  isOpen,
  onClose,
  sourcesCount,
  onFileUpload,
  onAddUrl,
  onAddText,
  onAddYouTube,
}: AddSourceModalProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showUrlInput, setShowUrlInput] = useState(false)
  const [showTextInput, setShowTextInput] = useState(false)
  const [showYouTubeInput, setShowYouTubeInput] = useState(false)
  const [urlValue, setUrlValue] = useState('')
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [textTitle, setTextTitle] = useState('')
  const [textContent, setTextContent] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)

  if (!isOpen) return null

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = e.dataTransfer.files
    if (files.length > 0) {
      setIsUploading(true)
      await onFileUpload(files)
      setIsUploading(false)
    }
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      setIsUploading(true)
      await onFileUpload(files)
      setIsUploading(false)
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleUrlSubmit = async () => {
    if (urlValue.trim()) {
      await onAddUrl(urlValue.trim())
      setUrlValue('')
      setShowUrlInput(false)
      onClose()
    }
  }

  const handleTextSubmit = async () => {
    if (textTitle.trim() && textContent.trim()) {
      await onAddText(textTitle.trim(), textContent.trim())
      setTextTitle('')
      setTextContent('')
      setShowTextInput(false)
      onClose()
    }
  }

  const handleYouTubeSubmit = async () => {
    if (youtubeUrl.trim() && onAddYouTube) {
      await onAddYouTube(youtubeUrl.trim())
      setYoutubeUrl('')
      setShowYouTubeInput(false)
      onClose()
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-[#111111] border border-gray-800 rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden shadow-2xl">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-orange-400 via-pink-500 to-purple-600 flex items-center justify-center">
              <BookOpen className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Add Sources</h2>
              <p className="text-sm text-gray-500">Upload documents or add links</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal Content */}
        <div className="p-6 overflow-y-auto max-h-[calc(85vh-140px)]">
          <p className="text-gray-300 mb-1">
            Sources let the AI base its responses on the information that matters most to you.
          </p>
          <p className="text-sm text-gray-500 mb-6">
            Examples: research papers, meeting notes, course readings, documentation, articles, etc.
          </p>

          {/* Upload Area */}
          <div
            className={`border-2 border-dashed rounded-xl p-10 mb-6 text-center transition-all cursor-pointer ${
              isDragging
                ? 'border-blue-500 bg-blue-500/10'
                : 'border-gray-700 hover:border-gray-600 hover:bg-gray-800/30'
            }`}
            onClick={() => !isUploading && fileInputRef.current?.click()}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              accept=".pdf,.txt,.md,.doc,.docx,.mp3,.wav,.png,.jpg,.jpeg,.gif,.webp"
              multiple
              className="hidden"
            />
            <div className="w-14 h-14 mx-auto mb-4 rounded-full bg-gray-800 flex items-center justify-center">
              {isUploading ? (
                <Loader2 className="w-7 h-7 text-blue-400 animate-spin" />
              ) : (
                <Upload className="w-7 h-7 text-blue-400" />
              )}
            </div>
            <p className="text-white font-medium mb-2">
              {isUploading ? 'Uploading...' : 'Upload sources'}
            </p>
            <p className="text-gray-400 text-sm">
              Drag & drop or{' '}
              <span className="text-blue-400 hover:underline cursor-pointer">choose files</span> to upload
            </p>
            <p className="text-gray-500 text-xs mt-4 max-w-lg mx-auto">
              Supported: PDF, TXT, Markdown, Audio (mp3, wav), Images (png, jpg, gif, webp), Word documents
            </p>
          </div>

          {/* Source Type Options */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            {/* Website Link */}
            <div className="p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center gap-2 mb-3">
                <Globe className="w-5 h-5 text-green-400" />
                <span className="text-sm text-white font-medium">Website</span>
              </div>
              <button
                onClick={() => {
                  setShowUrlInput(true)
                  setShowTextInput(false)
                  setShowYouTubeInput(false)
                }}
                className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
              >
                <Link className="w-3 h-3" />
                Add URL
              </button>
            </div>

            {/* YouTube */}
            <div className="p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center gap-2 mb-3">
                <Youtube className="w-5 h-5 text-red-500" />
                <span className="text-sm text-white font-medium">YouTube</span>
              </div>
              <button
                onClick={() => {
                  setShowYouTubeInput(true)
                  setShowUrlInput(false)
                  setShowTextInput(false)
                }}
                className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
              >
                <Youtube className="w-3 h-3" />
                Add Video
              </button>
            </div>

            {/* Paste Text */}
            <div className="p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center gap-2 mb-3">
                <Clipboard className="w-5 h-5 text-purple-400" />
                <span className="text-sm text-white font-medium">Paste Text</span>
              </div>
              <button
                onClick={() => {
                  setShowTextInput(true)
                  setShowUrlInput(false)
                  setShowYouTubeInput(false)
                }}
                className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
              >
                <Copy className="w-3 h-3" />
                Add Text
              </button>
            </div>
          </div>

          {/* URL Input Section */}
          {showUrlInput && (
            <div className="mb-6 p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-white font-medium">Add website URL</span>
                <button
                  onClick={() => {
                    setShowUrlInput(false)
                    setUrlValue('')
                  }}
                  className="p-1 text-gray-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex gap-2">
                <input
                  type="url"
                  value={urlValue}
                  onChange={(e) => setUrlValue(e.target.value)}
                  placeholder="https://example.com/article"
                  className="flex-1 px-4 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && handleUrlSubmit()}
                />
                <button
                  onClick={handleUrlSubmit}
                  disabled={!urlValue.trim()}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                >
                  Add
                </button>
              </div>
            </div>
          )}

          {/* YouTube Input Section */}
          {showYouTubeInput && (
            <div className="mb-6 p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-white font-medium flex items-center gap-2">
                  <Youtube className="w-4 h-4 text-red-500" />
                  Add YouTube video
                </span>
                <button
                  onClick={() => {
                    setShowYouTubeInput(false)
                    setYoutubeUrl('')
                  }}
                  className="p-1 text-gray-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <p className="text-xs text-gray-400 mb-3">
                Paste a YouTube URL and we&apos;ll extract the transcript automatically.
              </p>
              <div className="flex gap-2">
                <input
                  type="url"
                  value={youtubeUrl}
                  onChange={(e) => setYoutubeUrl(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=..."
                  className="flex-1 px-4 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-red-500 text-sm"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && handleYouTubeSubmit()}
                />
                <button
                  onClick={handleYouTubeSubmit}
                  disabled={!youtubeUrl.trim()}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                >
                  Add
                </button>
              </div>
            </div>
          )}

          {/* Text Input Section */}
          {showTextInput && (
            <div className="mb-6 p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-white font-medium">Paste text content</span>
                <button
                  onClick={() => {
                    setShowTextInput(false)
                    setTextTitle('')
                    setTextContent('')
                  }}
                  className="p-1 text-gray-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="space-y-3">
                <input
                  type="text"
                  value={textTitle}
                  onChange={(e) => setTextTitle(e.target.value)}
                  placeholder="Title for this source"
                  className="w-full px-4 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm"
                  autoFocus
                />
                <textarea
                  value={textContent}
                  onChange={(e) => setTextContent(e.target.value)}
                  placeholder="Paste your text content here..."
                  rows={6}
                  className="w-full px-4 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm resize-none"
                />
                <div className="flex justify-end">
                  <button
                    onClick={handleTextSubmit}
                    disabled={!textTitle.trim() || !textContent.trim()}
                    className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                  >
                    Add Source
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Source Limit Progress */}
          <div className="flex items-center gap-3">
            <FileText className="w-4 h-4 text-gray-500" />
            <span className="text-sm text-gray-400">Source limit</span>
            <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 transition-all"
                style={{ width: `${Math.min((sourcesCount / 50) * 100, 100)}%` }}
              />
            </div>
            <span className="text-sm text-gray-400">{sourcesCount} / 50</span>
          </div>
        </div>
      </div>
    </div>
  )
}
