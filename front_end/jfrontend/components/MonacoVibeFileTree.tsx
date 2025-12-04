"use client"

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { safeTrim, toStr, toWorkspaceRelativePath } from '@/lib/strings'
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
  Loader2,
  FilePlus,
  FolderPlus,
  Edit2,
  Trash2,
  X,
  Check
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { FileIcon, FolderIcon } from '@/lib/file-icons'
import { ImportRepoButton } from '@/components/ImportRepoButton'

interface FileTreeNode {
  name: string
  type: 'file' | 'directory'
  path: string
  size?: number
  children?: FileTreeNode[]
}

interface MonacoVibeFileTreeProps {
  sessionId: string
  isContainerRunning?: boolean
  onFileSelect: (filePath: string, content: string) => void
  onFileContentChange?: (filePath: string, content: string) => void
  currentDir?: string
  newFileButton?: React.ReactNode
  className?: string
}

interface ContextMenu {
  x: number
  y: number
  node: FileTreeNode
}

export default function MonacoVibeFileTree({
  sessionId,
  isContainerRunning = false,
  onFileSelect,
  onFileContentChange,
  currentDir = '/workspace',
  newFileButton,
  className = ""
}: MonacoVibeFileTreeProps) {
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([])
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set(['/workspace']))
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [fileCache, setFileCache] = useState<Map<string, string>>(new Map())
  const [isLoading, setIsLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [filteredTree, setFilteredTree] = useState<FileTreeNode[]>([])
  const [contextMenu, setContextMenu] = useState<ContextMenu | null>(null)
  const [renamingNode, setRenamingNode] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)

  // New file dialog state
  const [showNewFileDialog, setShowNewFileDialog] = useState(false)
  const [newFileName, setNewFileName] = useState('')
  const [draggedNode, setDraggedNode] = useState<FileTreeNode | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const contextMenuRef = useRef<HTMLDivElement>(null)
  const lastCallRef = useRef<number>(0)

  // FileIcon component from react-file-icon is used for all file types
  // It automatically provides appropriate icons for JS, Python, C++, etc.

  // WebSocket setup for real-time file system events
  const setupFileWatcher = useCallback(() => {
    if (!sessionId) return

    // Temporarily disable file system watcher until backend endpoint is implemented
    console.log('📁 File system watcher disabled (fs-events endpoint not implemented)')
    return () => { } // Return empty cleanup function

    /* TODO: Re-enable when backend implements fs-events WebSocket endpoint
    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${wsProtocol}//${window.location.host}/api/vibecode/container/${sessionId}/fs-events`

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
        console.warn('File system watcher connection failed (endpoint may not exist):', error)
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
    */
  }, [sessionId, onFileContentChange])

  // Load file tree with improved error handling and throttling
  const loadFileTree = useCallback(async () => {
    if (!sessionId) return

    // Throttle API calls to prevent spam
    const now = Date.now()
    if (lastCallRef.current && now - lastCallRef.current < 2000) {
      console.log('⏳ Throttling file tree load (too frequent)')
      return
    }
    lastCallRef.current = now

    // Don't load if already loading
    if (isLoading) {
      console.log('⏳ File tree already loading, skipping...')
      return
    }

    try {
      setIsLoading(true)
      const token = localStorage.getItem('token')

      // Check if user is authenticated
      if (!token) {
        console.warn('⚠️ No auth token - user needs to log in')
        setFileTree([])
        setIsLoading(false)
        return
      }

      const response = await fetch('/api/vibecode/files/tree', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`  // Always include auth header
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: '/workspace'
        })
      })

      if (response.ok) {
        const data = await response.json()
        // Backend returns a hierarchical tree with a root (path=/workspace)
        const toNode = (n: any): FileTreeNode => ({
          name: n.name,
          type: n.type,
          path: n.path,
          size: n.size,
          children: Array.isArray(n.children) ? n.children.map(toNode) : undefined
        })
        const root = toNode(data)
        const children = root.children || []
        setFileTree(children)
        console.log('📁 Loaded file tree:', children.length, 'items')
        if (children.length > 0) {
          console.log('📁 Files:', children.map(f => `${f.name} (${f.type})`).join(', '))
        }
      } else {
        // Better error handling
        if (response.status === 401) {
          console.error('❌ Auth failed - token expired, please re-login')
          setFileTree([])
          // Optionally redirect to login or show auth error
        } else if (response.status === 404) {
          console.error('❌ Container not found - start container first')
          setFileTree([])
        } else {
          const errorText = await response.text()
          console.error(`❌ File tree load failed (${response.status}):`, errorText)
          setFileTree([])
        }
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
      const response = await fetch('/api/vibecode/files/read', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token && { 'Authorization': `Bearer ${token}` })
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: toWorkspaceRelativePath(filePath)
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

      const response = await fetch('/api/vibecode/files/save', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: toWorkspaceRelativePath(filePath),
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

  // Create new file
  const createFile = useCallback(async (parentPath: string, fileName: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        console.error('No authentication token found')
        return false
      }

      // Convert absolute path to relative path for the API
      const filePath = toWorkspaceRelativePath(`${parentPath}/${fileName}`.replace('//', '/'))

      const response = await fetch('/api/vibecode/files/create', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: filePath,
          type: 'file'
        })
      })

      if (response.ok) {
        console.log('📄 File created:', filePath)
        // Optimistic update
        await loadFileTree()
        return true
      } else {
        console.error('Failed to create file:', response.status)
        return false
      }
    } catch (error) {
      console.error('Error creating file:', error)
      return false
    }
  }, [sessionId, loadFileTree])

  // Create new folder
  const createFolder = useCallback(async (parentPath: string, folderName: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        console.error('No authentication token found')
        return false
      }

      // Convert absolute path to relative path for the API
      const folderPath = toWorkspaceRelativePath(`${parentPath}/${folderName}`.replace('//', '/'))

      const response = await fetch('/api/vibecode/files/create', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: folderPath,
          type: 'folder'
        })
      })

      if (response.ok) {
        console.log('📁 Folder created:', folderPath)
        // Optimistic update
        await loadFileTree()
        // Expand parent folder
        setExpandedNodes(prev => new Set(prev.add(parentPath)))
        return true
      } else {
        console.error('Failed to create folder:', response.status)
        return false
      }
    } catch (error) {
      console.error('Error creating folder:', error)
      return false
    }
  }, [sessionId, loadFileTree])

  // Rename file or folder
  const renameItem = useCallback(async (oldPath: string, newName: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        console.error('No authentication token found')
        return false
      }

      const pathParts = toWorkspaceRelativePath(oldPath).split('/')
      pathParts[pathParts.length - 1] = newName
      const newPath = pathParts.join('/')

      const response = await fetch('/api/vibecode/files/rename', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          old_path: toWorkspaceRelativePath(oldPath),
          new_name: newName
        })
      })

      if (response.ok) {
        console.log('✏️ Renamed:', oldPath, '->', newPath)
        // Optimistic update
        await loadFileTree()
        // Update selected file if it was renamed
        if (selectedFile === oldPath) {
          setSelectedFile(newPath)
        }
        return true
      } else {
        console.error('Failed to rename:', response.status)
        return false
      }
    } catch (error) {
      console.error('Error renaming:', error)
      return false
    }
  }, [sessionId, loadFileTree, selectedFile])

  // Delete file or folder
  const deleteItem = useCallback(async (path: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        console.error('No authentication token found')
        return false
      }

      const response = await fetch('/api/vibecode/files/delete', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: path
        })
      })

      if (response.ok) {
        console.log('🗑️ Deleted:', path)
        // Optimistic update
        await loadFileTree()
        // Clear selection if deleted file was selected
        if (selectedFile === path) {
          setSelectedFile(null)
        }
        return true
      } else {
        console.error('Failed to delete:', response.status)
        return false
      }
    } catch (error) {
      console.error('Error deleting:', error)
      return false
    }
  }, [sessionId, loadFileTree, selectedFile])

  // Move file or folder
  const moveItem = useCallback(async (sourcePath: string, targetDir: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        console.error('No authentication token found')
        return false
      }

      // Validate destination is within /workspace
      if (!targetDir.startsWith('/workspace')) {
        console.error('Invalid destination: must be within /workspace')
        return false
      }

      // Prevent moving into itself or its children
      if (targetDir.startsWith(sourcePath + '/') || targetDir === sourcePath) {
        console.error('Cannot move item into itself')
        return false
      }

      const fileName = sourcePath.split('/').pop()
      const newPath = `${targetDir}/${fileName}`.replace('//', '/')

      const response = await fetch('/api/vibecode/files/move', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          source_path: sourcePath,
          target_dir: targetDir
        })
      })

      if (response.ok) {
        const result = await response.json().catch(() => ({}))
        console.log('✅ Moved:', sourcePath, '->', targetDir, result)
        // Reload file tree to reflect changes
        await loadFileTree()
        // Update selected file if it was moved
        if (selectedFile === sourcePath) {
          const fileName = sourcePath.split('/').pop()
          const newPath = `${targetDir}/${fileName}`.replace('//', '/')
          setSelectedFile(newPath)
        }
        // Expand target directory to show the moved item
        setExpandedNodes(prev => new Set(prev.add(targetDir)))
        return true
      } else {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }))
        console.error('❌ Move failed:', response.status, errorData)
        const errorMsg = errorData.detail || errorData.message || 'Failed to move item'
        alert(`Error: ${errorMsg}`)
        return false
      }
    } catch (error) {
      console.error('❌ Error moving:', error)
      alert(`Error: ${error instanceof Error ? error.message : 'Failed to move item'}`)
      return false
    }
  }, [sessionId, loadFileTree, selectedFile])

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

  // Handle right-click context menu
  const handleContextMenu = useCallback((e: React.MouseEvent, node: FileTreeNode) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      node
    })
  }, [])

  // Close context menu
  const closeContextMenu = useCallback(() => {
    setContextMenu(null)
  }, [])

  // Handle context menu actions
  const handleNewFile = useCallback(async () => {
    const node = contextMenu?.node
    if (!node) return

    const parentPath = node.type === 'directory' ? node.path : node.path.split('/').slice(0, -1).join('/')
    const fileName = prompt('Enter file name:')

    if (fileName && safeTrim(fileName)) {
      await createFile(parentPath, safeTrim(fileName))
    }
    closeContextMenu()
  }, [contextMenu, createFile, closeContextMenu])

  // Handle + button file creation with dialog
  const handleCreateFile = useCallback(async () => {
    if (!newFileName.trim()) return

    try {
      await createFile('/workspace', safeTrim(newFileName))
      setNewFileName('')
      setShowNewFileDialog(false)
    } catch (error) {
      console.error('Failed to create file:', error)
    }
  }, [newFileName, createFile])

  const handleNewFolder = useCallback(async () => {
    const node = contextMenu?.node
    if (!node) return

    const parentPath = node.type === 'directory' ? node.path : node.path.split('/').slice(0, -1).join('/')
    const folderName = prompt('Enter folder name:')

    if (folderName && safeTrim(folderName)) {
      await createFolder(parentPath, safeTrim(folderName))
    }
    closeContextMenu()
  }, [contextMenu, createFolder, closeContextMenu])

  const handleRename = useCallback(() => {
    const node = contextMenu?.node
    if (!node) return

    setRenamingNode(node.path)
    setRenameValue(node.name)
    closeContextMenu()
  }, [contextMenu, closeContextMenu])

  const handleDelete = useCallback(() => {
    const node = contextMenu?.node
    if (!node) return

    setShowDeleteConfirm(node.path)
    closeContextMenu()
  }, [contextMenu, closeContextMenu])

  const confirmDelete = useCallback(async (path: string) => {
    await deleteItem(path)
    setShowDeleteConfirm(null)
  }, [deleteItem])

  const cancelDelete = useCallback(() => {
    setShowDeleteConfirm(null)
  }, [])

  const confirmRename = useCallback(async (oldPath: string) => {
    const trimmedValue = safeTrim(renameValue)
    if (trimmedValue && trimmedValue !== oldPath.split('/').pop()) {
      await renameItem(oldPath, trimmedValue)
    }
    setRenamingNode(null)
    setRenameValue('')
  }, [renameValue, renameItem])

  const cancelRename = useCallback(() => {
    setRenamingNode(null)
    setRenameValue('')
  }, [])

  // Drag and drop handlers
  const handleDragStart = useCallback((e: React.DragEvent, node: FileTreeNode) => {
    e.stopPropagation()
    setDraggedNode(node)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', node.path)

    // Add visual feedback
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.style.opacity = '0.5'
    }
  }, [])

  const handleDragEnd = useCallback((e: React.DragEvent) => {
    e.stopPropagation()
    setDraggedNode(null)
    setDropTarget(null)

    // Remove visual feedback
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.style.opacity = '1'
    }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent, node: FileTreeNode) => {
    e.preventDefault()
    e.stopPropagation()

    // Only allow dropping on directories
    if (node.type === 'directory' && draggedNode && node.path !== draggedNode.path) {
      e.dataTransfer.dropEffect = 'move'
      setDropTarget(node.path)
    } else {
      e.dataTransfer.dropEffect = 'none'
    }
  }, [draggedNode])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.stopPropagation()
    setDropTarget(null)
  }, [])

  const handleDrop = useCallback(async (e: React.DragEvent, targetNode: FileTreeNode) => {
    e.preventDefault()
    e.stopPropagation()

    setDropTarget(null)

    // Only allow dropping on directories
    if (targetNode.type !== 'directory' || !draggedNode) {
      console.warn('❌ Drop target is not a directory or no item is being dragged')
      setDraggedNode(null)
      return
    }

    // Don't drop on itself
    if (targetNode.path === draggedNode.path) {
      console.warn('❌ Cannot drop item on itself')
      setDraggedNode(null)
      return
    }

    // Prevent dropping into a child directory
    if (draggedNode.path.startsWith(targetNode.path + '/')) {
      console.warn('❌ Cannot drop item into its own child directory')
      setDraggedNode(null)
      return
    }

    console.log('📦 Moving:', draggedNode.path, '->', targetNode.path)

    // Perform the move
    const success = await moveItem(draggedNode.path, targetNode.path)
    if (!success) {
      console.error('❌ Failed to move item')
      alert(`Failed to move ${draggedNode.name} to ${targetNode.name}`)
    }
    setDraggedNode(null)
  }, [draggedNode, moveItem])

  // Filter files based on search term
  const filterTree = useCallback((nodes: FileTreeNode[], term: string): FileTreeNode[] => {
    if (!safeTrim(term)) return nodes

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

  // Render file tree node with tree lines
  const renderFileNode = useCallback((node: FileTreeNode, depth = 0, isLastArray: boolean[] = []) => {
    const isExpanded = expandedNodes.has(node.path)
    const isSelected = selectedFile === node.path
    const isRenaming = renamingNode === node.path
    const isDeleting = showDeleteConfirm === node.path
    const isDropTarget = dropTarget === node.path
    const isLast = isLastArray[isLastArray.length - 1]

    return (
      <div key={node.path} className="relative">
        {/* Tree branch lines */}
        {depth > 0 && (
          <div className="absolute left-0 top-0 bottom-0 pointer-events-none" style={{ width: `${depth * 16}px` }}>
            {/* Vertical lines for parent levels */}
            {Array.from({ length: depth }).map((_, i) => {
              // Don't show vertical line if that level's parent was the last item
              const showLine = i < isLastArray.length ? !isLastArray[i] : true
              return showLine ? (
                <div
                  key={i}
                  className="absolute top-0 bottom-0 w-px bg-gray-600"
                  style={{ left: `${i * 16 + 8}px` }}
                />
              ) : null
            })}
            {/* Horizontal connector line */}
            <div
              className="absolute w-3 h-px bg-gray-600"
              style={{
                left: `${(depth - 1) * 16 + 8}px`,
                top: '14px' // Centered vertically
              }}
            />
            {/* L-shaped corner for last item */}
            {isLast && (
              <div
                className="absolute w-px bg-gray-600"
                style={{
                  left: `${(depth - 1) * 16 + 8}px`,
                  top: 0,
                  height: '14px'
                }}
              />
            )}
          </div>
        )}

        <div
          className={`flex items-center py-1 px-2 hover:bg-gray-700 cursor-pointer rounded relative transition-colors z-10 ${isSelected ? 'bg-gray-600' : ''
            } ${isDropTarget ? 'bg-blue-600/30 border-2 border-blue-500' : ''
            }`}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
          onClick={() => !isRenaming && handleFileClick(node)}
          onContextMenu={(e) => handleContextMenu(e, node)}
          draggable={!isRenaming}
          onDragStart={(e) => handleDragStart(e, node)}
          onDragEnd={handleDragEnd}
          onDragOver={(e) => handleDragOver(e, node)}
          onDragLeave={handleDragLeave}
          onDrop={(e) => handleDrop(e, node)}
        >
          {node.type === 'directory' && (
            <span className="mr-1 text-gray-400 z-20">
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </span>
          )}
          {node.type === 'directory' ? (
            <FolderIcon size={16} className="mr-2" />
          ) : (
            <FileIcon fileName={node.name} size={16} className="mr-2" />
          )}
          {isRenaming ? (
            <div className="flex items-center flex-1 gap-1" onClick={(e) => e.stopPropagation()}>
              <Input
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    confirmRename(node.path)
                  } else if (e.key === 'Escape') {
                    cancelRename()
                  }
                }}
                className="h-6 text-xs bg-gray-700 border-gray-600 text-gray-200 px-2"
                autoFocus
              />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => confirmRename(node.path)}
                className="h-6 w-6 p-0"
              >
                <Check size={12} />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={cancelRename}
                className="h-6 w-6 p-0"
              >
                <X size={12} />
              </Button>
            </div>
          ) : (
            <>
              <span className="text-sm text-gray-200 truncate flex-1">{node.name}</span>
              {node.size !== undefined && (
                <span className="ml-auto text-xs text-gray-500">
                  {node.size < 1024 ? `${node.size}B` : `${(node.size / 1024).toFixed(1)}KB`}
                </span>
              )}
            </>
          )}
        </div>

        {isDeleting && (
          <div className="flex items-center gap-1 ml-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation()
                confirmDelete(node.path)
              }}
              className="h-6 px-2 bg-red-600 hover:bg-red-700 text-white text-xs"
            >
              Delete
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation()
                cancelDelete()
              }}
              className="h-6 px-2 text-xs"
            >
              Cancel
            </Button>
          </div>
        )}

        {/* Render children */}
        {node.type === 'directory' && isExpanded && node.children && node.children.length > 0 && (
          <div>
            {node.children.map((child, index) => {
              const isChildLast = index === node.children!.length - 1
              return renderFileNode(child, depth + 1, [...isLastArray, isChildLast])
            })}
          </div>
        )}
      </div>
    )
  }, [
    expandedNodes,
    selectedFile,
    renamingNode,
    showDeleteConfirm,
    dropTarget,
    renameValue,
    handleFileClick,
    handleContextMenu,
    confirmRename,
    cancelRename,
    confirmDelete,
    cancelDelete,
    handleDragStart,
    handleDragEnd,
    handleDragOver,
    handleDragLeave,
    handleDrop
  ])

  // Initialize component
  useEffect(() => {
    if (sessionId && isContainerRunning) {
      loadFileTree()
      const cleanup = setupFileWatcher()
      return cleanup
    }
  }, [sessionId, isContainerRunning, setupFileWatcher])

  // Auto-refresh file tree every 10 seconds (less frequent to reduce flickering)
  useEffect(() => {
    if (!sessionId || !isContainerRunning) return

    const interval = setInterval(() => {
      // Only refresh if not currently loading and no file is selected
      if (!isLoading && !selectedFile) {
        console.log('🔄 Auto-refreshing file tree...')
        loadFileTree()
      }
    }, 10000) // Refresh every 10 seconds

    return () => clearInterval(interval)
  }, [sessionId, isContainerRunning, loadFileTree, isLoading, selectedFile])

  // Close context menu on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target as Node)) {
        closeContextMenu()
      }
    }

    if (contextMenu) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [contextMenu, closeContextMenu])

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
            <ImportRepoButton 
              sessionId={sessionId} 
              onSuccess={loadFileTree}
            />
            {newFileButton || (
              <Button
                size="sm"
                variant="ghost"
                className="p-1 h-auto hover:bg-gray-700"
                onClick={() => setShowNewFileDialog(true)}
                title="New File"
              >
                <Plus size={14} className="text-gray-400" />
              </Button>
            )}
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
            {(searchTerm ? filteredTree : fileTree).map((node, index, array) => {
              const isLast = index === array.length - 1
              return renderFileNode(node, 0, [isLast])
            })}
            {fileTree.length === 0 && !isLoading && (
              <div className="text-gray-500 text-sm text-center py-8">
                No files found
              </div>
            )}
          </div>
        )}
      </div>

      {/* Context Menu */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          className="fixed bg-gray-800 border border-gray-600 rounded shadow-lg py-1 z-50 min-w-[180px]"
          style={{
            left: `${contextMenu.x}px`,
            top: `${contextMenu.y}px`
          }}
        >
          <button
            className="w-full px-4 py-2 text-left text-sm text-gray-200 hover:bg-gray-700 flex items-center gap-2"
            onClick={handleNewFile}
          >
            <FilePlus size={14} />
            New File
          </button>
          <button
            className="w-full px-4 py-2 text-left text-sm text-gray-200 hover:bg-gray-700 flex items-center gap-2"
            onClick={handleNewFolder}
          >
            <FolderPlus size={14} />
            New Folder
          </button>
          <div className="border-t border-gray-600 my-1" />
          <button
            className="w-full px-4 py-2 text-left text-sm text-gray-200 hover:bg-gray-700 flex items-center gap-2"
            onClick={handleRename}
          >
            <Edit2 size={14} />
            Rename
          </button>
          <button
            className="w-full px-4 py-2 text-left text-sm text-red-400 hover:bg-gray-700 flex items-center gap-2"
            onClick={handleDelete}
          >
            <Trash2 size={14} />
            Delete
          </button>
        </div>
      )}

      {/* New File Dialog */}
      <Dialog open={showNewFileDialog} onOpenChange={setShowNewFileDialog}>
        <DialogContent className="bg-gray-900 border-gray-700 text-white sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle className="text-xl font-semibold text-white">Create New File</DialogTitle>
            <DialogDescription className="text-gray-400">
              Enter a filename with the appropriate extension (e.g., main.py, app.js, data.json)
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <label className="text-sm font-medium text-gray-300 mb-2 block">
                Filename
              </label>
              <Input
                type="text"
                placeholder="example.py"
                value={newFileName}
                onChange={(e) => setNewFileName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newFileName.trim()) {
                    handleCreateFile()
                  }
                }}
                className="bg-gray-800 border-gray-600 text-white placeholder:text-gray-500 focus:border-purple-500"
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <Button
                variant="outline"
                onClick={() => {
                  setShowNewFileDialog(false)
                  setNewFileName('')
                }}
                className="border-gray-600 text-gray-300 hover:bg-gray-800"
              >
                Cancel
              </Button>
              <Button
                onClick={handleCreateFile}
                disabled={!newFileName.trim()}
                className="bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 text-white"
              >
                <FilePlus className="w-4 h-4 mr-2" />
                Create File
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}