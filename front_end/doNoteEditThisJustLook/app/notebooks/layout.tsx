'use client'

import { useEffect, useState } from 'react'
import { useNotebookStore } from '@/stores/notebookStore'
import { useUser } from '@/lib/auth/UserProvider'
import NotebookTopNav from '@/components/notebook/NotebookTopNav'

interface NotebooksLayoutProps {
  children: React.ReactNode
}

export default function NotebooksLayout({ children }: NotebooksLayoutProps) {
  const { user, isLoading: authLoading } = useUser()
  const { fetchNotebooks } = useNotebookStore()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // Fetch notebooks when user is authenticated
  useEffect(() => {
    if (!authLoading && user) {
      fetchNotebooks()
    }
  }, [authLoading, user, fetchNotebooks])

  // Listen to sidebar collapse events from main HARVIS sidebar
  useEffect(() => {
    const handleSidebarCollapse = (e: CustomEvent<{ collapsed: boolean }>) => {
      setSidebarCollapsed(e.detail.collapsed)
    }

    window.addEventListener('sidebar-collapse', handleSidebarCollapse as EventListener)
    return () => {
      window.removeEventListener('sidebar-collapse', handleSidebarCollapse as EventListener)
    }
  }, [])

  // Calculate the width based on sidebar state
  // Root layout adds: pt-16 (64px top padding), container mx-auto px-4 py-8
  // We need to counteract these
  // z-index 10 ensures we're above the main content but below modals (z-50) and sidebar (z-40)
  return (
    <div
      className="fixed top-16 right-0 bottom-0 bg-[#0a0a0a] overflow-hidden transition-all duration-300 z-10"
      style={{
        left: sidebarCollapsed ? '4rem' : '16rem'
      }}
    >
      <div className="flex h-full flex-col">
        <NotebookTopNav />
        <div className="flex-1 min-h-0 overflow-hidden">{children}</div>
      </div>
    </div>
  )
}
