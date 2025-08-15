"use client"

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { 
  Folder, 
  FolderOpen, 
  File,
  FileText,
  Code,
  Image,
  Music,
  Video,
  Plus,
  RefreshCw,
  Search,
  ChevronRight,
  ChevronDown,
  Loader2
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface FileTreeNode {
  name: string
  type: 'file' | 'directory'
  path: string
  size?: number
  children?: FileTreeNode[]
}

interface MonacoVibeFileTreeProps {
  sessionId: string
  onFileSelect: (filePath: string, content: string) => void
  onFileContentChange?: (filePath: string, content: string) => void
  className?: string
}

export default function MonacoVibeFileTree({ 
  sessionId, 
  onFileSelect, 
  onFileContentChange,
  className = "" 
}: MonacoVibeFileTreeProps) {
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([])
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set(['/workspace']))
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [fileCache, setFileCache] = useState<Map<string, string>>(new Map())
  const [isLoading, setIsLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [filteredTree, setFilteredTree] = useState<FileTreeNode[]>([])
  
  const wsRef = useRef<WebSocket | null>(null)

  // Get appropriate icon for file type
  const getFileIcon = useCallback((node: FileTreeNode, isExpanded = false) => {
    if (node.type === 'directory') {
      return isExpanded ? FolderOpen : Folder
    }
    
    const extension = node.name.split('.').pop()?.toLowerCase()
    
    switch (extension) {
      case 'js':
      case 'ts':
      case 'jsx':
      case 'tsx':
      case 'py':
      case 'java':
      case 'cpp':
      case 'c':
      case 'go':
      case 'rs':
      case 'php':
      case 'rb':
        return Code
      case 'txt':
      case 'md':
      case 'json':
      case 'yaml':
      case 'yml':
      case 'xml':
        return FileText
      case 'png':
      case 'jpg':
      case 'jpeg':
      case 'gif':
      case 'svg':
        return Image
      case 'mp3':
      case 'wav':
      case 'flac':
        return Music
      case 'mp4':
      case 'avi':
      case 'mov':
        return Video
      default:
        return File
    }
  }, [])

  // WebSocket setup for real-time file system events
  const setupFileWatcher = useCallback(() => {
    if (!sessionId) return

    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${wsProtocol}//${window.location.host}/api/vibecoding/container/${sessionId}/fs-events`
      
      const ws = new WebSocket(wsUrl)
      
      ws.onopen = () => {
        console.log('📁 File system watcher connected')
      }
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'file-changed' || data.type === 'file-created' || data.type === 'file-deleted') {
            console.log('📄 File system change detected:', data)
            loadFileTree() // Refresh tree on changes
            
            // Update cache if file changed
            if (data.type === 'file-changed' && data.filePath && data.content) {
              setFileCache(prev => new Map(prev.set(data.filePath, data.content)))
              onFileContentChange?.(data.filePath, data.content)
            }
          }
        } catch (error) {
          console.error('Error parsing file system event:', error)
        }
      }
      
      ws.onerror = (error) => {
        console.error('File system watcher error:', error)
      }
      
      ws.onclose = () => {
        console.log('📁 File system watcher disconnected')
      }
      
      wsRef.current = ws
      
      return () => {
        ws.close()
        wsRef.current = null
      }
    } catch (error) {
      console.warn('Could not establish file system watcher:', error)
    }
  }, [sessionId, onFileContentChange])

  // Load file tree with improved error handling
  const loadFileTree = useCallback(async () => {
    if (!sessionId) return

    try {
      setIsLoading(true)
      const token = localStorage.getItem('token')
      
      const response = await fetch('/api/vibecoding/files', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token && { 'Authorization': `Bearer ${token}` })
        },
        body: JSON.stringify({
          action: 'list',
          session_id: sessionId,
          path: '/workspace'
        })
      })

      if (response.ok) {
        const data = await response.json()
        
        // Convert flat file list to tree structure
        const buildTree = (files: any[]): FileTreeNode[] => {
          const tree: FileTreeNode[] = []
          const pathMap = new Map<string, FileTreeNode>()
          
          // Sort files: directories first, then by name
          const sortedFiles = files.sort((a, b) => {
            if (a.type !== b.type) {
              return a.type === 'directory' ? -1 : 1
            }
            return a.name.localeCompare(b.name)
          })
          
          sortedFiles.forEach(file => {
            const node: FileTreeNode = {
              name: file.name,
              type: file.type,
              path: file.path,
              size: file.size,
              children: file.type === 'directory' ? [] : undefined
            }
            
            pathMap.set(file.path, node)
            
            // For now, add all files to root level
            // TODO: Build proper hierarchy based on path
            tree.push(node)
          })
          
          return tree
        }
        
        const tree = buildTree(data.files || [])
        setFileTree(tree)
        console.log('📁 Loaded file tree:', tree.length, 'items')
      } else {
        console.error('Failed to load file tree:', response.status)
      }
    } catch (error) {
      console.error('Error loading file tree:', error)
    } finally {
      setIsLoading(false)
    }
  }, [sessionId])

  // Load file content with caching
  const loadFileContent = useCallback(async (filePath: string): Promise<string> => {
    // Check cache first
    if (fileCache.has(filePath)) {
      return fileCache.get(filePath)!
    }

    try {
      const token = localStorage.getItem('token')
      const response = await fetch('/api/vibecoding/files', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token && { 'Authorization': `Bearer ${token}` })
        },
        body: JSON.stringify({
          action: 'read',
          session_id: sessionId,
          file_path: filePath
        })
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        
        // Cache the content
        setFileCache(prev => new Map(prev.set(filePath, content)))
        return content
      } else {
        console.error('Failed to load file content:', response.status)
        return ''
      }
    } catch (error) {
      console.error('Error loading file content:', error)
      return ''
    }
  }, [sessionId, fileCache])

  // Save file content
  const saveFileContent = useCallback(async (filePath: string, content: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        console.error('No authentication token found')
        return false
      }

      const response = await fetch('/api/vibecoding/files', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          action: 'write',
          session_id: sessionId,
          file_path: filePath,
          content: content
        })
      })

      if (response.ok) {
        // Update cache
        setFileCache(prev => new Map(prev.set(filePath, content)))
        console.log('💾 File saved:', filePath)
        return true
      } else {
        console.error('Failed to save file:', response.status)
        return false
      }
    } catch (error) {
      console.error('Error saving file:', error)
      return false
    }
  }, [sessionId])

  // Handle file click
  const handleFileClick = useCallback(async (node: FileTreeNode) => {
    if (node.type === 'file') {
      setSelectedFile(node.path)
      const content = await loadFileContent(node.path)
      onFileSelect(node.path, content)
    } else {
      // Toggle directory expansion
      setExpandedNodes(prev => {
        const newSet = new Set(prev)
        if (newSet.has(node.path)) {
          newSet.delete(node.path)
        } else {
          newSet.add(node.path)
        }
        return newSet
      })
    }
  }, [loadFileContent, onFileSelect])

  // Filter files based on search term
  const filterTree = useCallback((nodes: FileTreeNode[], term: string): FileTreeNode[] => {
    if (!term.trim()) return nodes
    
    return nodes.filter(node => {
      const matchesName = node.name.toLowerCase().includes(term.toLowerCase())
      const matchesChildren = node.children ? filterTree(node.children, term).length > 0 : false
      return matchesName || matchesChildren
    }).map(node => ({
      ...node,
      children: node.children ? filterTree(node.children, term) : undefined
    }))
  }, [])

  // Update filtered tree when search term changes
  useEffect(() => {
    setFilteredTree(filterTree(fileTree, searchTerm))
  }, [fileTree, searchTerm, filterTree])

  // Render file tree node
  const renderFileNode = useCallback((node: FileTreeNode, depth = 0) => {
    const isExpanded = expandedNodes.has(node.path)
    const isSelected = selectedFile === node.path
    const Icon = getFileIcon(node, isExpanded)
    
    return (
      <div key={node.path}>
        <div 
          className={`flex items-center py-1 px-2 hover:bg-gray-700 cursor-pointer rounded ${
            isSelected ? 'bg-gray-600' : ''
          }`}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
          onClick={() => handleFileClick(node)}
        >
          {node.type === 'directory' && (
            <span className="mr-1 text-gray-400">
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </span>
          )}
          <Icon size={16} className={`mr-2 ${
            node.type === 'directory' ? 'text-blue-400' : 'text-gray-300'
          }`} />
          <span className="text-sm text-gray-200 truncate">{node.name}</span>
          {node.size !== undefined && (
            <span className="ml-auto text-xs text-gray-500">
              {node.size < 1024 ? `${node.size}B` : `${(node.size / 1024).toFixed(1)}KB`}
            </span>
          )}
        </div>
        
        {node.type === 'directory' && isExpanded && node.children && (
          <div>
            {node.children.map((child) => renderFileNode(child, depth + 1))}
          </div>
        )}
      </div>
    )
  }, [expandedNodes, selectedFile, getFileIcon, handleFileClick])

  // Initialize component
  useEffect(() => {
    if (sessionId) {
      loadFileTree()
      const cleanup = setupFileWatcher()
      return cleanup
    }
  }, [sessionId, loadFileTree, setupFileWatcher])

  return (
    <div className={`bg-gray-800 border-r border-gray-700 flex flex-col h-full ${className}`}>
      {/* Header */}
      <div className="p-3 border-b border-gray-700">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-gray-300">EXPLORER</h3>
          <div className="flex space-x-1">
            <Button 
              onClick={loadFileTree}
              size="sm"
              variant="ghost"
              className="p-1 h-auto hover:bg-gray-700"
              disabled={isLoading}
            >
              {isLoading ? (
                <Loader2 size={14} className="animate-spin text-gray-400" />
              ) : (
                <RefreshCw size={14} className="text-gray-400" />
              )}
            </Button>
            <Button 
              size="sm"
              variant="ghost"
              className="p-1 h-auto hover:bg-gray-700"
            >
              <Plus size={14} className="text-gray-400" />
            </Button>
          </div>
        </div>
        
        {/* Search */}
        <div className="relative">
          <Search size={14} className="absolute left-2 top-1/2 transform -translate-y-1/2 text-gray-500" />
          <Input 
            type="text" 
            placeholder="Search files..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-8 text-xs bg-gray-700 border-gray-600 text-gray-300 h-7"
          />
        </div>
      </div>
      
      {/* File Tree */}
      <div className="flex-1 overflow-y-auto">
        {isLoading && fileTree.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-gray-500">
            <Loader2 size={20} className="animate-spin mr-2" />
            Loading files...
          </div>
        ) : (
          <div className="p-2">
            {(searchTerm ? filteredTree : fileTree).map(node => renderFileNode(node))}
            {fileTree.length === 0 && !isLoading && (
              <div className="text-gray-500 text-sm text-center py-8">
                No files found
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}