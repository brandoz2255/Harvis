import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { createPluginContext } from '@/contrib/plugin'
import { registry } from '@/contrib/registry'
import { ROUTES_AREA } from '@/app/routes'
import { resetServerCapabilities, setServerCapabilities } from '@/store/server-capabilities'

import plugin from './plugin'

const pages = () => registry.getArea(ROUTES_AREA).filter(c => c.source === 'plugin:kanban')

describe('kanban plugin', () => {
  let disposers: (() => void)[]

  beforeEach(() => {
    disposers = []
    resetServerCapabilities()
  })

  afterEach(() => {
    disposers.forEach(d => d())
  })

  const load = () => plugin.register(createPluginContext('kanban', d => disposers.push(d)))

  it('registers nothing until the server says it has a board', () => {
    load()
    expect(pages()).toHaveLength(0)

    setServerCapabilities({ capabilities: { kanban: false } })
    expect(pages()).toHaveLength(0)
  })

  it('shows the page when the capability turns on and hides it when it turns off', () => {
    load()
    setServerCapabilities({ capabilities: { kanban: true } })
    expect(pages()).toHaveLength(1)

    setServerCapabilities({ capabilities: { kanban: false } })
    expect(pages()).toHaveLength(0)
  })
})
