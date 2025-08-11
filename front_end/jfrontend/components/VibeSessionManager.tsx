"use client"

import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  FolderOpen,
  Plus,
  Settings,
  Clock,
  FileText,
  Play,
  Pause,
  Trash2,
  Edit3,
  Save,
  X,
  Loader2,
  Container,
  Users
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"

interface Session {
  id: string
  session_id: string
  project_name: string
  description?: string
  container_status: 'running' | 'stopped' | 'starting' | 'stopping'
  created_at: string
  updated_at: string
  last_activity: string
  file_count: number
  activity_status: 'active' | 'recent' | 'inactive'
}

interface VibeSessionManagerProps {
  currentSessionId: string | null
  onSessionSelect: (session: Session) => void
  onSessionCreate: (projectName: string, description?: string) => Promise<Session>
  onSessionDelete?: (sessionId: string) => Promise<void>
  userId: number
  className?: string
}

export default function VibeSessionManager({
  currentSessionId,
  onSessionSelect,
  onSessionCreate,
  onSessionDelete,
  userId,
  className = ""
}: VibeSessionManagerProps) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)
  const [newProjectName, setNewProjectName] = useState("")
  const [newDescription, setNewDescription] = useState("")
  const [editProjectName, setEditProjectName] = useState("")
  const [editDescription, setEditDescription] = useState("")
  const [showCreateDialog, setShowCreateDialog] = useState(false)

  const loadSessions = async () => {
    try {
      setIsLoading(true)
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch(`/api/vibecoding/sessions/${userId}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })

      if (response.ok) {
        const data = await response.json()
        setSessions(data.sessions || [])
      } else {
        console.error('Failed to load sessions')
      }
    } catch (error) {
      console.error('Error loading sessions:', error)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    if (userId) {
      loadSessions()
    }
  }, [userId])

  const handleCreateSession = async () => {
    if (!newProjectName.trim() || isCreating) return

    try {
      setIsCreating(true)
      const session = await onSessionCreate(newProjectName, newDescription)
      
      // Refresh sessions list
      await loadSessions()
      
      setNewProjectName("")
      setNewDescription("")
      setShowCreateDialog(false)
      
      // Select the new session
      onSessionSelect(session)
    } catch (error) {
      console.error('Failed to create session:', error)
    } finally {
      setIsCreating(false)
    }
  }

  const handleDeleteSession = async (sessionId: string) => {
    if (!onSessionDelete) return
    
    try {
      await onSessionDelete(sessionId)
      await loadSessions()
      
      // If we deleted the current session, clear selection
      if (currentSessionId === sessionId) {
        // The parent component should handle clearing the current session
      }
    } catch (error) {
      console.error('Failed to delete session:', error)
    }
  }

  const startEditSession = (session: Session) => {
    setEditingSessionId(session.id)
    setEditProjectName(session.project_name)
    setEditDescription(session.description || "")
  }

  const saveEditSession = async (sessionId: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch(`/api/vibecoding/sessions/${sessionId}`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          project_name: editProjectName,
          description: editDescription
        })
      })

      if (response.ok) {
        await loadSessions()
        setEditingSessionId(null)
      }
    } catch (error) {
      console.error('Failed to update session:', error)
    }
  }

  const cancelEditSession = () => {
    setEditingSessionId(null)
    setEditProjectName("")
    setEditDescription("")
  }

  const getActivityColor = (status: string) => {
    switch (status) {
      case 'active': return 'border-green-500 text-green-400'
      case 'recent': return 'border-yellow-500 text-yellow-400'
      default: return 'border-gray-500 text-gray-400'
    }
  }

  const getContainerStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'border-green-500 text-green-400'
      case 'starting': return 'border-yellow-500 text-yellow-400'
      case 'stopping': return 'border-orange-500 text-orange-400'
      default: return 'border-red-500 text-red-400'
    }
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffTime = Math.abs(now.getTime() - date.getTime())
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
    
    if (diffDays === 1) return 'Today'
    if (diffDays === 2) return 'Yesterday'
    if (diffDays <= 7) return `${diffDays - 1} days ago`
    return date.toLocaleDateString()
  }

  if (isLoading) {
    return (
      <Card className={`bg-gray-900/50 backdrop-blur-sm border-purple-500/30 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-purple-400" />
          <span className="ml-2 text-gray-300">Loading sessions...</span>
        </div>
      </Card>
    )
  }

  return (
    <Card className={`bg-gray-900/50 backdrop-blur-sm border-purple-500/30 flex flex-col ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-purple-500/30 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <FolderOpen className="w-5 h-5 text-purple-400" />
            <h3 className="text-lg font-semibold text-purple-300">Sessions</h3>
            <Badge variant="outline" className="border-gray-500 text-gray-400">
              {sessions.length}
            </Badge>
          </div>
          
          <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
            <DialogTrigger asChild>
              <Button size="sm" className="bg-purple-600 hover:bg-purple-700 text-white">
                <Plus className="w-3 h-3 mr-1" />
                New
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-gray-900 border-purple-500/30 text-white">
              <DialogHeader>
                <DialogTitle className="text-purple-300">Create New Session</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 pt-4">
                <div>
                  <label className="text-sm font-medium text-gray-300 mb-2 block">
                    Project Name
                  </label>
                  <Input
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    placeholder="My Awesome Project"
                    className="bg-gray-800 border-gray-600 text-white"
                    onKeyPress={(e) => e.key === 'Enter' && handleCreateSession()}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-300 mb-2 block">
                    Description (Optional)
                  </label>
                  <Input
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    placeholder="Brief description of your project"
                    className="bg-gray-800 border-gray-600 text-white"
                    onKeyPress={(e) => e.key === 'Enter' && handleCreateSession()}
                  />
                </div>
                <div className="flex space-x-2 pt-4">
                  <Button
                    onClick={handleCreateSession}
                    disabled={!newProjectName.trim() || isCreating}
                    className="bg-purple-600 hover:bg-purple-700 text-white flex-1"
                  >
                    {isCreating ? (
                      <Loader2 className="w-4 h-4 animate-spin mr-2" />
                    ) : (
                      <Plus className="w-4 h-4 mr-2" />
                    )}
                    Create Session
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
        </div>
      </div>

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {sessions.length === 0 ? (
          <div className="text-center py-8">
            <FolderOpen className="w-12 h-12 text-gray-600 mx-auto mb-4" />
            <p className="text-gray-400 mb-4">No sessions yet</p>
            <Button
              onClick={() => setShowCreateDialog(true)}
              className="bg-purple-600 hover:bg-purple-700 text-white"
            >
              <Plus className="w-4 h-4 mr-2" />
              Create Your First Session
            </Button>
          </div>
        ) : (
          <AnimatePresence>
            {sessions.map((session) => (
              <motion.div
                key={session.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                onClick={() => editingSessionId !== session.id && onSessionSelect(session)}
                className={`p-4 rounded-lg border cursor-pointer transition-all hover:shadow-lg ${
                  currentSessionId === session.session_id
                    ? 'border-purple-500 bg-purple-500/20 shadow-purple-500/25'
                    : 'border-gray-600 bg-gray-800/50 hover:border-gray-500'
                }`}
              >
                {editingSessionId === session.id ? (
                  <div className="space-y-3" onClick={(e) => e.stopPropagation()}>
                    <Input
                      value={editProjectName}
                      onChange={(e) => setEditProjectName(e.target.value)}
                      className="bg-gray-700 border-gray-600 text-white font-medium"
                    />
                    <Input
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      placeholder="Description (optional)"
                      className="bg-gray-700 border-gray-600 text-white text-sm"
                    />
                    <div className="flex space-x-2">
                      <Button
                        onClick={() => saveEditSession(session.id)}
                        size="sm"
                        className="bg-green-600 hover:bg-green-700 text-white"
                      >
                        <Save className="w-3 h-3 mr-1" />
                        Save
                      </Button>
                      <Button
                        onClick={cancelEditSession}
                        size="sm"
                        variant="outline"
                        className="border-gray-600 text-gray-300"
                      >
                        <X className="w-3 h-3 mr-1" />
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <div className="flex items-start justify-between mb-2">
                      <h4 className="font-medium text-white truncate flex-1">
                        {session.project_name}
                      </h4>
                      <div className="flex items-center space-x-1 ml-2">
                        <Button
                          onClick={(e) => {
                            e.stopPropagation()
                            startEditSession(session)
                          }}
                          size="sm"
                          variant="ghost"
                          className="p-1 h-6 w-6 text-gray-400 hover:text-white"
                        >
                          <Edit3 className="w-3 h-3" />
                        </Button>
                        {onSessionDelete && (
                          <Button
                            onClick={(e) => {
                              e.stopPropagation()
                              handleDeleteSession(session.session_id)
                            }}
                            size="sm"
                            variant="ghost"
                            className="p-1 h-6 w-6 text-red-400 hover:text-red-300"
                          >
                            <Trash2 className="w-3 h-3" />
                          </Button>
                        )}
                      </div>
                    </div>

                    {session.description && (
                      <p className="text-sm text-gray-400 mb-3 truncate">
                        {session.description}
                      </p>
                    )}

                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-3">
                        <Badge 
                          variant="outline" 
                          className={`text-xs ${getActivityColor(session.activity_status)}`}
                        >
                          <Clock className="w-3 h-3 mr-1" />
                          {session.activity_status}
                        </Badge>
                        
                        <Badge 
                          variant="outline" 
                          className={`text-xs ${getContainerStatusColor(session.container_status)}`}
                        >
                          <Container className="w-3 h-3 mr-1" />
                          {session.container_status}
                        </Badge>
                        
                        <Badge variant="outline" className="text-xs border-blue-500 text-blue-400">
                          <FileText className="w-3 h-3 mr-1" />
                          {session.file_count} files
                        </Badge>
                      </div>
                      
                      <span className="text-xs text-gray-500">
                        {formatDate(session.last_activity)}
                      </span>
                    </div>
                  </div>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>

      {/* Refresh Button */}
      <div className="p-4 border-t border-purple-500/30 flex-shrink-0">
        <Button
          onClick={loadSessions}
          variant="outline"
          size="sm"
          className="w-full bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
        >
          <Settings className="w-3 h-3 mr-2" />
          Refresh Sessions
        </Button>
      </div>
    </Card>
  )
}