// Mounted once in the shell. Keeps the mod list fresh, applies the looks of
// every on mod, and gives the bar and side-panel slots a place while at least
// one mod uses them (an unused slot adds nothing to the chrome).
import { useStore } from '@nanostores/react'
import { useEffect } from 'react'

import { allPaneIds } from '@/components/pane-shell/tree/model'
import { $layoutTree, removeTreePane } from '@/components/pane-shell/tree/store'
import { registry } from '@/contrib/registry'

import { applyLooks } from './looks'
import { ModSlot } from './mod-slot'
import { $mods, refreshMods, runnableUiMods } from './store'

const SIDE_PANE_ID = 'mod-side-panel'

const renderStatusLine = () => <ModSlot slot="status-line" />
const renderClock = () => <ModSlot slot="clock" />
const renderSidePanel = () => <ModSlot slot="side-panel" />

export function ModsRuntime() {
  const rows = useStore($mods)
  const hasStatusLine = runnableUiMods(rows, 'status-line').length > 0
  const hasClock = runnableUiMods(rows, 'clock').length > 0
  const hasSidePanel = runnableUiMods(rows, 'side-panel').length > 0

  useEffect(() => {
    void refreshMods()
  }, [])

  // Looks follow the list: a mod turning off (or changing bytes) drops its overrides.
  useEffect(() => {
    applyLooks(rows)
  }, [rows])

  useEffect(() => {
    if (!hasStatusLine) {
      return
    }

    return registry.register({ area: 'statusBar.left', id: 'mod.status-line', render: renderStatusLine })
  }, [hasStatusLine])

  useEffect(() => {
    if (!hasClock) {
      return
    }

    return registry.register({ area: 'statusBar.right', id: 'mod.clock', render: renderClock })
  }, [hasClock])

  useEffect(() => {
    if (!hasSidePanel) {
      return
    }

    const dispose = registry.register({
      area: 'panes',
      data: { collapsible: true, dock: { pane: 'workspace', pos: 'right' }, placement: 'right', width: '18rem' },
      id: SIDE_PANE_ID,
      render: renderSidePanel,
      title: 'mods'
    })

    return () => {
      dispose()

      // Unregistering leaves the pane in a saved layout tree; sweep it out.
      const tree = $layoutTree.get()

      if (tree && allPaneIds(tree).includes(SIDE_PANE_ID)) {
        removeTreePane(SIDE_PANE_ID)
      }
    }
  }, [hasSidePanel])

  useEffect(() => () => applyLooks([]), [])

  return null
}
