import type { ChangeEvent } from 'react'
import { useRef, useState } from 'react'

import { getHermesConfigDefaults, getHermesConfigRecord, saveHermesConfig } from '@/hermes'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import { confirm } from '@/store/confirm'
import { notify, notifyError } from '@/store/notifications'

import { invalidateHermesConfig } from '../hooks/use-config-record'

/** Settings-wide config import / export / reset-to-defaults. */
export function useConfigTransfer(onConfigSaved?: () => void) {
  const { t } = useI18n()
  const importInputRef = useRef<HTMLInputElement | null>(null)
  // Bumped after an import or reset so the open config page re-seeds its draft
  // from the saved record instead of autosaving its stale copy back over it.
  const [configEpoch, setConfigEpoch] = useState(0)

  const afterConfigReplaced = async () => {
    await invalidateHermesConfig()
    setConfigEpoch(epoch => epoch + 1)
    onConfigSaved?.()
  }

  const importConfig = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''

    if (!file) {
      return
    }

    void file
      .text()
      .then(async text => {
        const parsed: unknown = JSON.parse(text)
        // Accept both an exported record and a `{config: {...}}` wrapper.
        const record =
          parsed && typeof parsed === 'object' && !Array.isArray(parsed) && 'config' in parsed
            ? (parsed as { config: unknown }).config
            : parsed

        if (!record || typeof record !== 'object' || Array.isArray(record)) {
          throw new Error(t.settings.config.invalidJson)
        }

        const result = await saveHermesConfig(record as Parameters<typeof saveHermesConfig>[0])

        if (!result.ok) {
          throw new Error(t.settings.config.autosaveFailed)
        }

        await afterConfigReplaced()
        triggerHaptic('success')
        notify({ kind: 'success', title: t.settings.config.imported, message: file.name })
      })
      .catch(err => notifyError(err, t.settings.config.invalidJson))
  }

  const exportConfig = async () => {
    try {
      const cfg = await getHermesConfigRecord()
      const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'hermes-config.json'
      a.click()
      URL.revokeObjectURL(url)
      triggerHaptic('success')
    } catch (err) {
      notifyError(err, t.settings.exportFailed)
    }
  }

  const resetConfig = async () => {
    const ok = await confirm({
      confirmLabel: t.settings.resetToDefaults,
      destructive: true,
      title: t.settings.resetConfirm
    })

    if (!ok) {
      return
    }

    try {
      await saveHermesConfig(await getHermesConfigDefaults())
      await afterConfigReplaced()
      triggerHaptic('success')
    } catch (err) {
      notifyError(err, t.settings.resetFailed)
    }
  }

  return { configEpoch, exportConfig, importConfig, importInputRef, resetConfig }
}
