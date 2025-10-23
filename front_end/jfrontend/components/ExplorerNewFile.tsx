"use client"

import React, { useState } from 'react'
import { Plus, Loader2, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from './ToastProvider'
import { FilesAPI } from '@/app/ide/lib/api'

interface ExplorerNewFileProps {
  sessionId: string
  currentDir: string
  refreshTree: () => void
  onOpenFile: (filePath: string) => void
  className?: string
}

export default function ExplorerNewFile({ 
  sessionId, 
  currentDir, 
  refreshTree, 
  onOpenFile, 
  className = "" 
}: ExplorerNewFileProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [fileName, setFileName] = useState('')
  const toast = useToast()

  const handleCreate = async () => {
    if (!fileName.trim() || isCreating) return

    try {
      setIsCreating(true)
      
      // Resolve full path
      const fullPath = `${currentDir}/${fileName.trim()}`.replace('//', '/')
      
      const loadingToastId = toast.loading('Creating file...', `Setting up ${fileName}`)
      
      // Create the file
      await FilesAPI.create(sessionId, fullPath, 'file')
      
      // Success!
      toast.dismiss(loadingToastId)
      toast.success('File created!', `${fileName} has been added to your workspace`)
      
      // Reset form and close dialog
      setFileName('')
      setIsOpen(false)
      
      // Refresh tree and open file
      refreshTree()
      onOpenFile(fullPath)
      
    } catch (error: any) {
      console.error('File creation failed:', error)
      
      let errorMessage = 'Failed to create file'
      if (error.message) {
        errorMessage = error.message
      }
      
      toast.error('File creation failed', errorMessage)
    } finally {
      setIsCreating(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !isCreating) {
      handleCreate()
    }
  }

  const getFileIcon = (fileName: string) => {
    const extension = fileName.split('.').pop()?.toLowerCase()
    
    switch (extension) {
      case 'py':
        return '🐍'
      case 'js':
      case 'ts':
      case 'jsx':
      case 'tsx':
        return '📜'
      case 'json':
        return '📋'
      case 'md':
        return '📝'
      case 'html':
        return '🌐'
      case 'css':
        return '🎨'
      case 'sql':
        return '🗄️'
      default:
        return '📄'
    }
  }

  return (
    <>
      <Button
        onClick={() => setIsOpen(true)}
        size="sm"
        variant="ghost"
        className="p-1 h-auto hover:bg-gray-700"
        disabled={isCreating}
        title="New File"
      >
        {isCreating ? (
          <Loader2 size={14} className="animate-spin text-gray-400" />
        ) : (
          <Plus size={14} className="text-gray-400" />
        )}
      </Button>

      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="bg-gray-900 border-gray-600 text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="text-gray-300">Create New File</DialogTitle>
          </DialogHeader>
          
          <div className="space-y-4 pt-4">
            <div>
              <label className="text-sm font-medium text-gray-300 mb-2 block">
                File Name
              </label>
              <div className="flex items-center gap-2">
                <span className="text-2xl">{getFileIcon(fileName || 'file.txt')}</span>
                <Input
                  value={fileName}
                  onChange={(e) => setFileName(e.target.value)}
                  placeholder="hello.py"
                  className="bg-gray-800 border-gray-600 text-white flex-1"
                  onKeyPress={handleKeyPress}
                  disabled={isCreating}
                  autoFocus
                />
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Include the file extension (e.g., .py, .js, .json, .md)
              </p>
            </div>
            
            <div className="flex space-x-2 pt-4">
              <Button
                onClick={handleCreate}
                disabled={!fileName.trim() || isCreating}
                className="bg-blue-600 hover:bg-blue-700 text-white flex-1"
              >
                {isCreating ? (
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                ) : (
                  <FileText className="w-4 h-4 mr-2" />
                )}
                {isCreating ? 'Creating...' : 'Create File'}
              </Button>
              
              <Button
                onClick={() => setIsOpen(false)}
                variant="outline"
                className="border-gray-600 text-gray-300"
                disabled={isCreating}
              >
                Cancel
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
