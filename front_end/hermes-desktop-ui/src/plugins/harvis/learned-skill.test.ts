import { beforeEach, describe, expect, it, vi } from 'vitest'

const { listeners, notify, notifyError, setSkillEnabled } = vi.hoisted(() => ({
  listeners: new Map<string, (event: unknown) => void>(),
  notify: vi.fn(),
  notifyError: vi.fn(),
  setSkillEnabled: vi.fn()
}))

vi.mock('@hermes/plugin-sdk', () => ({
  host: {
    notify,
    notifyError,
    onEvent: (type: string, fn: (event: unknown) => void) => {
      listeners.set(type, fn)

      return () => listeners.delete(type)
    }
  }
}))
vi.mock('@/api/skills', () => ({ setSkillEnabled }))

const { watchLearnedSkills } = await import('./learned-skill')

beforeEach(() => {
  listeners.clear()
  notify.mockReset()
  setSkillEnabled.mockReset()
})

describe('watchLearnedSkills', () => {
  it('offers to enable a skill Harvis just drafted, and enabling it switches it on', async () => {
    const stop = watchLearnedSkills()
    listeners.get('harvis.skill.drafted')?.({
      type: 'harvis.skill.drafted',
      payload: { name: 'docker-compose-debug', description: 'When compose will not start.' }
    })

    const toast = notify.mock.calls[0][0]
    expect(toast.title).toBe('Harvis learned a skill')
    expect(toast.message).toBe('docker-compose-debug — When compose will not start.')
    expect(toast.action.label).toBe('Enable')

    setSkillEnabled.mockResolvedValue({ ok: true, name: 'docker-compose-debug', enabled: true })
    toast.action.onClick()
    await vi.waitFor(() => expect(notify).toHaveBeenCalledTimes(2))
    expect(setSkillEnabled).toHaveBeenCalledWith('docker-compose-debug', true)
    expect(notify.mock.calls[1][0]).toMatchObject({ id: toast.id, kind: 'success' })

    stop()
    expect(listeners.has('harvis.skill.drafted')).toBe(false)
  })

  it('ignores an event without a skill name', () => {
    watchLearnedSkills()
    listeners.get('harvis.skill.drafted')?.({ type: 'harvis.skill.drafted', payload: {} })
    expect(notify).not.toHaveBeenCalled()
  })
})
