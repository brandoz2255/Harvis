import { afterEach, describe, expect, it, vi } from 'vitest'
import { $session } from '@/lib/harvis-session'
import { modsApi } from './api'
import { $islandVisible, $mods, refreshMods } from './store'
import type { ModRow } from './types'

const signIn = (id: string) => $session.set({ status: 'signed-in', user: { id, email: '', name: '', role: 'user' } })

afterEach(() => {
  $session.set({ status: 'signed-out', expired: false })
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('account island and mod isolation', () => {
  it('defaults on for an account that never chose, ignores legacy state, and restores each account setting', () => {
    localStorage.setItem('hermes.desktop.islandVisible', 'false')
    signIn('alice')
    expect($islandVisible.get()).toBe(true)
    $islandVisible.set(false)
    signIn('bob')
    expect($islandVisible.get()).toBe(true)
    $islandVisible.set(false)
    $islandVisible.set(true)
    signIn('alice')
    expect($islandVisible.get()).toBe(false)
    $session.set({ status: 'signed-out', expired: false })
    expect($islandVisible.get()).toBe(false)
    signIn('bob')
    expect($islandVisible.get()).toBe(true)
  })

  it('discards a previous account’s late mod response', async () => {
    let resolve!: (rows: ModRow[]) => void
    vi.spyOn(modsApi, 'list').mockImplementationOnce(() => new Promise(r => { resolve = r }))
      .mockResolvedValueOnce([])
    signIn('alice')
    const old = refreshMods()
    signIn('bob')
    await refreshMods()
    resolve([{ name: 'alice-mod' } as ModRow])
    await old
    expect($mods.get()).toEqual([])
  })
})
