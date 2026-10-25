import { beforeEach, describe, expect, it, vi } from 'vitest'

const { invalidateQueries, invalidateSlashCompletions, listeners, notify, notifyError, openSkillReview } = vi.hoisted(
  () => ({
    invalidateQueries: vi.fn(),
    invalidateSlashCompletions: vi.fn(),
    listeners: new Map<string, (event: unknown) => void>(),
    notify: vi.fn(),
    notifyError: vi.fn(),
    openSkillReview: vi.fn()
  })
)

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
vi.mock('@/lib/query-client', () => ({ queryClient: { invalidateQueries } }))
vi.mock('@/lib/slash-completion-cache', () => ({ invalidateSlashCompletions }))

const { watchLearnedSkills } = await import('./learned-skill')

beforeEach(() => {
  listeners.clear()
  notify.mockReset()
  openSkillReview.mockReset()
  invalidateQueries.mockReset()
  invalidateSlashCompletions.mockReset()
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
    expect(openSkillReview).toHaveBeenCalledWith('docker-compose-debug', expect.any(Function))
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

  it('refreshes the Skills tab and the slash list once a review is approved or rejected', () => {
    watchLearnedSkills()
    listeners.get('harvis.skill.drafted')?.({ type: 'harvis.skill.drafted', payload: { name: 'docker-compose-debug' } })
    notify.mock.calls[0][0].action.onClick()

    const onResolved = openSkillReview.mock.calls[0][1]
    expect(invalidateQueries).not.toHaveBeenCalled()

    onResolved({ approved: true, name: 'docker-compose-debug' })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ['skills-list'] })
    expect(invalidateSlashCompletions).toHaveBeenCalledTimes(1)

    onResolved({ approved: false, name: 'docker-compose-debug' })
    expect(invalidateQueries).toHaveBeenCalledTimes(2)
  })

  it('shows nothing for a skipped draft: only the drafted event raises a toast', () => {
    watchLearnedSkills()
    // The backend sends harvis.skill.skipped after every workspace turn that taught nothing (asked=false).
    expect(listeners.has('harvis.skill.skipped')).toBe(false)
    expect([...listeners.keys()]).toEqual(['harvis.skill.drafted'])
    expect(notify).not.toHaveBeenCalled()
  })
})
