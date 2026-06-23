'use client'

import { useMemo, useState } from 'react'

import { AppShell } from '@/components/layout/AppShell'
import { NotebookList } from './components/NotebookList'
import { Button } from '@/components/ui/button'
import { Plus, RefreshCw } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useNotebooks, useCreateNotebook } from '@/lib/hooks/use-notebooks'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/hooks/use-translation'

export default function NotebooksPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const createNotebook = useCreateNotebook()
  const [searchTerm, setSearchTerm] = useState('')
  const { data: notebooks, isLoading, refetch } = useNotebooks(false)

  // "+ New Notebook" creates instantly (no name prompt) and opens the empty notebook;
  // the AI generates a title + emoji once its first source is added.
  const handleNewNotebook = async () => {
    try {
      const nb = await createNotebook.mutateAsync({ name: '', description: '' })
      router.push(`/notebooks/${encodeURIComponent(nb.id)}`)
    } catch {
      // error toast handled by the mutation
    }
  }
  const { data: archivedNotebooks } = useNotebooks(true)

  const normalizedQuery = searchTerm.trim().toLowerCase()

  const filteredActive = useMemo(() => {
    if (!notebooks) {
      return undefined
    }
    if (!normalizedQuery) {
      return notebooks
    }
    return notebooks.filter((notebook) =>
      notebook.name.toLowerCase().includes(normalizedQuery)
    )
  }, [notebooks, normalizedQuery])

  const filteredArchived = useMemo(() => {
    if (!archivedNotebooks) {
      return undefined
    }
    if (!normalizedQuery) {
      return archivedNotebooks
    }
    return archivedNotebooks.filter((notebook) =>
      notebook.name.toLowerCase().includes(normalizedQuery)
    )
  }, [archivedNotebooks, normalizedQuery])

  const hasArchived = (archivedNotebooks?.length ?? 0) > 0
  const isSearching = normalizedQuery.length > 0

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold">{t('notebooks.title')}</h1>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
            <Input
              id="notebook-search"
              name="notebook-search"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder={t('notebooks.searchPlaceholder')}
              autoComplete="off"
              aria-label={t('common.accessibility.searchNotebooks') || "Search notebooks"}
              className="w-full sm:w-64"
            />
            <Button onClick={handleNewNotebook} disabled={createNotebook.isPending}>
              <Plus className="h-4 w-4 mr-2" />
              {t('notebooks.newNotebook')}
            </Button>
          </div>
        </div>
        
        <div className="space-y-8">
          <NotebookList 
            notebooks={filteredActive} 
            isLoading={isLoading}
            title={t('notebooks.activeNotebooks')}
            emptyTitle={isSearching ? t('common.noMatches') : undefined}
            emptyDescription={isSearching ? t('common.tryDifferentSearch') : undefined}
            onAction={!isSearching ? handleNewNotebook : undefined}
            actionLabel={!isSearching ? t('notebooks.newNotebook') : undefined}
          />
          
          {hasArchived && (
            <NotebookList 
              notebooks={filteredArchived} 
              isLoading={false}
              title={t('notebooks.archivedNotebooks')}
              collapsible
              emptyTitle={isSearching ? t('common.noMatches') : undefined}
              emptyDescription={isSearching ? t('common.tryDifferentSearch') : undefined}
            />
          )}
        </div>
        </div>
      </div>
    </AppShell>
  )
}
