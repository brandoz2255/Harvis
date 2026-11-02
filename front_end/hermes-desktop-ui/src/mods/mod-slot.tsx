// <ModSlot slot="..."> mounts every on + approved mod whose manifest declares
// that slot, each inside the sandbox from host.ts. Slots with no home in the
// shell yet (slash-command, pre-send) render nothing.
import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useRef } from 'react'

import { cn } from '@/lib/utils'

import { modHost } from './runtime'
import { $mods, runnableUiMods } from './store'
import type { ModRow, ModSlotName } from './types'

// Box each slot's frames live in. A slot missing here has no place in the shell.
const SLOT_BOX: Partial<Record<ModSlotName, string>> = {
  'chat-widget': 'h-24 w-full overflow-hidden',
  clock: 'h-5 w-16 overflow-hidden',
  island: 'pointer-events-auto fixed bottom-10 left-80 z-40 h-44 w-72 overflow-hidden rounded-lg border border-border',
  pet: 'pointer-events-auto fixed bottom-10 right-4 z-40 size-24 overflow-hidden',
  'side-panel': 'size-full overflow-hidden',
  'status-line': 'h-5 w-48 overflow-hidden'
}

export function useModsInSlot(slot: ModSlotName): ModRow[] {
  const rows = useStore($mods)

  return useMemo(() => runnableUiMods(rows, slot), [rows, slot])
}

function ModFrame({ className, row }: { className?: string; row: ModRow }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current

    if (!el) {
      return
    }

    void modHost.launch(row, el)

    return () => modHost.stop(row.name)
    // The hash is the identity: the same bytes stay mounted, new bytes remount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row.name, row.hash, row.approved_hash])

  return <div className={className} data-mod={row.name} ref={ref} />
}

export function ModSlot({ slot }: { slot: ModSlotName }) {
  const rows = useModsInSlot(slot)
  const box = SLOT_BOX[slot]

  if (!box || rows.length === 0) {
    return null
  }

  return (
    <>
      {rows.map(row => (
        <ModFrame className={cn(box)} key={`${row.name}:${row.hash}`} row={row} />
      ))}
    </>
  )
}
