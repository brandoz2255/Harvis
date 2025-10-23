"use client"

import React, { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Plus, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from './ToastProvider'
import { SessionsAPI, Session } from '@/app/ide/lib/api'
import { pollUntil } from '@/app/ide/lib/polling'

interface SessionCreatorProps {
  onReady: (session: Session) => void
  className?: string
}

export default function SessionCreator({ onReady, className = "" }: SessionCreatorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [sessionName, setSessionName] = useState('')
  const [description, setDescription] = useState('')
  const toast = useToast()

  const handleCreate = async () => {
    if (!sessionName.trim() || isCreating) return

    try {
      setIsCreating(true)
      
      // Step 1: Create session
      const loadingToastId = toast.loading('Creating session...', 'Setting up your development environment')
      const createResult = await SessionsAPI.create(sessionName.trim(), description.trim() || undefined)
      
      // Step 2: Start session (start container)
      toast.update(loadingToastId, 'Starting container...', 'Preparing your workspace')
      const startResult = await SessionsAPI.start(createResult.session.session_id)
      
      // Step 3: Wait for container to be ready
      toast.update(loadingToastId, 'Waiting for ready...', 'Finalizing setup')
      
      try {
        await pollUntil({
          fn: () => SessionsAPI.status(createResult.session.session_id),
          isDone: (result) => result.status === 'ready',
          timeoutMs: 30000,
          intervalMs: 2000,
          onProgress: (result) => {
            console.log('Container status:', result.status, 'message:', result.message)
            if (result.message) {
              toast.update(loadingToastId, 'Waiting for ready...', result.message)
            }
          }
        })
        
        // Success!
        toast.dismiss(loadingToastId)
        toast.success('Session ready!', `Your workspace "${sessionName}" is now active`)
        
        // Reset form and close dialog
        setSessionName('')
        setDescription('')
        setIsOpen(false)
        
        // Notify parent
        onReady(createResult.session)
        
      } catch (pollError) {
        // Container might be running but not "ready" - that's okay
        console.warn('Container polling failed, but session might still work:', pollError)
        toast.dismiss(loadingToastId)
        toast.info('Session created', 'Container is starting up, may take a moment to be fully ready')
        
        // Reset form and close dialog
        setSessionName('')
        setDescription('')
        setIsOpen(false)
        
        // Notify parent anyway
        onReady(createResult.session)
      }
      
    } catch (error: any) {
      console.error('Session creation failed:', error)
      
      let errorMessage = 'Failed to create session'
      if (error.message) {
        errorMessage = error.message
      }
      
      toast.error('Session creation failed', errorMessage)
    } finally {
      setIsCreating(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !isCreating) {
      handleCreate()
    }
  }

  return (
    <>
      <Button
        onClick={() => setIsOpen(true)}
        size="sm"
        className="bg-purple-600 hover:bg-purple-700 text-white"
        disabled={isCreating}
      >
        {isCreating ? (
          <Loader2 className="w-4 h-4 animate-spin mr-2" />
        ) : (
          <Plus className="w-4 h-4 mr-2" />
        )}
        New Session
      </Button>

      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="bg-gray-900 border-purple-500/30 text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="text-purple-300">Create New Session</DialogTitle>
          </DialogHeader>
          
          <div className="space-y-4 pt-4">
            <div>
              <label className="text-sm font-medium text-gray-300 mb-2 block">
                Session Name
              </label>
              <Input
                value={sessionName}
                onChange={(e) => setSessionName(e.target.value)}
                placeholder="My Awesome Project"
                className="bg-gray-800 border-gray-600 text-white"
                onKeyPress={handleKeyPress}
                disabled={isCreating}
                autoFocus
              />
            </div>
            
            <div>
              <label className="text-sm font-medium text-gray-300 mb-2 block">
                Description (Optional)
              </label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of your project"
                className="bg-gray-800 border-gray-600 text-white"
                onKeyPress={handleKeyPress}
                disabled={isCreating}
              />
            </div>
            
            <div className="flex space-x-2 pt-4">
              <Button
                onClick={handleCreate}
                disabled={!sessionName.trim() || isCreating}
                className="bg-purple-600 hover:bg-purple-700 text-white flex-1"
              >
                {isCreating ? (
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                ) : (
                  <Plus className="w-4 h-4 mr-2" />
                )}
                {isCreating ? 'Creating...' : 'Create Session'}
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
