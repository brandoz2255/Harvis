"use client"

import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Plus, Circle } from "lucide-react"
import { Button } from "@/components/ui/button"

interface Session {
  id: string
  session_id: string
  name: string
  description?: string
  container_status: 'running' | 'stopped' | 'starting' | 'stopping'
  created_at: string
  updated_at: string
  last_activity: string
  file_count: number
  activity_status: 'active' | 'recent' | 'inactive'
}

interface SessionTabsProps {
  sessions: Session[]
  activeSessionId: string | null
  onSessionSelect: (session: Session) => void
  onSessionClose: (sessionId: string) => void
  onNewSession: () => void
  className?: string
}

export default function SessionTabs({
  sessions,
  activeSessionId,
  onSessionSelect,
  onSessionClose,
  onNewSession,
  className = ""
}: SessionTabsProps) {
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running':
        return 'text-green-400'
      case 'starting':
        return 'text-yellow-400'
      case 'stopping':
        return 'text-orange-400'
      case 'stopped':
        return 'text-red-400'
      default:
        return 'text-gray-400'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'running':
        return '●'
      case 'starting':
        return '◐'
      case 'stopping':
        return '◑'
      case 'stopped':
        return '○'
      default:
        return '○'
    }
  }

  return (
    <div className={`flex items-center gap-1 ${className}`}>
      {/* Session Tabs */}
      <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide">
        <AnimatePresence>
          {sessions.map((session) => (
            <motion.div
              key={session.session_id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              className="flex items-center"
            >
              <Button
                onClick={() => onSessionSelect(session)}
                variant="ghost"
                className={`
                  flex items-center gap-2 px-3 py-2 rounded-none border-b-2 transition-all
                  ${activeSessionId === session.session_id
                    ? 'border-blue-500 bg-blue-500/10 text-white'
                    : 'border-transparent text-gray-400 hover:text-white hover:bg-gray-700'
                  }
                `}
              >
                <span className={`text-xs ${getStatusColor(session.container_status)}`}>
                  {getStatusIcon(session.container_status)}
                </span>
                <span className="text-sm font-medium truncate max-w-32">
                  {session.name}
                </span>
                <Button
                  onClick={(e) => {
                    e.stopPropagation()
                    onSessionClose(session.session_id)
                  }}
                  variant="ghost"
                  size="sm"
                  className="p-0 w-4 h-4 hover:bg-gray-600 rounded"
                >
                  <X className="w-3 h-3" />
                </Button>
              </Button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* New Session Button */}
      <Button
        onClick={onNewSession}
        variant="ghost"
        size="sm"
        className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded"
        title="New Session"
      >
        <Plus className="w-4 h-4" />
      </Button>
    </div>
  )
}
