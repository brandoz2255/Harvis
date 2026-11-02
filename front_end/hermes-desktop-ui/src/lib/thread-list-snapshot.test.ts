import { describe, expect, it } from 'vitest'
import { createIncrementalAssistantRuntime, IncrementalExternalStoreRuntimeCore } from './incremental-external-store-runtime'

describe('thread list snapshots', () => {
  it('returns a stable snapshot even before subscription and updates when the list changes', () => {
    const core = new IncrementalExternalStoreRuntimeCore({ messages: [], onNew: async () => {} })
    const runtime = createIncrementalAssistantRuntime(core)
    const first = runtime.threads.getState()
    expect(runtime.threads.getState()).toBe(first)
    core.setAdapter({ messages: [], onNew: async () => {}, adapters: { threadList: { threads: [{ id: 'other', status: 'regular' }] } } })
    expect(runtime.threads.getState()).not.toBe(first)
    expect(runtime.threads.getState().threadIds).toContain('other')
    expect(runtime.threads.getState()).toBe(runtime.threads.getState())
  })
})
