"""Guarded migration: unique index on workspace_events(workspace_id, seq).

Backstop for the single-allocator fix (see terminal_container.allocate_event_seq):
all event writers now draw seq from one per-workspace monotonic allocator, so new
duplicate (workspace_id, seq) pairs cannot be produced in-process. This index
makes that guarantee hold across processes/restarts too.

DELIBERATELY NON-DESTRUCTIVE: databases written before the allocator fix may
already contain duplicate (workspace_id, seq) rows (the old split between
emit_terminal_event's MAX(seq)+1 and the run loop's in-memory counter). Creating
a unique index over such data would fail — and deduplicating automatically would
DELETE trace history, which is worse than a missing constraint. So:

  * duplicates found  → log a WARNING with the affected workspaces and SKIP the
                        index (rows are never touched; rerun after a manual
                        cleanup if the constraint is wanted on that DB)
  * no duplicates     → CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_events_ws_seq

Idempotent; called from main.py's lifespan migration block on every startup.
"""

import logging

logger = logging.getLogger(__name__)

_DUP_CHECK_SQL = """
SELECT workspace_id, seq, COUNT(*) AS n
FROM workspace_events
GROUP BY workspace_id, seq
HAVING COUNT(*) > 1
LIMIT 10
"""

_CREATE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_events_ws_seq
    ON workspace_events(workspace_id, seq)
"""


async def ensure_events_seq_unique_index(conn) -> bool:
    """Create the (workspace_id, seq) unique index iff no historical duplicates
    exist. Returns True when the index is in place, False when skipped."""
    dupes = await conn.fetch(_DUP_CHECK_SQL)
    if dupes:
        logger.warning(
            "workspace_events has %d+ duplicate (workspace_id, seq) pairs from the "
            "pre-allocator era (e.g. %s) — SKIPPING uq_workspace_events_ws_seq so no "
            "trace history is lost. The seq allocator prevents new duplicates; clean "
            "up the old rows manually if the index is wanted on this DB.",
            len(dupes),
            ", ".join(f"{r['workspace_id']}#{r['seq']}x{r['n']}" for r in dupes[:3]),
        )
        return False
    await conn.execute(_CREATE_INDEX_SQL)
    logger.info("✅ uq_workspace_events_ws_seq unique index ensured on workspace_events")
    return True
