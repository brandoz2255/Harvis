"use client"

import React, { useState, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  Folder,
  FolderOpen,
  File,
  FileText,
  Code,
  Image,
  Music,
  Video,
  Archive,
  Plus,
  RefreshCw,
  Edit3,
  Trash2,
  Download,
  Upload,
  Loader2,
  ChevronRight,
  ChevronDown,
  Terminal
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"

interface ContainerFile {
  name: string
  type: 'file' | 'directory'
  size: number
  permissions: string
  path: string
}

interface FileNode extends ContainerFile {
  isExpanded?: boolean
  children?: FileNode[]
  depth: number
}

interface VibeContainerFileExplorerProps {
  sessionId: string | null
  onFileSelect: (file: ContainerFile) => void
  selectedFilePath: string | null
  className?: string
}

export default function VibeContainerFileExplorer({
  sessionId,
  onFileSelect,
  selectedFilePath,
  className = ""
}: VibeContainerFileExplorerProps) {
  const [files, setFiles] = useState<FileNode[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [currentPath, setCurrentPath] = useState('/workspace')
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set(['/workspace']))
  const [isCreating, setIsCreating] = useState(false)
  const [newFileName, setNewFileName] = useState('')
  const [newFileType, setNewFileType] = useState<'file' | 'directory'>('file')
  const [showCreateDialog, setShowCreateDialog] = useState(false)

  // Drag and drop state
  const [draggedItem, setDraggedItem] = useState<FileNode | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const [isMoving, setIsMoving] = useState(false)

  const getFileIcon = (file: ContainerFile) => {
    if (file.type === 'directory') {
      return expandedPaths.has(file.path) ? FolderOpen : Folder
    }

    const extension = file.name.split('.').pop()?.toLowerCase()

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
      case 'ogg':
        return Music
      case 'mp4':
      case 'avi':
      case 'mov':
        return Video
      case 'zip':
      case 'tar':
      case 'gz':
        return Archive
      default:
        return File
    }
  }

  const getFileColor = (file: ContainerFile) => {
    if (file.type === 'directory') return 'text-blue-400'

    const extension = file.name.split('.').pop()?.toLowerCase()

    switch (extension) {
      case 'js':
      case 'ts':
      case 'jsx':
      case 'tsx':
        return 'text-yellow-400'
      case 'py':
        return 'text-green-400'
      case 'java':
        return 'text-red-400'
      case 'cpp':
      case 'c':
        return 'text-blue-500'
      case 'go':
        return 'text-cyan-400'
      case 'rs':
        return 'text-orange-400'
      case 'php':
        return 'text-purple-400'
      case 'rb':
        return 'text-red-500'
      case 'html':
        return 'text-orange-500'
      case 'css':
        return 'text-blue-600'
      case 'json':
        return 'text-green-500'
      case 'md':
        return 'text-gray-400'
      default:
        return 'text-gray-300'
    }
  }

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
  }

  const updateDirectoryInTree = useCallback((tree: FileNode[], targetPath: string, newFiles: FileNode[]): FileNode[] => {
    return tree.map(node => {
      if (node.path === targetPath && node.type === 'directory') {
        return { ...node, children: newFiles }
      } else if (node.children) {
        return { ...node, children: updateDirectoryInTree(node.children, targetPath, newFiles) }
      }
      return node
    })
  }, [])

  const loadFiles = useCallback(async (path: string = '/workspace') => {
    if (!sessionId) return

    try {
      setIsLoading(true)
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch('/api/vibecode/files/tree', {
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
        const data = await response.json()
        // Backend returns the tree rooted at `path`; use its children
        const toNode = (n: any): FileNode => ({
          name: n.name,
          type: n.type,
          size: n.size,
          permissions: n.permissions,
          path: n.path,
          depth: path.split('/').length - 1,
          isExpanded: expandedPaths.has(n.path),
          children: Array.isArray(n.children) ? n.children.map(toNode) : undefined
        })
        const root = toNode(data)
        const children = (root.children || []) as FileNode[]
        if (path === '/workspace') {
          setFiles(children)
        } else {
          setFiles(prev => updateDirectoryInTree(prev, path, children))
        }
      }
    } catch (error) {
      console.error('Failed to load files:', error)
    } finally {
      setIsLoading(false)
    }
  }, [sessionId, expandedPaths, updateDirectoryInTree])

  useEffect(() => {
    if (sessionId) {
      loadFiles('/workspace')
    }
  }, [sessionId, loadFiles])

  const toggleDirectory = async (file: FileNode) => {
    if (file.type !== 'directory') return

    const newExpandedPaths = new Set(expandedPaths)

    if (expandedPaths.has(file.path)) {
      newExpandedPaths.delete(file.path)
    } else {
      newExpandedPaths.add(file.path)
      // Load directory contents if not already loaded
      if (!file.children || file.children.length === 0) {
        await loadFiles(file.path)
      }
    }

    setExpandedPaths(newExpandedPaths)
  }

  const handleFileClick = (file: ContainerFile) => {
    if (file.type === 'file') {
      onFileSelect(file)
    }
  }

  const createFile = async () => {
    if (!newFileName.trim() || !sessionId) return

    try {
      setIsCreating(true)
      const token = localStorage.getItem('token')
      if (!token) return

      const filePath = `${currentPath}/${newFileName}`.replace('//', '/')

      const response = await fetch('/api/vibecode/files/create', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: filePath,
          type: newFileType === 'file' ? 'file' : 'folder'
        })
      })

      if (response.ok) {
        await loadFiles(currentPath)
        setNewFileName('')
        setShowCreateDialog(false)
      }
    } catch (error) {
      console.error('Failed to create file:', error)
    } finally {
      setIsCreating(false)
    }
  }

  // Move file/folder to a new location
  const moveFile = async (sourcePath: string, targetDir: string) => {
    if (!sessionId || isMoving) return

    try {
      setIsMoving(true)
      const token = localStorage.getItem('token')
      if (!token) {
        console.error('❌ No authentication token found')
        return
      }

      console.log('🚚 Moving file:', {
        from: sourcePath,
        to: targetDir,
        sessionId: sessionId
      })

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
        const result = await response.json()
        console.log('✅ File moved successfully:', result)
        await loadFiles(currentPath)
        // Also refresh the target directory to show the moved file
        if (targetDir !== currentPath) {
          await loadFiles(targetDir)
        }
      } else {
        const errorText = await response.text()
        console.error('❌ Failed to move file:', {
          status: response.status,
          error: errorText
        })
        alert(`Failed to move file: ${errorText}`)
      }
    } catch (error) {
      console.error('❌ Move file error:', error)
      alert(`Error moving file: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsMoving(false)
      setDraggedItem(null)
      setDropTarget(null)
    }
  }

  // Drag and drop handlers
  const handleDragStart = (e: React.DragEvent, file: FileNode) => {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', file.path)
    setDraggedItem(file)
  }

  const handleDragOver = (e: React.DragEvent, file: FileNode) => {
    e.preventDefault()
    e.stopPropagation()

    // Only allow dropping on directories or the workspace root
    if (file.type === 'directory' && draggedItem && file.path !== draggedItem.path) {
      e.dataTransfer.dropEffect = 'move'
      setDropTarget(file.path)
    }
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setDropTarget(null)
  }

  const handleDrop = async (e: React.DragEvent, targetFile: FileNode) => {
    e.preventDefault()
    e.stopPropagation()

    console.log('🎯 Drop event:', {
      draggedItem: draggedItem?.path,
      targetFile: targetFile.path,
      targetType: targetFile.type
    })

    // Validation checks
    if (!draggedItem) {
      console.log('❌ No dragged item')
      setDropTarget(null)
      return
    }

    if (targetFile.type !== 'directory') {
      console.log('❌ Target is not a directory')
      setDropTarget(null)
      return
    }

    // Don't allow dropping on itself
    if (targetFile.path === draggedItem.path) {
      console.log('❌ Cannot drop on itself')
      setDropTarget(null)
      return
    }

    // Don't allow dropping on its children (prevent circular moves)
    if (targetFile.path.startsWith(draggedItem.path + '/')) {
      console.log('❌ Cannot drop on child directory')
      setDropTarget(null)
      return
    }

    // All validations passed, proceed with move
    console.log('✅ Validation passed, moving file...')
    await moveFile(draggedItem.path, targetFile.path)
  }

  const handleDragEnd = () => {
    setDraggedItem(null)
    setDropTarget(null)
  }

  const renderFileTree = (nodes: FileNode[], parentDepth: number = 0, isLastArray: boolean[] = []) => {
    return nodes.map((file, index) => {
      const isLast = index === nodes.length - 1
      const currentIsLastArray = [...isLastArray, isLast]

      return (
        <div key={file.path} className="relative">
          {/* Tree branch lines */}
          {file.depth > 0 && (
            <div className="absolute left-0 top-0 bottom-0 pointer-events-none" style={{ width: `${file.depth * 16}px` }}>
              {/* Vertical lines for parent levels */}
              {Array.from({ length: file.depth }).map((_, i) => {
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
                  left: `${(file.depth - 1) * 16 + 8}px`,
                  top: '50%'
                }}
              />
              {/* L-shaped corner for last item */}
              {isLast && (
                <div
                  className="absolute w-px bg-gray-600"
                  style={{
                    left: `${(file.depth - 1) * 16 + 8}px`,
                    top: 0,
                    height: '50%'
                  }}
                />
              )}
            </div>
          )}

          <motion.div
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            draggable
            onDragStart={(e) => handleDragStart(e as unknown as React.DragEvent, file)}
            onDragOver={(e) => handleDragOver(e as unknown as React.DragEvent, file)}
            onDragLeave={(e) => handleDragLeave(e as unknown as React.DragEvent)}
            onDrop={(e) => handleDrop(e as unknown as React.DragEvent, file)}
            onDragEnd={handleDragEnd}
            className={`flex items-center space-x-2 py-1.5 px-2 rounded cursor-pointer hover:bg-gray-700/50 transition-colors ${selectedFilePath === file.path ? 'bg-purple-500/20 border-l-2 border-purple-500' : ''
              } ${dropTarget === file.path ? 'bg-blue-500/30 border-2 border-blue-400 border-dashed' : ''
              } ${draggedItem?.path === file.path ? 'opacity-50' : ''
              }`}
            style={{ paddingLeft: `${file.depth * 16 + 8}px` }}
            onClick={() => file.type === 'directory' ? toggleDirectory(file) : handleFileClick(file)}
          >
            {file.type === 'directory' && (
              <div className="w-4 h-4 flex items-center justify-center flex-shrink-0">
                {expandedPaths.has(file.path) ? (
                  <ChevronDown className="w-3 h-3 text-gray-400" />
                ) : (
                  <ChevronRight className="w-3 h-3 text-gray-400" />
                )}
              </div>
            )}

            {file.type === 'file' && (
              <div className="w-4 h-4 flex-shrink-0" />
            )}

            {React.createElement(getFileIcon(file), {
              className: `w-4 h-4 ${getFileColor(file)} flex-shrink-0`
            })}

            <span className={`text-sm truncate flex-1 ${getFileColor(file)}`}>
              {file.name}
            </span>

            {file.type === 'file' && (
              <span className="text-xs text-gray-500 flex-shrink-0">
                {formatFileSize(file.size)}
              </span>
            )}
          </motion.div>

          {file.type === 'directory' && expandedPaths.has(file.path) && file.children && (
            <div>
              {renderFileTree(file.children, file.depth, currentIsLastArray)}
            </div>
          )}
        </div>
      )
    })
  }

  return (
    <Card className={`bg-gray-900/50 backdrop-blur-sm border-blue-500/30 flex flex-col ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-blue-500/30 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Terminal className="w-5 h-5 text-blue-400" />
            <h3 className="text-lg font-semibold text-blue-300">Container Files</h3>
            {sessionId && (
              <Badge variant="outline" className="border-blue-500 text-blue-400 text-xs">
                {currentPath}
              </Badge>
            )}
          </div>

          <div className="flex items-center space-x-2">
            <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
              <DialogTrigger asChild>
                <Button
                  size="sm"
                  className="bg-blue-600 hover:bg-blue-700 text-white"
                  disabled={!sessionId}
                >
                  <Plus className="w-3 h-3 mr-1" />
                  New
                </Button>
              </DialogTrigger>
              <DialogContent className="bg-gray-900 border-blue-500/30 text-white">
                <DialogHeader>
                  <DialogTitle className="text-blue-300">
                    Create New {newFileType === 'file' ? 'File' : 'Folder'}
                  </DialogTitle>
                </DialogHeader>
                <div className="space-y-4 pt-4">
                  {/* Type selector */}
                  <div>
                    <label className="text-sm font-medium text-gray-300 mb-2 block">
                      Type
                    </label>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setNewFileType('file')}
                        className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md border transition-colors ${newFileType === 'file'
                            ? 'bg-blue-600 border-blue-500 text-white'
                            : 'bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700'
                          }`}
                      >
                        <File className="w-4 h-4" />
                        File
                      </button>
                      <button
                        onClick={() => setNewFileType('directory')}
                        className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md border transition-colors ${newFileType === 'directory'
                            ? 'bg-blue-600 border-blue-500 text-white'
                            : 'bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700'
                          }`}
                      >
                        <Folder className="w-4 h-4" />
                        Folder
                      </button>
                    </div>
                  </div>

                  {/* Name input */}
                  <div>
                    <label className="text-sm font-medium text-gray-300 mb-2 block">
                      {newFileType === 'file' ? 'File Name' : 'Folder Name'}
                    </label>
                    <Input
                      value={newFileName}
                      onChange={(e) => setNewFileName(e.target.value)}
                      placeholder={newFileType === 'file' ? 'example.py' : 'new-folder'}
                      className="bg-gray-800 border-gray-600 text-white"
                      onKeyPress={(e) => e.key === 'Enter' && createFile()}
                    />
                  </div>

                  {/* Current path indicator */}
                  <div className="text-xs text-gray-500">
                    Will be created in: <span className="text-gray-400">{currentPath}/</span>
                  </div>

                  <div className="flex space-x-2 pt-2">
                    <Button
                      onClick={createFile}
                      disabled={!newFileName.trim() || isCreating}
                      className="bg-blue-600 hover:bg-blue-700 text-white flex-1"
                    >
                      {isCreating ? (
                        <Loader2 className="w-4 h-4 animate-spin mr-2" />
                      ) : newFileType === 'file' ? (
                        <Plus className="w-4 h-4 mr-2" />
                      ) : (
                        <Folder className="w-4 h-4 mr-2" />
                      )}
                      Create {newFileType === 'file' ? 'File' : 'Folder'}
                    </Button>
                    <Button
                      onClick={() => setShowCreateDialog(false)}
                      variant="outline"
                      className="border-gray-600 text-gray-300"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              </DialogContent>
            </Dialog>

            <Button
              onClick={() => loadFiles(currentPath)}
              size="sm"
              variant="outline"
              className="bg-gray-800 border-gray-600 text-gray-300"
              disabled={isLoading || !sessionId}
            >
              {isLoading ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <RefreshCw className="w-3 h-3" />
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* File Tree */}
      <div className="flex-1 overflow-y-auto">
        {!sessionId ? (
          <div className="p-8 text-center">
            <Terminal className="w-12 h-12 text-gray-600 mx-auto mb-4" />
            <p className="text-gray-400">No session selected</p>
            <p className="text-sm text-gray-500">Select a session to browse files</p>
          </div>
        ) : isLoading && files.length === 0 ? (
          <div className="p-8 text-center">
            <Loader2 className="w-8 h-8 animate-spin text-blue-400 mx-auto mb-4" />
            <p className="text-gray-400">Loading container files...</p>
          </div>
        ) : files.length === 0 ? (
          <div className="p-8 text-center">
            <Folder className="w-12 h-12 text-gray-600 mx-auto mb-4" />
            <p className="text-gray-400">No files found</p>
            <p className="text-sm text-gray-500">The container workspace is empty</p>
          </div>
        ) : (
          <div className="p-2">
            <AnimatePresence>
              {renderFileTree(files)}
            </AnimatePresence>
          </div>
        )}
      </div>
    </Card>
  )
}