"""Agent teammates — a named, persistent agent with a job and a governed computer.

Sub-package layout (each module stays small and single-purpose):

    store.py   pure validation + asyncpg CRUD over the extended owui_subagents
    routes.py  /api/agents — JWT-auth CRUD and run intake

Later milestones add override.py, hard_limits.py, computer.py, audit.py,
memory.py and notify.py alongside these.
"""
