'use client'

import { useState, useRef } from 'react'
import {
  X, Upload, Link, Globe, Youtube, Clipboard,
  FileText, Copy, BookOpen, Loader2
} from 'lucide-react'

interface AddSourceModalProps {
  isOpen: boolean
  onClose: () => void
  sourcesCount: number
  onFileUpload: (files: FileList) => Promise<void>
  onAddUrl: (url: string) => Promise<void>
  onAddText: (title: string, content: string) => Promise<void>
  onAddYouTube?: (url: string) => Promise<void>
  compact?: boolean
}

export default function AddSourceModal({
  isOpen, onClose, sourcesCount,
  onFileUpload, onAddUrl, onAddText, onAddYouTube,
  compact = false,
}: AddSourceModalProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [activeInput, setActiveInput] = useState<'url' | 'youtube' | 'text' | null>(null)
  const [urlValue, setUrlValue] = useState('')
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [textTitle, setTextTitle] = useState('')
  const [textContent, setTextContent] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)

  if (!isOpen) return null

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true) }
  const handleDragLeave = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(false) }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer.files.length > 0) {
      setIsUploading(true)
      await onFileUpload(e.dataTransfer.files)
      setIsUploading(false)
    }
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setIsUploading(true)
      await onFileUpload(e.target.files)
      setIsUploading(false)
    }
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleUrlSubmit = async () => {
    if (!urlValue.trim()) return
    await onAddUrl(urlValue.trim())
    setUrlValue('')
  }

  const handleYouTubeSubmit = async () => {
    if (!youtubeUrl.trim() || !onAddYouTube) return
    await onAddYouTube(youtubeUrl.trim())
    setYoutubeUrl('')
  }

  const handleTextSubmit = async () => {
    if (!textTitle.trim() || !textContent.trim()) return
    await onAddText(textTitle.trim(), textContent.trim())
    setTextTitle(''); setTextContent('')
  }

  const switchInput = (type: 'url' | 'youtube' | 'text') => {
    setActiveInput(activeInput === type ? null : type)
  }

  if (compact) {
    return (
      <div className="border-b border-border p-2 space-y-2">
        {/* Drag & Drop Zone */}
        <div
          className={`border border-dashed rounded-lg p-3 text-center cursor-pointer transition-colors ${
            isDragging ? 'border-primary bg-primary/10' : 'border-border hover:border-muted-foreground'
          }`}
          onClick={() => !isUploading && fileInputRef.current?.click()}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <input ref={fileInputRef} type="file" onChange={handleFileSelect}
            accept=".pdf,.txt,.md,.doc,.docx,.mp3,.wav,.png,.jpg,.jpeg,.gif,.webp" multiple className="hidden" />
          {isUploading
            ? <Loader2 className="w-4 h-4 mx-auto animate-spin text-primary" />
            : <Upload className="w-4 h-4 mx-auto text-muted-foreground" />
          }
          <p className="text-[10px] text-muted-foreground mt-1">
            {isUploading ? 'Uploading...' : 'Drop files or click'}
          </p>
        </div>

        {/* Quick Actions */}
        <div className="flex gap-1">
          <button onClick={() => switchInput('url')}
            className={`flex-1 flex items-center justify-center gap-1 py-1 text-[10px] rounded ${activeInput === 'url' ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground hover:text-foreground'}`}>
            <Globe className="w-3 h-3" /> URL
          </button>
          <button onClick={() => switchInput('youtube')}
            className={`flex-1 flex items-center justify-center gap-1 py-1 text-[10px] rounded ${activeInput === 'youtube' ? 'bg-red-600 text-white' : 'bg-secondary text-muted-foreground hover:text-foreground'}`}>
            <Youtube className="w-3 h-3" /> YouTube
          </button>
          <button onClick={() => switchInput('text')}
            className={`flex-1 flex items-center justify-center gap-1 py-1 text-[10px] rounded ${activeInput === 'text' ? 'bg-purple-600 text-white' : 'bg-secondary text-muted-foreground hover:text-foreground'}`}>
            <Clipboard className="w-3 h-3" /> Text
          </button>
        </div>

        {/* Input Forms */}
        {activeInput === 'url' && (
          <div className="space-y-1">
            <input type="url" value={urlValue} onChange={e => setUrlValue(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleUrlSubmit()}
              placeholder="https://..." className="w-full px-2 py-1 text-xs bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary" autoFocus />
            <div className="flex gap-1">
              <button onClick={handleUrlSubmit} disabled={!urlValue.trim()}
                className="flex-1 py-1 text-[10px] bg-primary text-primary-foreground rounded disabled:opacity-50">Add</button>
              <button onClick={() => setActiveInput(null)} className="px-2 py-1 text-[10px] text-muted-foreground">Cancel</button>
            </div>
          </div>
        )}

        {activeInput === 'youtube' && (
          <div className="space-y-1">
            <input type="url" value={youtubeUrl} onChange={e => setYoutubeUrl(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleYouTubeSubmit()}
              placeholder="https://youtube.com/watch?v=..." className="w-full px-2 py-1 text-xs bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-red-500" autoFocus />
            <p className="text-[9px] text-muted-foreground">Transcript will be extracted automatically</p>
            <div className="flex gap-1">
              <button onClick={handleYouTubeSubmit} disabled={!youtubeUrl.trim() || !onAddYouTube}
                className="flex-1 py-1 text-[10px] bg-red-600 text-white rounded disabled:opacity-50">Add</button>
              <button onClick={() => setActiveInput(null)} className="px-2 py-1 text-[10px] text-muted-foreground">Cancel</button>
            </div>
          </div>
        )}

        {activeInput === 'text' && (
          <div className="space-y-1">
            <input type="text" value={textTitle} onChange={e => setTextTitle(e.target.value)}
              placeholder="Title..." className="w-full px-2 py-1 text-xs bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-purple-500" autoFocus />
            <textarea value={textContent} onChange={e => setTextContent(e.target.value)}
              placeholder="Content..." rows={3} className="w-full px-2 py-1 text-xs bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-purple-500 resize-none" />
            <div className="flex gap-1">
              <button onClick={handleTextSubmit} disabled={!textTitle.trim() || !textContent.trim()}
                className="flex-1 py-1 text-[10px] bg-purple-600 text-white rounded disabled:opacity-50">Add</button>
              <button onClick={() => setActiveInput(null)} className="px-2 py-1 text-[10px] text-muted-foreground">Cancel</button>
            </div>
          </div>
        )}

        {/* Source count */}
        <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
          <div className="flex-1 h-1 bg-secondary rounded-full overflow-hidden">
            <div className="h-full bg-primary transition-all" style={{ width: `${Math.min((sourcesCount / 50) * 100, 100)}%` }} />
          </div>
          <span>{sourcesCount}/50</span>
        </div>

        <button onClick={onClose} className="w-full py-1 text-[10px] text-muted-foreground hover:text-foreground">Done</button>
      </div>
    )
  }

  // Full-screen modal
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-card border border-border rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 via-blue-600 to-cyan-500 flex items-center justify-center">
              <BookOpen className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">Add Sources</h2>
              <p className="text-sm text-muted-foreground">Upload documents or add links</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 text-muted-foreground hover:text-foreground hover:bg-secondary rounded-lg transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 overflow-y-auto max-h-[calc(85vh-140px)]">
          <p className="text-muted-foreground mb-1">
            Sources let the AI base its responses on the information that matters most to you.
          </p>
          <p className="text-sm text-muted-foreground/70 mb-6">
            Examples: research papers, meeting notes, course readings, documentation, articles, etc.
          </p>

          {/* Upload Area */}
          <div
            className={`border-2 border-dashed rounded-xl p-10 mb-6 text-center transition-all cursor-pointer ${
              isDragging ? 'border-primary bg-primary/10' : 'border-border hover:border-muted-foreground hover:bg-secondary/30'
            }`}
            onClick={() => !isUploading && fileInputRef.current?.click()}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input ref={fileInputRef} type="file" onChange={handleFileSelect}
              accept=".pdf,.txt,.md,.doc,.docx,.mp3,.wav,.png,.jpg,.jpeg,.gif,.webp" multiple className="hidden" />
            <div className="w-14 h-14 mx-auto mb-4 rounded-full bg-secondary flex items-center justify-center">
              {isUploading ? <Loader2 className="w-7 h-7 text-primary animate-spin" /> : <Upload className="w-7 h-7 text-primary" />}
            </div>
            <p className="text-foreground font-medium mb-2">{isUploading ? 'Uploading...' : 'Upload sources'}</p>
            <p className="text-muted-foreground text-sm">
              Drag & drop or <span className="text-primary hover:underline cursor-pointer">choose files</span>
            </p>
            <p className="text-muted-foreground/60 text-xs mt-4 max-w-lg mx-auto">
              Supported: PDF, TXT, Markdown, Audio (mp3, wav), Images (png, jpg, gif, webp), Word documents
            </p>
          </div>

          {/* Source Type Options */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="p-4 bg-secondary/50 rounded-xl border border-border/50">
              <div className="flex items-center gap-2 mb-3">
                <Globe className="w-5 h-5 text-green-400" />
                <span className="text-sm text-foreground font-medium">Website</span>
              </div>
              <button onClick={() => switchInput('url')}
                className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground bg-secondary hover:bg-secondary/80 rounded-lg transition-colors">
                <Link className="w-3 h-3" /> Add URL
              </button>
            </div>

            <div className="p-4 bg-secondary/50 rounded-xl border border-border/50">
              <div className="flex items-center gap-2 mb-3">
                <Youtube className="w-5 h-5 text-red-500" />
                <span className="text-sm text-foreground font-medium">YouTube</span>
              </div>
              <button onClick={() => switchInput('youtube')}
                className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground bg-secondary hover:bg-secondary/80 rounded-lg transition-colors">
                <Youtube className="w-3 h-3" /> Add Video
              </button>
            </div>

            <div className="p-4 bg-secondary/50 rounded-xl border border-border/50">
              <div className="flex items-center gap-2 mb-3">
                <Clipboard className="w-5 h-5 text-purple-400" />
                <span className="text-sm text-foreground font-medium">Paste Text</span>
              </div>
              <button onClick={() => switchInput('text')}
                className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground bg-secondary hover:bg-secondary/80 rounded-lg transition-colors">
                <Copy className="w-3 h-3" /> Add Text
              </button>
            </div>
          </div>

          {/* URL Input */}
          {activeInput === 'url' && (
            <div className="mb-6 p-4 bg-secondary/50 rounded-xl border border-border/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-foreground font-medium">Add website URL</span>
                <button onClick={() => { setActiveInput(null); setUrlValue('') }} className="p-1 text-muted-foreground hover:text-foreground">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex gap-2">
                <input type="url" value={urlValue} onChange={e => setUrlValue(e.target.value)}
                  placeholder="https://example.com/article"
                  className="flex-1 px-4 py-2 bg-background border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary text-sm"
                  autoFocus onKeyDown={e => e.key === 'Enter' && handleUrlSubmit()} />
                <button onClick={handleUrlSubmit} disabled={!urlValue.trim()}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 text-sm font-medium">
                  Add
                </button>
              </div>
            </div>
          )}

          {/* YouTube Input */}
          {activeInput === 'youtube' && (
            <div className="mb-6 p-4 bg-secondary/50 rounded-xl border border-border/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-foreground font-medium flex items-center gap-2">
                  <Youtube className="w-4 h-4 text-red-500" /> Add YouTube video
                </span>
                <button onClick={() => { setActiveInput(null); setYoutubeUrl('') }} className="p-1 text-muted-foreground hover:text-foreground">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <p className="text-xs text-muted-foreground mb-3">Paste a YouTube URL and we&apos;ll extract the transcript automatically.</p>
              <div className="flex gap-2">
                <input type="url" value={youtubeUrl} onChange={e => setYoutubeUrl(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=..."
                  className="flex-1 px-4 py-2 bg-background border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-red-500 text-sm"
                  autoFocus onKeyDown={e => e.key === 'Enter' && handleYouTubeSubmit()} />
                <button onClick={handleYouTubeSubmit} disabled={!youtubeUrl.trim() || !onAddYouTube}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 text-sm font-medium">
                  Add
                </button>
              </div>
            </div>
          )}

          {/* Text Input */}
          {activeInput === 'text' && (
            <div className="mb-6 p-4 bg-secondary/50 rounded-xl border border-border/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-foreground font-medium">Paste text content</span>
                <button onClick={() => { setActiveInput(null); setTextTitle(''); setTextContent('') }} className="p-1 text-muted-foreground hover:text-foreground">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="space-y-3">
                <input type="text" value={textTitle} onChange={e => setTextTitle(e.target.value)}
                  placeholder="Title for this source"
                  className="w-full px-4 py-2 bg-background border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm" autoFocus />
                <textarea value={textContent} onChange={e => setTextContent(e.target.value)}
                  placeholder="Paste your text content here..." rows={6}
                  className="w-full px-4 py-2 bg-background border border-border rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm resize-none" />
                <div className="flex justify-end">
                  <button onClick={handleTextSubmit} disabled={!textTitle.trim() || !textContent.trim()}
                    className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 text-sm font-medium">
                    Add Source
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Source Limit */}
          <div className="flex items-center gap-3">
            <FileText className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">Source limit</span>
            <div className="flex-1 h-2 bg-secondary rounded-full overflow-hidden">
              <div className="h-full bg-primary transition-all" style={{ width: `${Math.min((sourcesCount / 50) * 100, 100)}%` }} />
            </div>
            <span className="text-sm text-muted-foreground">{sourcesCount} / 50</span>
          </div>
        </div>
      </div>
    </div>
  )
}
