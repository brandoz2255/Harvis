import { beforeEach, describe, expect, it } from 'vitest'

import {
  $serverCapabilities,
  hasCapability,
  resetServerCapabilities,
  setServerCapabilities
} from './server-capabilities'

describe('server capabilities', () => {
  beforeEach(() => resetServerCapabilities())

  it('reads every flag as off until a status answer arrives', () => {
    expect(hasCapability('git')).toBe(false)
    expect(hasCapability('logs')).toBe(false)
  })

  it('follows the flags the backend sends', () => {
    setServerCapabilities({ capabilities: { git: true, kanban: false, logs: false } })

    expect(hasCapability('git')).toBe(true)
    expect(hasCapability('kanban')).toBe(false)
    expect(hasCapability('logs')).toBe(false)
  })

  it('treats a flag the backend does not mention as off', () => {
    setServerCapabilities({ capabilities: { git: true } })

    expect(hasCapability('skills_hub')).toBe(false)
  })

  it('treats only a literal true as on', () => {
    setServerCapabilities({ capabilities: { git: 'yes', logs: 1, sandbox: true } })

    expect(hasCapability('git')).toBe(false)
    expect(hasCapability('logs')).toBe(false)
    expect(hasCapability('sandbox')).toBe(true)
  })

  it('assumes a backend with no flags (a stock Hermes gateway) can do everything', () => {
    setServerCapabilities({ version: '1' })

    expect($serverCapabilities.get().loaded).toBe(true)
    expect(hasCapability('git_remote')).toBe(true)
    expect(hasCapability('kanban')).toBe(true)
  })

  it('ignores malformed bodies', () => {
    setServerCapabilities(null)
    setServerCapabilities({ capabilities: ['git'] })

    expect(hasCapability('git')).toBe(true) // no usable flags: same as a stock gateway
  })
})
