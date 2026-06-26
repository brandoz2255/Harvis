'use client'

import { createContext, useContext, useState, useCallback, ReactNode } from 'react'
import { AddSourceDialog } from '@/components/sources/AddSourceDialog'
import { CreateNotebookDialog } from '@/components/notebooks/CreateNotebookDialog'
import { GeneratePodcastDialog } from '@/components/podcasts/GeneratePodcastDialog'

interface CreateDialogsContextType {
  openSourceDialog: () => void
  openNotebookDialog: () => void
  /** Optionally pre-scope the podcast to a notebook (Studio rail passes the current one). */
  openPodcastDialog: (notebookId?: string) => void
}

const CreateDialogsContext = createContext<CreateDialogsContextType | null>(null)

export function CreateDialogsProvider({ children }: { children: ReactNode }) {
  const [sourceDialogOpen, setSourceDialogOpen] = useState(false)
  const [notebookDialogOpen, setNotebookDialogOpen] = useState(false)
  const [podcastDialogOpen, setPodcastDialogOpen] = useState(false)
  const [podcastNotebookId, setPodcastNotebookId] = useState<string | undefined>(undefined)

  const openSourceDialog = useCallback(() => setSourceDialogOpen(true), [])
  const openNotebookDialog = useCallback(() => setNotebookDialogOpen(true), [])
  const openPodcastDialog = useCallback((notebookId?: string) => {
    setPodcastNotebookId(notebookId)
    setPodcastDialogOpen(true)
  }, [])

  return (
    <CreateDialogsContext.Provider
      value={{
        openSourceDialog,
        openNotebookDialog,
        openPodcastDialog,
      }}
    >
      {children}
      <AddSourceDialog open={sourceDialogOpen} onOpenChange={setSourceDialogOpen} />
      <CreateNotebookDialog open={notebookDialogOpen} onOpenChange={setNotebookDialogOpen} />
      <GeneratePodcastDialog
        open={podcastDialogOpen}
        onOpenChange={setPodcastDialogOpen}
        defaultNotebookId={podcastNotebookId}
      />
    </CreateDialogsContext.Provider>
  )
}

export function useCreateDialogs() {
  const context = useContext(CreateDialogsContext)
  if (!context) {
    throw new Error('useCreateDialogs must be used within a CreateDialogsProvider')
  }
  return context
}
