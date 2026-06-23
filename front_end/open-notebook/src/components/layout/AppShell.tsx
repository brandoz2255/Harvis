'use client'

import { SetupBanner } from './SetupBanner'

interface AppShellProps {
  children: React.ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Harvis: the open-notebook nav now lives in the Harvis (OWUI) left sidebar
          (NotebookNav), which drives this iframe via the `?onb=` query param. The
          app's own AppSidebar is intentionally NOT rendered here so the content runs
          full-width inside the Harvis shell. */}
      <main className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <SetupBanner />
        {children}
      </main>
    </div>
  )
}
