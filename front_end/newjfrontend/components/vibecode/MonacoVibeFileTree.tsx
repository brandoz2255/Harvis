"use client"

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { toWorkspaceRelativePath } from '@/lib/strings'
import {
  ChevronRight,
  ChevronDown,
  Loader2,
  FilePlus,
  FolderPlus,
  Edit2,
  Trash2,
  X,
  Check,
  Plus,
  RefreshCw,
  Search
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { FileIcon, FolderIcon } from '@/lib/file-icons'

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
  compact?: boolean
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
  compact = false,
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

  const [showNewFileDialog, setShowNewFileDialog] = useState(false)
  const [newFileName, setNewFileName] = useState('')
  const [draggedNode, setDraggedNode] = useState<FileTreeNode | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)

  const contextMenuRef = useRef<HTMLDivElement>(null)
  const lastCallRef = useRef<number>(0)

  // Load file tree
  const loadFileTree = useCallback(async () => {
    if (!sessionId) return

    const now = Date.now()
    if (lastCallRef.current && now - lastCallRef.current < 2000) return
    lastCallRef.current = now

    if (isLoading) return

    try {
      setIsLoading(true)
      const token = localStorage.getItem('token')
      if (!token) {
        setFileTree([])
        setIsLoading(false)
        return
      }

      const response = await fetch('/api/vibecode/files/tree', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: '/workspace'
        })
      })

      if (response.ok) {
        const data = await response.json()
        const toNode = (n: Record<string, unknown>): FileTreeNode => ({
          name: n.name as string,
          type: n.type as 'file' | 'directory',
          path: n.path as string,
          size: n.size as number | undefined,
          children: Array.isArray(n.children) ? n.children.map(toNode) : undefined
        })
        const root = toNode(data)
        const children = root.children || []
        setFileTree(children)
      } else {
        setFileTree([])
      }
    } catch (error) {
      console.error('Error loading file tree:', error)
    } finally {
      setIsLoading(false)
    }
  }, [sessionId, isLoading])

  // Load file content
  const loadFileContent = useCallback(async (filePath: string): Promise<string> => {
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
        setFileCache(prev => new Map(prev.set(filePath, content)))
        return content
      }
      return ''
    } catch (error) {
      console.error('Error loading file content:', error)
      return ''
    }
  }, [sessionId, fileCache])

  // Create new file
  const createFile = useCallback(async (parentPath: string, fileName: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return false

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
        await loadFileTree()
        return true
      }
      return false
    } catch (error) {
      console.error('Error creating file:', error)
      return false
    }
  }, [sessionId, loadFileTree])

  // Create new folder
  const createFolder = useCallback(async (parentPath: string, folderName: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return false

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
        await loadFileTree()
        setExpandedNodes(prev => new Set(prev.add(parentPath)))
        return true
      }
      return false
    } catch (error) {
      console.error('Error creating folder:', error)
      return false
    }
  }, [sessionId, loadFileTree])

  // Rename
  const renameItem = useCallback(async (oldPath: string, newName: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return false

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
        await loadFileTree()
        return true
      }
      return false
    } catch (error) {
      console.error('Error renaming:', error)
      return false
    }
  }, [sessionId, loadFileTree])

  // Delete
  const deleteItem = useCallback(async (path: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return false

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
        await loadFileTree()
        if (selectedFile === path) {
          setSelectedFile(null)
        }
        return true
      }
      return false
    } catch (error) {
      console.error('Error deleting:', error)
      return false
    }
  }, [sessionId, loadFileTree, selectedFile])

  // Move
  const moveItem = useCallback(async (sourcePath: string, targetDir: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return false

      if (!targetDir.startsWith('/workspace')) return false
      if (targetDir.startsWith(sourcePath + '/') || targetDir === sourcePath) return false

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
        await loadFileTree()
        setExpandedNodes(prev => new Set(prev.add(targetDir)))
        return true
      }
      return false
    } catch (error) {
      console.error('Error moving:', error)
      return false
    }
  }, [sessionId, loadFileTree])

  // Handle file click
  const handleFileClick = useCallback(async (node: FileTreeNode) => {
    if (node.type === 'file') {
      setSelectedFile(node.path)
      const content = await loadFileContent(node.path)
      onFileSelect(node.path, content)
    } else {
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

  // Context menu handlers
  const handleContextMenu = useCallback((e: React.MouseEvent, node: FileTreeNode) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ x: e.clientX, y: e.clientY, node })
  }, [])

  const closeContextMenu = useCallback(() => {
    setContextMenu(null)
  }, [])

  const handleNewFile = useCallback(async () => {
    const node = contextMenu?.node
    if (!node) return
    const parentPath = node.type === 'directory' ? node.path : node.path.split('/').slice(0, -1).join('/')
    const fileName = prompt('Enter file name:')
    if (fileName?.trim()) {
      await createFile(parentPath, fileName.trim())
    }
    closeContextMenu()
  }, [contextMenu, createFile, closeContextMenu])

  const handleCreateFile = useCallback(async () => {
    if (!newFileName.trim()) return
    try {
      await createFile('/workspace', newFileName.trim())
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
    if (folderName?.trim()) {
      await createFolder(parentPath, folderName.trim())
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

  const confirmRename = useCallback(async (oldPath: string) => {
    const trimmedValue = renameValue.trim()
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

  // Drag and drop
  const handleDragStart = useCallback((e: React.DragEvent, node: FileTreeNode) => {
    e.stopPropagation()
    setDraggedNode(node)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', node.path)
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.style.opacity = '0.5'
    }
  }, [])

  const handleDragEnd = useCallback((e: React.DragEvent) => {
    e.stopPropagation()
    setDraggedNode(null)
    setDropTarget(null)
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.style.opacity = '1'
    }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent, node: FileTreeNode) => {
    e.preventDefault()
    e.stopPropagation()
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

    if (targetNode.type !== 'directory' || !draggedNode) {
      setDraggedNode(null)
      return
    }
    if (targetNode.path === draggedNode.path) {
      setDraggedNode(null)
      return
    }

    await moveItem(draggedNode.path, targetNode.path)
    setDraggedNode(null)
  }, [draggedNode, moveItem])

  // Filter tree
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

  useEffect(() => {
    setFilteredTree(filterTree(fileTree, searchTerm))
  }, [fileTree, searchTerm, filterTree])

  // Render file node
  const renderFileNode = useCallback((node: FileTreeNode, depth = 0, isLastArray: boolean[] = []) => {
    const isExpanded = expandedNodes.has(node.path)
    const isSelected = selectedFile === node.path
    const isRenaming = renamingNode === node.path
    const isDeleting = showDeleteConfirm === node.path
    const isDropTargetNode = dropTarget === node.path

    return (
      <div key={node.path} className="relative">
        {depth > 0 && (
          <div className="absolute left-0 top-0 bottom-0 pointer-events-none" style={{ width: `${depth * 16}px` }}>
            {Array.from({ length: depth }).map((_, i) => {
              const showLine = i < isLastArray.length ? !isLastArray[i] : true
              return showLine ? (
                <div
                  key={i}
                  className="absolute top-0 bottom-0 w-px bg-secondary"
                  style={{ left: `${i * 16 + 8}px` }}
                />
              ) : null
            })}
            <div
              className="absolute w-3 h-px bg-secondary"
              style={{
                left: `${(depth - 1) * 16 + 8}px`,
                top: '14px'
              }}
            />
          </div>
        )}

        <div
          className={`flex items-center py-1 px-2 hover:bg-secondary cursor-pointer rounded relative transition-colors z-10 ${isSelected ? 'bg-secondary' : ''
            } ${isDropTargetNode ? 'bg-blue-600/30 border-2 border-blue-500' : ''
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
            <span className="mr-1 text-muted-foreground z-20">
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
                  if (e.key === 'Enter') confirmRename(node.path)
                  else if (e.key === 'Escape') cancelRename()
                }}
                className="h-6 text-xs bg-muted border-border text-foreground px-2"
                autoFocus
              />
              <Button size="sm" variant="ghost" onClick={() => confirmRename(node.path)} className="h-6 w-6 p-0">
                <Check size={12} />
              </Button>
              <Button size="sm" variant="ghost" onClick={cancelRename} className="h-6 w-6 p-0">
                <X size={12} />
              </Button>
            </div>
          ) : (
            <>
              <span className="text-sm text-foreground truncate flex-1">{node.name}</span>
              {node.size !== undefined && (
                <span className="ml-auto text-xs text-muted-foreground/60">
                  {node.size < 1024 ? `${node.size}B` : `${(node.size / 1024).toFixed(1)}KB`}
                </span>
              )}
            </>
          )}
        </div>

        {isDeleting && (
          <div className="flex items-center gap-1 ml-2">
            <Button
              size="sm" variant="ghost"
              onClick={(e) => { e.stopPropagation(); confirmDelete(node.path) }}
              className="h-6 px-2 bg-red-600 hover:bg-red-700 text-white text-xs"
            >
              Delete
            </Button>
            <Button
              size="sm" variant="ghost"
              onClick={(e) => { e.stopPropagation(); setShowDeleteConfirm(null) }}
              className="h-6 px-2 text-xs"
            >
              Cancel
            </Button>
          </div>
        )}

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
    expandedNodes, selectedFile, renamingNode, showDeleteConfirm, dropTarget,
    renameValue, handleFileClick, handleContextMenu, confirmRename, cancelRename,
    confirmDelete, handleDragStart, handleDragEnd, handleDragOver, handleDragLeave, handleDrop
  ])

  // Initialize
  useEffect(() => {
    if (sessionId && isContainerRunning) {
      loadFileTree()
    }
  }, [sessionId, isContainerRunning])

  // Auto-refresh
  useEffect(() => {
    if (!sessionId || !isContainerRunning) return
    const interval = setInterval(() => {
      if (!isLoading && !selectedFile) {
        loadFileTree()
      }
    }, 10000)
    return () => clearInterval(interval)
  }, [sessionId, isContainerRunning, loadFileTree, isLoading, selectedFile])

  // Close context menu on outside click
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
    <div className={`bg-background border-r border-border flex flex-col h-full ${className}`}>
      {/* Header */}
      <div className="p-3 border-b border-border">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">EXPLORER</h3>
          <div className="flex space-x-1">
            <Button
              onClick={loadFileTree}
              size="sm"
              variant="ghost"
              className="p-1 h-auto hover:bg-secondary"
              disabled={isLoading}
            >
              {isLoading ? (
                <Loader2 size={14} className="animate-spin text-muted-foreground" />
              ) : (
                <RefreshCw size={14} className="text-muted-foreground" />
              )}
            </Button>
            {newFileButton || (
              <Button
                size="sm"
                variant="ghost"
                className="p-1 h-auto hover:bg-secondary"
                onClick={() => setShowNewFileDialog(true)}
                title="New File"
              >
                <Plus size={14} className="text-muted-foreground" />
              </Button>
            )}
          </div>
        </div>

        <div className="relative">
          <Search size={14} className="absolute left-2 top-1/2 transform -translate-y-1/2 text-muted-foreground/60" />
          <Input
            type="text"
            placeholder="Search files..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-8 text-xs bg-muted border-border text-foreground h-7"
          />
        </div>
      </div>

      {/* File Tree */}
      <div className="flex-1 overflow-y-auto">
        {isLoading && fileTree.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-muted-foreground/60">
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
              <div className="text-muted-foreground/60 text-sm text-center py-8">
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
          className="fixed bg-background border border-border rounded shadow-lg py-1 z-50 min-w-[180px]"
          style={{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }}
        >
          <button className="w-full px-4 py-2 text-left text-sm text-foreground hover:bg-secondary flex items-center gap-2" onClick={handleNewFile}>
            <FilePlus size={14} /> New File
          </button>
          <button className="w-full px-4 py-2 text-left text-sm text-foreground hover:bg-secondary flex items-center gap-2" onClick={handleNewFolder}>
            <FolderPlus size={14} /> New Folder
          </button>
          <div className="border-t border-border my-1" />
          <button className="w-full px-4 py-2 text-left text-sm text-foreground hover:bg-secondary flex items-center gap-2" onClick={handleRename}>
            <Edit2 size={14} /> Rename
          </button>
          <button className="w-full px-4 py-2 text-left text-sm text-red-400 hover:bg-secondary flex items-center gap-2" onClick={handleDelete}>
            <Trash2 size={14} /> Delete
          </button>
        </div>
      )}

      {/* New File Dialog */}
      <Dialog open={showNewFileDialog} onOpenChange={setShowNewFileDialog}>
        <DialogContent className="bg-background border-border text-white sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle className="text-xl font-semibold text-white">Create New File</DialogTitle>
            <DialogDescription className="text-muted-foreground">
              Enter a filename with the appropriate extension (e.g., main.py, app.js)
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <label className="text-sm font-medium text-foreground mb-2 block">Filename</label>
              <Input
                type="text"
                placeholder="example.py"
                value={newFileName}
                onChange={(e) => setNewFileName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newFileName.trim()) handleCreateFile()
                }}
                className="bg-background border-border text-white placeholder:text-muted-foreground/60 focus:border-purple-500"
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <Button
                variant="outline"
                onClick={() => { setShowNewFileDialog(false); setNewFileName('') }}
                className="border-border text-foreground hover:bg-background"
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
