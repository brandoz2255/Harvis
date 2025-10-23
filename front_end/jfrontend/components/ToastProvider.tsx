"use client"

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { X, CheckCircle, AlertCircle, Info, Loader2 } from 'lucide-react'

export interface Toast {
  id: string
  type: 'success' | 'error' | 'info' | 'loading'
  title: string
  description?: string
  duration?: number
}

interface ToastContextType {
  toast: {
    success: (title: string, description?: string, duration?: number) => string
    error: (title: string, description?: string, duration?: number) => string
    info: (title: string, description?: string, duration?: number) => string
    loading: (title: string, description?: string) => string
    update: (id: string, title: string, description?: string, type?: Toast['type']) => void
    dismiss: (id: string) => void
  }
}

const ToastContext = createContext<ToastContextType | null>(null)

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const addToast = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).substr(2, 9)
    const newToast = { ...toast, id }
    setToasts(prev => [...prev, newToast])
    return id
  }, [])

  const dismiss = useCallback((id: string) => {
    setToasts(prev => prev.filter(toast => toast.id !== id))
  }, [])

  const update = useCallback((id: string, title: string, description?: string, type?: Toast['type']) => {
    setToasts(prev => prev.map(toast => 
      toast.id === id 
        ? { ...toast, title, description, ...(type && { type }) }
        : toast
    ))
  }, [])

  const toast = {
    success: (title: string, description?: string, duration = 4000) => 
      addToast({ type: 'success', title, description, duration }),
    error: (title: string, description?: string, duration = 6000) => 
      addToast({ type: 'error', title, description, duration }),
    info: (title: string, description?: string, duration = 4000) => 
      addToast({ type: 'info', title, description, duration }),
    loading: (title: string, description?: string) => 
      addToast({ type: 'loading', title, description, duration: 0 }),
    update,
    dismiss
  }

  // Auto-dismiss toasts
  useEffect(() => {
    toasts.forEach(toast => {
      if (toast.duration && toast.duration > 0) {
        const timer = setTimeout(() => {
          dismiss(toast.id)
        }, toast.duration)
        return () => clearTimeout(timer)
      }
    })
  }, [toasts, dismiss])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

function ToastContainer({ toasts, onDismiss }: { toasts: Toast[], onDismiss: (id: string) => void }) {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  if (!mounted) return null

  return createPortal(
    <div className="fixed top-4 right-4 z-50 space-y-2 max-w-sm">
      <AnimatePresence>
        {toasts.map(toast => (
          <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />
        ))}
      </AnimatePresence>
    </div>,
    document.body
  )
}

function ToastItem({ toast, onDismiss }: { toast: Toast, onDismiss: (id: string) => void }) {
  const getIcon = () => {
    switch (toast.type) {
      case 'success':
        return <CheckCircle className="w-5 h-5 text-green-400" />
      case 'error':
        return <AlertCircle className="w-5 h-5 text-red-400" />
      case 'info':
        return <Info className="w-5 h-5 text-blue-400" />
      case 'loading':
        return <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />
      default:
        return <Info className="w-5 h-5 text-gray-400" />
    }
  }

  const getBackgroundColor = () => {
    switch (toast.type) {
      case 'success':
        return 'bg-green-900/20 border-green-500/30'
      case 'error':
        return 'bg-red-900/20 border-red-500/30'
      case 'info':
        return 'bg-blue-900/20 border-blue-500/30'
      case 'loading':
        return 'bg-gray-900/20 border-gray-500/30'
      default:
        return 'bg-gray-900/20 border-gray-500/30'
    }
  }

  const getTextColor = () => {
    switch (toast.type) {
      case 'success':
        return 'text-green-300'
      case 'error':
        return 'text-red-300'
      case 'info':
        return 'text-blue-300'
      case 'loading':
        return 'text-gray-300'
      default:
        return 'text-gray-300'
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 300, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 300, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      className={`${getBackgroundColor()} border rounded-lg p-4 shadow-lg backdrop-blur-sm`}
    >
      <div className="flex items-start gap-3">
        {getIcon()}
        <div className="flex-1 min-w-0">
          <h4 className={`text-sm font-medium ${getTextColor()}`}>
            {toast.title}
          </h4>
          {toast.description && (
            <p className={`text-xs mt-1 ${getTextColor()} opacity-80`}>
              {toast.description}
            </p>
          )}
        </div>
        <button
          onClick={() => onDismiss(toast.id)}
          className="text-gray-400 hover:text-gray-200 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </motion.div>
  )
}
