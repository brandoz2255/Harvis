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

      const response = await fetch('/api/vibecoding/files', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          action: 'list',
          session_id: sessionId,
          path: path
        })
      })

      if (response.ok) {
        const data = await response.json()
        const fileNodes: FileNode[] = data.files.map((file: ContainerFile) => ({
          ...file,
          depth: path.split('/').length - 1,
          isExpanded: expandedPaths.has(file.path),
          children: file.type === 'directory' ? [] : undefined
        }))
        
        if (path === '/workspace') {
          setFiles(fileNodes)
        } else {
          // Update the specific directory in the tree
          setFiles(prev => updateDirectoryInTree(prev, path, fileNodes))
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
      
      const response = await fetch('/api/vibecoding/files', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          action: 'write',
          file_path: filePath,
          content: newFileType === 'file' ? '// New file\n' : ''
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

  const renderFileTree = (nodes: FileNode[]) => {
    return nodes.map((file) => (
      <div key={file.path}>
        <motion.div
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          className={`flex items-center space-x-2 p-2 rounded cursor-pointer hover:bg-gray-700/50 transition-colors ${
            selectedFilePath === file.path ? 'bg-purple-500/20 border-l-2 border-purple-500' : ''
          }`}
          style={{ paddingLeft: `${file.depth * 16 + 8}px` }}
          onClick={() => file.type === 'directory' ? toggleDirectory(file) : handleFileClick(file)}
        >
          {file.type === 'directory' && (
            <div className="w-4 h-4 flex items-center justify-center">
              {expandedPaths.has(file.path) ? (
                <ChevronDown className="w-3 h-3 text-gray-400" />
              ) : (
                <ChevronRight className="w-3 h-3 text-gray-400" />
              )}
            </div>
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
          <div className="ml-2">
            {renderFileTree(file.children)}
          </div>
        )}
      </div>
    ))
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
                  <DialogTitle className="text-blue-300">Create New File</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 pt-4">
                  <div>
                    <label className="text-sm font-medium text-gray-300 mb-2 block">
                      File Name
                    </label>
                    <Input
                      value={newFileName}
                      onChange={(e) => setNewFileName(e.target.value)}
                      placeholder="example.py"
                      className="bg-gray-800 border-gray-600 text-white"
                      onKeyPress={(e) => e.key === 'Enter' && createFile()}
                    />
                  </div>
                  <div className="flex space-x-2 pt-4">
                    <Button
                      onClick={createFile}
                      disabled={!newFileName.trim() || isCreating}
                      className="bg-blue-600 hover:bg-blue-700 text-white flex-1"
                    >
                      {isCreating ? (
                        <Loader2 className="w-4 h-4 animate-spin mr-2" />
                      ) : (
                        <Plus className="w-4 h-4 mr-2" />
                      )}
                      Create File
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