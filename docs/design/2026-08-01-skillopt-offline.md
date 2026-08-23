# SkillOpt / SkillOpt-Sleep — offline skills improvement

Date: 2026-08-01 · Status: scaffold only

Upstream: https://github.com/microsoft/skillopt (MIT)

## Locked split

| Now | Later |
|-----|--------|
| Seed `skills/Harvis/harvis-build/SKILL.md` + owui_skills supported seed | Offline trainer mining Build trajectories |
| Inject Build skill into vibecode system prompt | Skills UI “Improve skill from past runs” |
| | SkillOpt-Sleep nightly cron |

## Run (when ready)

```bash
HARVIS_SKILLOPT_ENABLED=1 ./scripts/skillopt-offline.sh
```

Writes `best_skill.candidate.md` under `data/skillopt/out/`. Does **not** auto-publish;
human audit / supported gate still required.

## Non-goals

- Not a chat skill pasted every turn
- Not in the default 7 GB image
- Not OpenClaw egress for training rollouts by default
