import { host } from '@hermes/plugin-sdk'

import { openSkillReview } from './skill-review'

interface Drafted {
  description?: string
  /** 'update' when the model proposed a revision to a skill that already exists. */
  kind?: 'new' | 'update'
  name?: string
}

/**
 * After a hard job (a workspace run, or "save this as a skill") Harvis proposes
 * itself a skill, or a revision to one it has (python_back_end/plugins/hermes_ui/learn.py
 * draft_skill). The backend then sends `harvis.skill.drafted`; this turns it into
 * a toast whose Review button opens the full text and diff (skill-review.tsx).
 * Nothing applies until the person approves there: the toast alone can't switch a
 * skill on, so a one-line summary is never the thing someone vouches for.
 */
export function watchLearnedSkills(): () => void {
  if (typeof host.onEvent !== 'function') {
    return () => undefined
  }

  return host.onEvent('harvis.skill.drafted', event => {
    const { description, kind, name } = (event?.payload || {}) as Drafted

    if (!name) {
      return
    }

    const id = `harvis-skill-${name}`

    host.notify({
      id,
      kind: 'info',
      icon: 'lightbulb',
      title: kind === 'update' ? 'Harvis proposed a skill update' : 'Harvis learned a skill',
      message: description ? `${name} — ${description}` : name,
      detail: 'Nothing changes until you review the full text and approve it.',
      durationMs: 0,
      action: {
        label: 'Review',
        onClick: () => {
          openSkillReview(name)
        }
      }
    })
  })
}
