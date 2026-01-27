"use client"

import React, { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronRight,
  ChevronDown,
  File,
  Folder,
  FolderOpen,
  Plus,
  Download,
  Trash2,
  Edit,
  Copy,
  Move,
  MoreHorizontal,
  FileText,
  Sparkles
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

export interface FileTreeNode {
  id: string
  name: string
  type: 'file' | 'folder'
  parentId?: string
  path: string
  content?: string
  language?: string
  size?: number
  children?: FileTreeNode[]
  isExpanded?: boolean
  isModified?: boolean
  createdAt: Date
  updatedAt: Date
}

interface VibeFileTreeProps {
  sessionId: string
  files: FileTreeNode[]
  selectedFileId?: string
  onFileSelect: (file: FileTreeNode) => void
  onFileCreate: (parentId: string | null, name: string, type: 'file' | 'folder') => void
  onFileRename: (fileId: string, newName: string) => void
  onFileDelete: (fileId: string) => void
  onFileMove: (fileId: string, newParentId: string | null) => void
  onDownload: (fileId: string, isFolder: boolean) => void
  onToggleExpanded: (fileId: string) => void
  isLoading?: boolean
}

interface ContextMenuProps {
  x: number
  y: number
  node: FileTreeNode
  onClose: () => void
  onAction: (action: string, node: FileTreeNode) => void
}

function ContextMenu({ x, y, node, onClose, onAction }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [onClose])

  const menuItems = [
    { id: 'rename', label: 'Rename', icon: Edit },
    { id: 'duplicate', label: 'Duplicate', icon: Copy },
    { id: 'download', label: 'Download', icon: Download },
    { id: 'delete', label: 'Delete', icon: Trash2, danger: true },
  ]

  if (node.type === 'folder') {
    menuItems.unshift(
      { id: 'new-file', label: 'New File', icon: FileText },
      { id: 'new-folder', label: 'New Folder', icon: Folder }
    )
  }

  return (
    <motion.div
      ref={menuRef}
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="fixed bg-gray-800 border border-gray-600 rounded-lg shadow-lg z-50 py-1 min-w-[140px]"
      style={{ left: x, top: y }}
    >
      {menuItems.map((item) => (
        <button
          key={item.id}
          className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-700 flex items-center space-x-2 ${
            item.danger ? 'text-red-400 hover:text-red-300' : 'text-gray-300 hover:text-white'
          }`}
          onClick={() => {
            onAction(item.id, node)
            onClose()
          }}
        >
          <item.icon className="w-4 h-4" />
          <span>{item.label}</span>
        </button>
      ))}
    </motion.div>
  )
}

function FileTreeItem({ 
  node, 
  level = 0, 
  selectedFileId, 
  onFileSelect, 
  onToggleExpanded, 
  onContextMenu,
  draggedNode,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDrop
}: {
  node: FileTreeNode
  level: number
  selectedFileId?: string
  onFileSelect: (file: FileTreeNode) => void
  onToggleExpanded: (fileId: string) => void
  onContextMenu: (event: React.MouseEvent, node: FileTreeNode) => void
  draggedNode?: FileTreeNode | null
  onDragStart: (node: FileTreeNode) => void
  onDragOver: (event: React.DragEvent) => void
  onDragLeave: () => void
  onDrop: (event: React.DragEvent, targetNode: FileTreeNode) => void
}) {
  const [dragOver, setDragOver] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [newName, setNewName] = useState(node.name)

  const isSelected = selectedFileId === node.id
  const hasChildren = node.children && node.children.length > 0
  const canExpand = node.type === 'folder'

  const handleToggle = () => {
    if (canExpand) {
      onToggleExpanded(node.id)
    }
  }

  const handleSelect = () => {
    if (node.type === 'file') {
      onFileSelect(node)
    } else {
      handleToggle()
    }
  }

  const handleDragStart = (event: React.DragEvent) => {
    onDragStart(node)
    event.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (event: React.DragEvent) => {
    if (node.type === 'folder' && draggedNode && draggedNode.id !== node.id) {
      event.preventDefault()
      setDragOver(true)
      onDragOver(event)
    }
  }

  const handleDragLeave = () => {
    setDragOver(false)
    onDragLeave()
  }

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setDragOver(false)
    onDrop(event, node)
  }

  const getFileIcon = (file: FileTreeNode) => {
    if (file.type === 'folder') {
      return file.isExpanded ? FolderOpen : Folder
    }
    return FileText
  }

  const getLanguageBadge = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase()
    const langMap: { [key: string]: string } = {
      'py': 'Python',
      'js': 'JS',
      'jsx': 'JSX',
      'ts': 'TS',
      'tsx': 'TSX',
      'html': 'HTML',
      'css': 'CSS',
      'json': 'JSON',
      'md': 'MD',
      'sql': 'SQL'
    }
    return langMap[ext || ''] || ext?.toUpperCase() || ''
  }

  const IconComponent = getFileIcon(node)

  return (
    <div>
      <div
        className={`flex items-center space-x-2 py-1 px-2 rounded cursor-pointer transition-all duration-200 ${
          isSelected
            ? 'bg-purple-600/30 border border-purple-500/50 text-white'
            : dragOver
            ? 'bg-blue-600/30 border border-blue-500/50 text-white'
            : 'hover:bg-gray-700/50 text-gray-300 hover:text-white'
        }`}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        draggable
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleSelect}
        onContextMenu={(e) => {
          e.preventDefault()
          onContextMenu(e, node)
        }}
      >
        {/* Expand/Collapse Icon */}
        {canExpand && (
          <button onClick={(e) => { e.stopPropagation(); handleToggle() }} className="p-0.5">
            {node.isExpanded ? (
              <ChevronDown className="w-4 h-4 text-gray-400" />
            ) : (
              <ChevronRight className="w-4 h-4 text-gray-400" />
            )}
          </button>
        )}

        {/* File/Folder Icon */}
        <IconComponent className={`w-4 h-4 flex-shrink-0 ${
          node.type === 'folder' ? 'text-blue-400' : 'text-purple-400'
        }`} />

        {/* Name */}
        <div className="flex-1 flex items-center space-x-2 min-w-0">
          {editingName ? (
            <Input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onBlur={() => setEditingName(false)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  setEditingName(false)
                  // Handle rename
                } else if (e.key === 'Escape') {
                  setNewName(node.name)
                  setEditingName(false)
                }
              }}
              className="h-6 text-xs bg-gray-700 border-gray-600"
              autoFocus
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <>
              <span className="text-sm truncate">{node.name}</span>
              {node.type === 'file' && getLanguageBadge(node.name) && (
                <Badge variant="outline" className="text-xs px-1 py-0 h-4 border-gray-600 text-gray-400">
                  {getLanguageBadge(node.name)}
                </Badge>
              )}
            </>
          )}
        </div>

        {/* Modified indicator */}
        {node.isModified && (
          <div className="w-2 h-2 bg-orange-400 rounded-full flex-shrink-0" />
        )}
      </div>

      {/* Children */}
      <AnimatePresence>
        {canExpand && node.isExpanded && hasChildren && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
          >
            {node.children?.map((child) => (
              <FileTreeItem
                key={child.id}
                node={child}
                level={level + 1}
                selectedFileId={selectedFileId}
                onFileSelect={onFileSelect}
                onToggleExpanded={onToggleExpanded}
                onContextMenu={onContextMenu}
                draggedNode={draggedNode}
                onDragStart={onDragStart}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function VibeFileTree({
  sessionId,
  files,
  selectedFileId,
  onFileSelect,
  onFileCreate,
  onFileRename,
  onFileDelete,
  onFileMove,
  onDownload,
  onToggleExpanded,
  isLoading = false
}: VibeFileTreeProps) {
  const [contextMenu, setContextMenu] = useState<{
    x: number
    y: number
    node: FileTreeNode
  } | null>(null)
  const [draggedNode, setDraggedNode] = useState<FileTreeNode | null>(null)
  const [showCreateDialog, setShowCreateDialog] = useState<{
    parentId: string | null
    type: 'file' | 'folder'
  } | null>(null)
  const [newItemName, setNewItemName] = useState('')

  const handleContextMenu = (event: React.MouseEvent, node: FileTreeNode) => {
    event.preventDefault()
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      node
    })
  }

  const handleContextAction = async (action: string, node: FileTreeNode) => {
    switch (action) {
      case 'new-file':
        setShowCreateDialog({ parentId: node.id, type: 'file' })
        break
      case 'new-folder':
        setShowCreateDialog({ parentId: node.id, type: 'folder' })
        break
      case 'rename':
        const newName = prompt('Enter new name:', node.name)
        if (newName && newName !== node.name) {
          onFileRename(node.id, newName)
        }
        break
      case 'duplicate':
        const duplicateName = `${node.name}_copy`
        onFileCreate(node.parentId || null, duplicateName, node.type)
        break
      case 'download':
        onDownload(node.id, node.type === 'folder')
        break
      case 'delete':
        if (confirm(`Are you sure you want to delete "${node.name}"?`)) {
          onFileDelete(node.id)
        }
        break
    }
  }

  const handleDragStart = (node: FileTreeNode) => {
    setDraggedNode(node)
  }

  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault()
  }

  const handleDragLeave = () => {
    // Handle drag leave if needed
  }

  const handleDrop = (event: React.DragEvent, targetNode: FileTreeNode) => {
    event.preventDefault()
    if (draggedNode && targetNode.type === 'folder' && draggedNode.id !== targetNode.id) {
      onFileMove(draggedNode.id, targetNode.id)
    }
    setDraggedNode(null)
  }

  const handleCreateItem = () => {
    if (showCreateDialog && newItemName.trim()) {
      onFileCreate(showCreateDialog.parentId, newItemName.trim(), showCreateDialog.type)
      setNewItemName('')
      setShowCreateDialog(null)
    }
  }

  // Build tree structure
  const buildTree = (nodes: FileTreeNode[]): FileTreeNode[] => {
    const nodeMap = new Map(nodes.map(node => [node.id, { ...node, children: [] as FileTreeNode[] }]))
    const rootNodes: FileTreeNode[] = []

    for (const node of nodes) {
      const treeNode = nodeMap.get(node.id)!
      if (node.parentId && nodeMap.has(node.parentId)) {
        const parent = nodeMap.get(node.parentId)!
        if (!parent.children) parent.children = []
        parent.children.push(treeNode)
      } else {
        rootNodes.push(treeNode)
      }
    }

    // Sort: folders first, then files, both alphabetically
    const sortNodes = (nodes: FileTreeNode[]): FileTreeNode[] => {
      return nodes.sort((a, b) => {
        if (a.type !== b.type) {
          return a.type === 'folder' ? -1 : 1
        }
        return a.name.localeCompare(b.name)
      }).map(node => ({
        ...node,
        children: node.children ? sortNodes(node.children) : undefined
      }))
    }

    return sortNodes(rootNodes)
  }

  const treeStructure = buildTree(files)

  return (
    <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30 h-full flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-purple-500/30">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Folder className="w-5 h-5 text-purple-400" />
            <h3 className="text-lg font-semibold text-purple-300">Files</h3>
            <Badge variant="outline" className="border-purple-500 text-purple-400 text-xs">
              {files.length}
            </Badge>
          </div>
          <div className="flex space-x-1">
            <Button
              onClick={() => setShowCreateDialog({ parentId: null, type: 'file' })}
              size="sm"
              className="bg-purple-600 hover:bg-purple-700 text-white"
              title="New File"
            >
              <Plus className="w-3 h-3 mr-1" />
              File
            </Button>
            <Button
              onClick={() => setShowCreateDialog({ parentId: null, type: 'folder' })}
              size="sm"
              variant="outline"
              className="bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600"
              title="New Folder"
            >
              <Plus className="w-3 h-3 mr-1" />
              Folder
            </Button>
          </div>
        </div>
      </div>

      {/* File Tree */}
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="flex items-center justify-center h-32 text-gray-400">
            <Sparkles className="w-5 h-5 animate-spin mr-2" />
            Loading files...
          </div>
        ) : treeStructure.length === 0 ? (
          <div className="text-center text-gray-400 py-8">
            <Folder className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p className="mb-2">No files yet</p>
            <p className="text-sm">Create your first file or folder to get started</p>
          </div>
        ) : (
          <div className="space-y-1">
            {treeStructure.map((node) => (
              <FileTreeItem
                key={node.id}
                node={node}
                level={0}
                selectedFileId={selectedFileId}
                onFileSelect={onFileSelect}
                onToggleExpanded={onToggleExpanded}
                onContextMenu={handleContextMenu}
                draggedNode={draggedNode}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              />
            ))}
          </div>
        )}
      </div>

      {/* Context Menu */}
      <AnimatePresence>
        {contextMenu && (
          <ContextMenu
            x={contextMenu.x}
            y={contextMenu.y}
            node={contextMenu.node}
            onClose={() => setContextMenu(null)}
            onAction={handleContextAction}
          />
        )}
      </AnimatePresence>

      {/* Create Item Dialog */}
      <AnimatePresence>
        {showCreateDialog && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-gray-800 rounded-lg p-6 w-96 border border-gray-600"
            >
              <h3 className="text-lg font-semibold text-white mb-4">
                Create New {showCreateDialog.type === 'file' ? 'File' : 'Folder'}
              </h3>
              <Input
                value={newItemName}
                onChange={(e) => setNewItemName(e.target.value)}
                placeholder={showCreateDialog.type === 'file' ? 'filename.py' : 'folder-name'}
                className="mb-4 bg-gray-700 border-gray-600 text-white"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleCreateItem()
                  } else if (e.key === 'Escape') {
                    setShowCreateDialog(null)
                    setNewItemName('')
                  }
                }}
                autoFocus
              />
              <div className="flex space-x-2">
                <Button
                  onClick={handleCreateItem}
                  className="flex-1 bg-purple-600 hover:bg-purple-700 text-white"
                  disabled={!newItemName.trim()}
                >
                  Create
                </Button>
                <Button
                  onClick={() => {
                    setShowCreateDialog(null)
                    setNewItemName('')
                  }}
                  variant="outline"
                  className="flex-1 bg-gray-700 border-gray-600 text-gray-300"
                >
                  Cancel
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  )
}