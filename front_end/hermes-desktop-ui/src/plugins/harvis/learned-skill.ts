import { host } from '@hermes/plugin-sdk'

import { setSkillEnabled } from '@/api/skills'

interface Drafted {
  name?: string
  description?: string
}

/**
 * After a hard job (a workspace run, or "save this as a skill") Harvis writes
 * itself a skill — a playbook for next time — and saves it switched OFF
 * (python_back_end/plugins/hermes_ui/learn.py draft_skill). The backend then
 * sends `harvis.skill.drafted`; this turns it into a toast whose Enable is the
 * one click that switches the skill on and marks it trusted (rest_skills.py),
 * after which chats that match it carry it (skill_select.py).
 */
export function watchLearnedSkills(): () => void {
  if (typeof host.onEvent !== 'function') {
    return () => undefined
  }

  return host.onEvent('harvis.skill.drafted', event => {
    const { description, name } = (event?.payload || {}) as Drafted

    if (!name) {
      return
    }

    const id = `harvis-skill-${name}`

    host.notify({
      id,
      kind: 'info',
      icon: 'lightbulb',
      title: 'Harvis learned a skill',
      message: description ? `${name} — ${description}` : name,
      detail: 'It stays off until you enable it. You can read or edit it in Skills.',
      durationMs: 0,
      action: {
        label: 'Enable',
        onClick: () => {
          setSkillEnabled(name, true)
            .then(res =>
              host.notify({
                id,
                kind: res.ok ? 'success' : 'error',
                message: res.ok ? `${name} is on. Harvis will use it when a chat matches.` : `Couldn't enable ${name}.`
              })
            )
            .catch((err: unknown) => host.notifyError(err, `Couldn't enable ${name}`))
        }
      }
    })
  })
}
