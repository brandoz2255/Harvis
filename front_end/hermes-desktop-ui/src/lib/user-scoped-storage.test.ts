import { beforeEach, describe, expect, it } from 'vitest'

import { claimUserScopedStorage, clearUserScopedStorage } from './user-scoped-storage'

const OWNER = 'harvis.storageOwner'

describe('claimUserScopedStorage', () => {
  beforeEach(() => window.localStorage.clear())

  it('keeps the cache for the same user', () => {
    window.localStorage.setItem(OWNER, 'u1')
    window.localStorage.setItem('hermes.desktop.lastRoute', '/chat/abc')

    expect(claimUserScopedStorage('u1')).toBe('same')
    expect(window.localStorage.getItem('hermes.desktop.lastRoute')).toBe('/chat/abc')
  })

  it('adopts a cache of unknown owner instead of dropping drafts on upgrade', () => {
    window.localStorage.setItem('hermes.desktop.lastRoute', '/chat/abc')

    expect(claimUserScopedStorage('u1')).toBe('same')
    expect(window.localStorage.getItem('hermes.desktop.lastRoute')).toBe('/chat/abc')
    expect(window.localStorage.getItem(OWNER)).toBe('u1')
  })

  it('wipes the previous account cache when a different user signs in', () => {
    window.localStorage.setItem(OWNER, 'u1')
    window.localStorage.setItem('hermes.desktop.lastRoute', '/chat/abc')
    window.localStorage.setItem('hermes:composer-drafts:v3', '{"x":"secret draft"}')
    window.localStorage.setItem('hermes.transcript-tail.v2:sess-1', '[]')
    window.localStorage.setItem('harvis-artifact-data:v1:deadbeef:notes', 'u1 data')
    window.localStorage.setItem('hermes.theme', 'dark')

    expect(claimUserScopedStorage('u2')).toBe('switched')

    expect(window.localStorage.getItem('hermes.desktop.lastRoute')).toBeNull()
    expect(window.localStorage.getItem('hermes:composer-drafts:v3')).toBeNull()
    expect(window.localStorage.getItem('hermes.transcript-tail.v2:sess-1')).toBeNull()
    expect(window.localStorage.getItem('harvis-artifact-data:v1:deadbeef:notes')).toBeNull()
    expect(window.localStorage.getItem('hermes.theme')).toBe('dark')
    expect(window.localStorage.getItem(OWNER)).toBe('u2')
    expect(claimUserScopedStorage('u2')).toBe('same')
  })

  it('forgets the owner on sign-out so the next account is not treated as a switch', () => {
    window.localStorage.setItem(OWNER, 'u1')
    clearUserScopedStorage()

    expect(window.localStorage.getItem(OWNER)).toBeNull()
  })
})
