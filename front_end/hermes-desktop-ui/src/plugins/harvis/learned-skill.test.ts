import { beforeEach, describe, expect, it, vi } from 'vitest'

const { listeners, notify, notifyError, openSkillReview } = vi.hoisted(() => ({
  listeners: new Map<string, (event: unknown) => void>(),
  notify: vi.fn(),
  notifyError: vi.fn(),
  openSkillReview: vi.fn()
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
vi.mock('./skill-review', () => ({ openSkillReview }))

const { watchLearnedSkills } = await import('./learned-skill')

beforeEach(() => {
  listeners.clear()
  notify.mockReset()
  openSkillReview.mockReset()
})

describe('watchLearnedSkills', () => {
  it('offers Review, not Enable, for a skill Harvis just drafted, and Review opens the panel', () => {
    const stop = watchLearnedSkills()
    listeners.get('harvis.skill.drafted')?.({
      type: 'harvis.skill.drafted',
      payload: { name: 'docker-compose-debug', description: 'When compose will not start.' }
    })

    const toast = notify.mock.calls[0][0]
    expect(toast.title).toBe('Harvis learned a skill')
    expect(toast.message).toBe('docker-compose-debug — When compose will not start.')
    expect(toast.action.label).toBe('Review')
    expect(toast.action.label).not.toBe('Enable')

    // Nothing is approved by the toast itself; the button only opens the review panel.
    expect(openSkillReview).not.toHaveBeenCalled()
    toast.action.onClick()
    expect(openSkillReview).toHaveBeenCalledWith('docker-compose-debug')
    expect(notify).toHaveBeenCalledTimes(1)

    stop()
    expect(listeners.has('harvis.skill.drafted')).toBe(false)
  })

  it('says it is an update when the model proposed a revision', () => {
    watchLearnedSkills()
    listeners.get('harvis.skill.drafted')?.({
      type: 'harvis.skill.drafted',
      payload: { name: 'docker-compose-debug', kind: 'update' }
    })

    const toast = notify.mock.calls[0][0]
    expect(toast.title).toBe('Harvis proposed a skill update')
    expect(toast.action.label).toBe('Review')
  })

  it('ignores an event without a skill name', () => {
    watchLearnedSkills()
    listeners.get('harvis.skill.drafted')?.({ type: 'harvis.skill.drafted', payload: {} })
    expect(notify).not.toHaveBeenCalled()
  })
})
