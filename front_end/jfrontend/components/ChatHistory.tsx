"use client"

import { useEffect, useState, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  MessageSquare, 
  Plus, 
  Trash2, 
  Edit3, 
  Calendar, 
  Clock,
  User,
  Bot,
  History,
  X,
  Search,
  Filter
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useChatHistoryStore, ChatSession, ChatMessage } from '@/stores/chatHistoryStore'

interface ChatHistoryProps {
  onSessionSelect?: (sessionId: string) => void
  currentSessionId?: string
}

export default function ChatHistory({ onSessionSelect, currentSessionId }: ChatHistoryProps) {
  const {
    sessions,
    currentSession,
    messages,
    isLoadingSessions,
    isLoadingMessages,
    isHistoryVisible,
    error,
    fetchSessions,
    createNewChat,
    selectSession,
    deleteSession,
    updateSessionTitle,
    toggleHistoryVisibility,
  } = useChatHistoryStore()

  const [searchTerm, setSearchTerm] = useState('')
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [selectedView, setSelectedView] = useState<'sessions' | 'messages'>('sessions')

  // Debounced fetch sessions to prevent spam
  const fetchSessionsRef = useRef(fetchSessions)
  fetchSessionsRef.current = fetchSessions
  
  const debouncedFetchSessions = (() => {
    let timeoutId: NodeJS.Timeout
    return () => {
      clearTimeout(timeoutId)
      timeoutId = setTimeout(() => {
        fetchSessionsRef.current()
      }, 500) // 500ms debounce
    }
  })()
  
  // Fetch sessions on mount only to prevent infinite loops
  useEffect(() => {
    debouncedFetchSessions()
  }, [debouncedFetchSessions])

  // Stabilized selectSession to prevent recreation
  const selectSessionRef = useRef(selectSession)
  selectSessionRef.current = selectSession
  
  const stableSelectSession = useCallback(
    (sessionId: string) => selectSessionRef.current(sessionId),
    []
  )
  
  // Handle external session selection with proper cleanup and debouncing
  useEffect(() => {
    if (currentSessionId && currentSessionId !== currentSession?.id) {
      const controller = new AbortController()
      let timeoutId: NodeJS.Timeout
      
      const handleSelection = async () => {
        try {
          if (!controller.signal.aborted) {
            await stableSelectSession(currentSessionId)
          }
        } catch (error) {
          if (!controller.signal.aborted) {
            console.error('Error selecting session:', error)
          }
        }
      }
      
      // Debounce session selection to prevent rapid switches
      timeoutId = setTimeout(handleSelection, 300)
      
      return () => {
        controller.abort()
        clearTimeout(timeoutId)
      }
    }
  }, [currentSessionId, currentSession?.id, stableSelectSession])

  const filteredSessions = sessions.filter(session =>
    session.title.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const handleCreateNewChat = async () => {
    try {
      const session = await createNewChat()
      if (session && onSessionSelect) {
        onSessionSelect(session.id)
      }
    } catch (error) {
      console.error('Failed to create new chat:', error)
      // Error is already handled by the store
    }
  }

  const handleSessionClick = async (session: ChatSession) => {
    try {
      await selectSession(session.id)
      if (onSessionSelect) {
        onSessionSelect(session.id)
      }
      setSelectedView('messages')
    } catch (error) {
      console.error('Failed to select session:', error)
      // Error is already handled by the store
    }
  }

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    
    const session = sessions.find(s => s.id === sessionId)
    const sessionTitle = session?.title || 'this chat session'
    const messageCount = session?.message_count || 0
    
    const confirmMessage = messageCount > 0
      ? `Are you sure you want to delete "${sessionTitle}"? This will permanently delete ${messageCount} message${messageCount === 1 ? '' : 's'}.`
      : `Are you sure you want to delete "${sessionTitle}"?`
    
    if (window.confirm(confirmMessage)) {
      try {
        await deleteSession(sessionId)
        console.log(`🗑️ Deleted session: ${sessionTitle}`)
      } catch (error) {
        console.error('Failed to delete session:', error)
        alert('Failed to delete chat session. Please try again.')
      }
    }
  }

  const handleEditTitle = (session: ChatSession, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingSessionId(session.id)
    setEditTitle(session.title)
  }

  const handleSaveTitle = async () => {
    if (editingSessionId && editTitle.trim()) {
      await updateSessionTitle(editingSessionId, editTitle.trim())
      setEditingSessionId(null)
      setEditTitle('')
    }
  }

  const handleCancelEdit = () => {
    setEditingSessionId(null)
    setEditTitle('')
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
    
    if (diffDays === 0) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } else if (diffDays === 1) {
      return 'Yesterday'
    } else if (diffDays < 7) {
      return `${diffDays} days ago`
    } else {
      return date.toLocaleDateString()
    }
  }

  const getMessageIcon = (message: ChatMessage) => {
    switch (message.role) {
      case 'user':
        return <User className="w-3 h-3" />
      case 'assistant':
        return <Bot className="w-3 h-3" />
      default:
        return <MessageSquare className="w-3 h-3" />
    }
  }

  if (!isHistoryVisible) {
    return (
      <Button
        onClick={toggleHistoryVisibility}
        variant="outline"
        size="sm"
        className="fixed top-4 left-4 z-50 bg-gray-900/90 border-blue-500/30 text-blue-300 hover:bg-gray-800"
      >
        <History className="w-4 h-4 mr-2" />
        Chat History
      </Button>
    )
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ x: -400, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: -400, opacity: 0 }}
        transition={{ duration: 0.3 }}
        className="fixed left-0 top-0 h-full w-96 bg-gray-900/95 backdrop-blur-sm border-r border-blue-500/30 z-40 flex flex-col"
      >
        {/* Header */}
        <div className="p-4 border-b border-blue-500/30">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-blue-300 flex items-center">
              <History className="w-5 h-5 mr-2" />
              Chat History
            </h2>
            <Button
              onClick={toggleHistoryVisibility}
              variant="ghost"
              size="sm"
              className="text-gray-400 hover:text-white"
            >
              <X className="w-4 h-4" />
            </Button>
          </div>

          {/* View Toggle */}
          <div className="flex space-x-1 mb-4">
            <Button
              onClick={() => setSelectedView('sessions')}
              variant={selectedView === 'sessions' ? 'default' : 'outline'}
              size="sm"
              className="flex-1"
            >
              Sessions
            </Button>
            <Button
              onClick={() => setSelectedView('messages')}
              variant={selectedView === 'messages' ? 'default' : 'outline'}
              size="sm"
              className="flex-1"
              disabled={!currentSession}
            >
              Messages
            </Button>
          </div>

          {selectedView === 'sessions' && (
            <>
              {/* Search */}
              <div className="relative mb-4">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
                <Input
                  placeholder="Search conversations..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-10 bg-gray-800 border-gray-600 text-white placeholder-gray-400"
                />
              </div>

              {/* New Chat Button */}
              <Button
                onClick={handleCreateNewChat}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white"
                disabled={isLoadingSessions}
              >
                <Plus className="w-4 h-4 mr-2" />
                {isLoadingSessions ? 'Creating...' : 'New Chat'}
              </Button>
            </>
          )}

          {selectedView === 'messages' && currentSession && (
            <div className="space-y-2">
              <h3 className="font-medium text-white truncate">{currentSession.title}</h3>
              <div className="flex items-center space-x-4 text-xs text-gray-400">
                <span className="flex items-center">
                  <Calendar className="w-3 h-3 mr-1" />
                  {formatDate(currentSession.created_at)}
                </span>
                <span className="flex items-center">
                  <MessageSquare className="w-3 h-3 mr-1" />
                  {currentSession.message_count} messages
                </span>
              </div>
              <Button
                onClick={() => setSelectedView('sessions')}
                variant="outline"
                size="sm"
                className="w-full"
              >
                Back to Sessions
              </Button>
            </div>
          )}
        </div>

        {/* Error Display */}
        {error && (
          <div className="px-4 pb-2">
            <div className="p-2 bg-red-900/20 border border-red-500/30 rounded text-red-400 text-sm">
              {error}
            </div>
          </div>
        )}
        
        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {selectedView === 'sessions' && (
            <div className="space-y-2">
              {isLoadingSessions ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                </div>
              ) : filteredSessions.length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  {searchTerm ? 'No conversations found' : 'No chat history yet'}
                </div>
              ) : (
                <AnimatePresence>
                  {filteredSessions.map((session) => (
                    <motion.div
                      key={session.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                      className={`relative group cursor-pointer transition-all duration-200 ${
                        currentSession?.id === session.id 
                          ? 'ring-2 ring-blue-500 bg-blue-900/30 shadow-lg transform scale-[1.02]' 
                          : 'hover:bg-gray-800/30'
                      }`}
                      onClick={() => handleSessionClick(session)}
                    >
                      <Card className={`p-3 transition-all duration-200 ${
                        currentSession?.id === session.id
                          ? 'bg-blue-900/20 border border-blue-500/40'
                          : 'bg-gray-800/50 hover:bg-gray-800/70 border border-gray-700/50'
                      }`}>
                        <div className="flex items-start justify-between">
                          <div className="flex-1 min-w-0 mr-2">
                            {editingSessionId === session.id ? (
                              <div className="space-y-2">
                                <Input
                                  value={editTitle}
                                  onChange={(e) => setEditTitle(e.target.value)}
                                  className="text-sm bg-gray-700 border-gray-600"
                                  autoFocus
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') handleSaveTitle()
                                    if (e.key === 'Escape') handleCancelEdit()
                                  }}
                                />
                                <div className="flex space-x-1">
                                  <Button onClick={handleSaveTitle} size="sm" className="text-xs">
                                    Save
                                  </Button>
                                  <Button onClick={handleCancelEdit} size="sm" variant="outline" className="text-xs">
                                    Cancel
                                  </Button>
                                </div>
                              </div>
                            ) : (
                              <>
                                <h3 className="text-sm font-medium text-white truncate mb-1">
                                  {session.title}
                                </h3>
                                <div className="flex items-center space-x-3 text-xs text-gray-400">
                                  <span className="flex items-center">
                                    <Clock className="w-3 h-3 mr-1" />
                                    {formatDate(session.last_message_at)}
                                  </span>
                                  <span>{session.message_count} msgs</span>
                                  {session.model_used && (
                                    <Badge variant="outline" className="text-xs border-green-500 text-green-400">
                                      {session.model_used}
                                    </Badge>
                                  )}
                                  {currentSession?.id === session.id && isLoadingMessages && (
                                    <div className="flex items-center space-x-1">
                                      <div className="animate-spin rounded-full h-3 w-3 border border-blue-500 border-t-transparent"></div>
                                      <span className="text-xs text-blue-400">Loading...</span>
                                    </div>
                                  )}
                                </div>
                              </>
                            )}
                          </div>
                          
                          {editingSessionId !== session.id && (
                            <div className="flex space-x-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <Button
                                onClick={(e) => handleEditTitle(session, e)}
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0 text-gray-400 hover:text-white"
                              >
                                <Edit3 className="w-3 h-3" />
                              </Button>
                              <Button
                                onClick={(e) => handleDeleteSession(session.id, e)}
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0 text-gray-400 hover:text-red-400"
                              >
                                <Trash2 className="w-3 h-3" />
                              </Button>
                            </div>
                          )}
                        </div>
                      </Card>
                    </motion.div>
                  ))}
                </AnimatePresence>
              )}
            </div>
          )}

          {selectedView === 'messages' && (
            <div className="space-y-3">
              {isLoadingMessages ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                </div>
              ) : messages.length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  No messages in this conversation
                </div>
              ) : (
                <AnimatePresence>
                  {messages.map((message, index) => (
                    <motion.div
                      key={message.id || index}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                      className={`p-3 rounded-lg ${
                        message.role === 'user' 
                          ? 'bg-blue-600/20 border-l-2 border-blue-500'
                          : 'bg-gray-700/50 border-l-2 border-green-500'
                      }`}
                    >
                      <div className="flex items-center space-x-2 mb-2">
                        {getMessageIcon(message)}
                        <span className="text-xs font-medium text-gray-300 capitalize">
                          {message.role}
                        </span>
                        {message.model_used && (
                          <Badge variant="outline" className="text-xs border-purple-500 text-purple-400">
                            {message.model_used}
                          </Badge>
                        )}
                        {message.created_at && (
                          <span className="text-xs text-gray-500">
                            {formatDate(message.created_at)}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-200 leading-relaxed">
                        {message.content}
                      </p>
                      {message.reasoning && (
                        <details className="mt-2">
                          <summary className="text-xs text-purple-400 cursor-pointer hover:text-purple-300">
                            View reasoning process
                          </summary>
                          <div className="mt-2 p-2 bg-purple-900/20 rounded text-xs text-purple-200 font-mono">
                            {message.reasoning}
                          </div>
                        </details>
                      )}
                    </motion.div>
                  ))}
                </AnimatePresence>
              )}
            </div>
          )}
        </div>
      </motion.div>
    </AnimatePresence>
  )
}