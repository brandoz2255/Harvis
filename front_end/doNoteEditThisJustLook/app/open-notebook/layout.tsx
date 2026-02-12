'use client'

import { OpenNotebookSidebar } from '@/components/notebook/OpenNotebookSidebar'
import { useOpenNotebookSidebarStore } from '@/stores/openNotebookUiStore'
import { cn } from '@/lib/utils'

export default function OpenNotebookLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { isCollapsed } = useOpenNotebookSidebarStore()

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <OpenNotebookSidebar />

      {/* Main Content */}
      <main
        className={cn(
          'flex-1 overflow-hidden transition-all duration-300',
          isCollapsed ? 'ml-0' : 'ml-0'
        )}
      >
        <div className="h-full overflow-auto">
          {children}
        </div>
      </main>
    </div>
  )
}
