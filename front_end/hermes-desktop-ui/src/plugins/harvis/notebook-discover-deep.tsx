/** Deep research inside Discover: start the job, watch its progress, add the report, then pick its cited pages. */

import { Button, Codicon, Input, useQuery } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'

import { blockedReason, useCapabilities } from './notebook-capabilities'
import { cancelDeep, deepStatus, type DeepImport, importDeep, startDeep } from './notebook-discover-api'
import { PagePicker } from './notebook-page-picker'
import { errorText, useChosenModel } from './notebook-shared'

const RUN_KEY = (notebookId: string) => `harvis.notebooks.deep.${notebookId}`

function readRun(notebookId: string) {
  try {
    return window.localStorage.getItem(RUN_KEY(notebookId)) ?? ''
  } catch {
    return ''
  }
}

function writeRun(notebookId: string, id: string) {
  try {
    if (id) {
      window.localStorage.setItem(RUN_KEY(notebookId), id)
    } else {
      window.localStorage.removeItem(RUN_KEY(notebookId))
    }
  } catch {
    // storage blocked: the run still works, it just isn't remembered across tabs
  }
}

export function DeepResearch({ notebookId, onAdded }: { notebookId: string; onAdded: () => void }) {
  const { chosen } = useChosenModel()
  const caps = useCapabilities()
  const blocked = blockedReason(caps?.deep_research) || blockedReason(caps?.web_search)
  const [query, setQuery] = useState('')
  const [sessionId, setSessionId] = useState(() => readRun(notebookId))
  const [starting, setStarting] = useState(false)
  const [imported, setImported] = useState<DeepImport | null>(null)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => writeRun(notebookId, sessionId), [notebookId, sessionId])

  const status = useQuery({
    enabled: !!sessionId,
    queryFn: () => deepStatus(notebookId, sessionId),
    queryKey: ['harvis', 'notebooks', notebookId, 'deep', sessionId],
    refetchInterval: q => (q.state.data && q.state.data.status !== 'running' ? false : 3000),
    retry: false
  })

  const run = status.data
  const gone = !!sessionId && !!status.error && !run

  useEffect(() => {
    if (gone) {
      // The run is no longer on the server (restart or finished long ago): forget it.
      setSessionId('')
    }
  }, [gone])

  const start = async () => {
    setStarting(true)
    setError('')
    setImported(null)

    try {
      const { session_id } = await startDeep(notebookId, query.trim(), chosen)
      setSessionId(session_id)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setStarting(false)
    }
  }

  const addReport = async () => {
    setImporting(true)
    setError('')

    try {
      setImported(await importDeep(notebookId, sessionId))
      onAdded()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setImporting(false)
    }
  }

  const finish = () => {
    setSessionId('')
    setImported(null)
    setQuery('')
  }

  const running = run?.status === 'running'

  return (
    <div className="space-y-2">
      {!sessionId && (
        <form
          className="flex gap-1.5"
          onSubmit={event => {
            event.preventDefault()
            void start()
          }}
        >
          <Input
            aria-label="Research question"
            className="min-w-0 flex-1"
            disabled={!!blocked}
            onChange={e => setQuery(e.target.value)}
            placeholder="A question worth a few minutes of reading"
            value={query}
          />
          <Button disabled={query.trim().length < 3 || starting || !!blocked} size="sm" type="submit">
            {starting ? 'Starting…' : 'Start'}
          </Button>
        </form>
      )}
      {blocked && <p className="text-xs text-destructive">{blocked}</p>}
      {sessionId && !run && !gone && <p className="text-xs text-(--ui-text-tertiary)">Checking the research…</p>}
      {run && (
        <div className="space-y-1.5 rounded-lg border p-3">
          <p className="truncate text-sm font-medium">{run.query}</p>
          {running && (
            <>
              <p className="text-xs text-(--ui-text-tertiary)">
                <Codicon name="loading" size="0.8rem" spinning /> {run.message || run.phase || 'Working…'}
              </p>
              <Button onClick={() => void cancelDeep(notebookId, sessionId)} size="xs" variant="outline">
                Cancel
              </Button>
            </>
          )}
          {run.status === 'error' && (
            <>
              <p className="text-xs text-destructive">{run.error || 'The research did not finish.'}</p>
              <Button onClick={finish} size="xs" variant="outline">
                Try again
              </Button>
            </>
          )}
          {run.status === 'cancelled' && (
            <>
              <p className="text-xs text-(--ui-text-tertiary)">Cancelled.</p>
              <Button onClick={finish} size="xs" variant="outline">
                Start over
              </Button>
            </>
          )}
          {run.status === 'done' && !imported && (
            <>
              <p className="text-xs text-(--ui-text-tertiary)">The report is ready.</p>
              <Button disabled={importing} onClick={() => void addReport()} size="sm">
                {importing ? 'Adding…' : 'Add report as a source'}
              </Button>
            </>
          )}
          {imported && (
            <>
              <p className="text-xs text-(--ui-text-tertiary)">
                {imported.already_added ? 'The report is already in this notebook' : 'Added the report'}:{' '}
                {imported.source.title}.
              </p>
              {imported.cited.length > 0 ? (
                <>
                  <p className="text-xs font-medium">Pages it cited</p>
                  <PagePicker
                    addLabel="Add cited pages"
                    notebookId={notebookId}
                    onAdded={onAdded}
                    pages={imported.cited.map(c => ({ ...c, snippet: '' }))}
                  />
                </>
              ) : (
                <p className="text-xs text-(--ui-text-tertiary)">It listed no pages to import.</p>
              )}
              <Button onClick={finish} size="xs" variant="ghost">
                Done
              </Button>
            </>
          )}
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
