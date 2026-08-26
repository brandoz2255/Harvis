"""Mine real Harvis Build runs out of Postgres into SkillOpt trajectories.

Before this module, `skillopt_job` could only read a `trajectories.jsonl` that
nothing ever wrote — so the trainer had an empty corpus by construction while
hundreds of real runs sat in `workspace_runs` / `workspace_events`.

What a trajectory is here: one workspace run, reduced to the few things a skill
optimizer can actually learn from — the task brief, whether it finished, the
ordered tool trace, which tool calls failed, and the error text if it died.
Nothing else is carried. In particular **tool OUTPUT is never read**, because
`tool_result.output` contains raw command output that has already been shown to
hold a live API key (see the env-dump incident in `workspace_events`). Tool
names and success flags are enough signal and carry no payload.

Read-only: this module issues SELECTs and nothing else.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# workspace_runs.status → outcome label. 'running'/'sandbox' are in-flight or
# scratch and are excluded from the corpus entirely rather than guessed at.
_OK_STATUSES = {"done", "completed"}
_FAIL_STATUSES = {"error", "cancelled"}

DEFAULT_SKILL_NAME = "harvis-build"

# Redaction applied to every free-text field before it leaves the DB. The corpus
# is written to disk and fed to a model, so it gets the same treatment as any
# other export.
_SECRET_PATTERNS = [
    re.compile(r"\b(sk-[A-Za-z0-9._\-]{12,})"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{16,})"),
    re.compile(r"\b(xox[abps]-[A-Za-z0-9-]{10,})"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\b(ey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"),
    re.compile(r"((?:api[_-]?key|token|secret|password|passwd|authorization)\s*[=:]\s*)(\S+)", re.I),
]


def redact(text: str) -> str:
    """Strip anything that looks like a credential out of free text."""
    if not text:
        return ""
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 2:
            out = pat.sub(lambda m: f"{m.group(1)}[REDACTED]", out)
        else:
            out = pat.sub("[REDACTED]", out)
    return out


@dataclass
class TrajectorySample:
    """One mined run. Kept JSON-round-trippable — this is the on-disk format."""

    run_id: str
    skill_name: str
    prompt_excerpt: str
    outcome: str  # ok | fail | unknown
    tool_trace: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    model: str = ""
    source: str = ""
    duration_ms: int | None = None
    error: str = ""
    summary_excerpt: str = ""

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> "TrajectorySample":
        known = {f for f in cls.__dataclass_fields__}  # noqa: SLF001 — dataclass API
        return cls(**{k: v for k, v in obj.items() if k in known})


def _as_dict(payload: Any) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            loaded = json.loads(payload)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:  # noqa: BLE001 — malformed rows are skipped, not fatal
            return {}
    return {}


def _outcome_for(status: str) -> str:
    s = (status or "").strip().lower()
    if s in _OK_STATUSES:
        return "ok"
    if s in _FAIL_STATUSES:
        return "fail"
    return "unknown"


_RUN_SQL = """
SELECT id, task_brief, status, model_provider, model_name, source,
       duration_ms, error_message, final_summary
FROM workspace_runs
WHERE status = ANY($1::text[])
  AND task_brief IS NOT NULL
  AND length(btrim(task_brief)) > 0
ORDER BY started_at DESC NULLS LAST
LIMIT $2
"""

_EVENT_SQL = """
SELECT workspace_id, event_type, payload
FROM workspace_events
WHERE workspace_id = ANY($1::text[])
  AND event_type IN ('tool_call', 'tool_result', 'error')
ORDER BY workspace_id, seq
"""


async def mine_trajectories(
    dsn: str,
    *,
    limit: int = 500,
    skill_name: str = DEFAULT_SKILL_NAME,
    min_tool_calls: int = 1,
) -> list[TrajectorySample]:
    """Read completed runs + their tool traces into TrajectorySamples.

    `min_tool_calls` drops chat-only runs ("hello") that used no tool — they
    teach a coding skill nothing and would otherwise dominate the corpus.
    """
    import asyncpg  # local import: the trainer runs outside the API process too

    conn = await asyncpg.connect(dsn)
    try:
        statuses = sorted(_OK_STATUSES | _FAIL_STATUSES)
        runs = await conn.fetch(_RUN_SQL, statuses, int(limit))
        if not runs:
            return []
        ids = [str(r["id"]) for r in runs]
        events = await conn.fetch(_EVENT_SQL, ids)
    finally:
        await conn.close()

    traces: dict[str, list[str]] = {rid: [] for rid in ids}
    failures: dict[str, list[str]] = {rid: [] for rid in ids}
    ev_errors: dict[str, str] = {}

    for ev in events:
        rid = str(ev["workspace_id"])
        payload = _as_dict(ev["payload"])
        et = ev["event_type"]
        if et == "tool_call":
            tool = str(payload.get("tool") or "").strip()
            if tool and tool != "finish":
                traces.setdefault(rid, []).append(tool)
        elif et == "tool_result":
            if payload.get("success") is False:
                tool = str(payload.get("tool") or "").strip()
                if tool:
                    failures.setdefault(rid, []).append(tool)
        elif et == "error":
            if rid not in ev_errors:
                ev_errors[rid] = str(payload.get("message") or "")

    samples: list[TrajectorySample] = []
    for r in runs:
        rid = str(r["id"])
        trace = traces.get(rid, [])
        if len(trace) < min_tool_calls:
            continue
        model = str(r["model_name"] or "")
        provider = str(r["model_provider"] or "")
        samples.append(
            TrajectorySample(
                run_id=rid,
                skill_name=skill_name,
                prompt_excerpt=redact(str(r["task_brief"] or "").strip())[:600],
                outcome=_outcome_for(str(r["status"] or "")),
                tool_trace=trace[:80],
                failed_tools=failures.get(rid, [])[:20],
                model=f"{provider}/{model}".strip("/") if (provider or model) else "",
                source=str(r["source"] or ""),
                duration_ms=int(r["duration_ms"]) if r["duration_ms"] is not None else None,
                error=redact(str(r["error_message"] or ev_errors.get(rid, "")))[:400],
                summary_excerpt=redact(str(r["final_summary"] or "").strip())[:400],
            )
        )

    logger.info(
        "skillopt: mined %d trajectories from %d candidate runs (min_tool_calls=%d)",
        len(samples), len(runs), min_tool_calls,
    )
    return samples


def mine_trajectories_sync(dsn: str, **kwargs: Any) -> list[TrajectorySample]:
    return asyncio.run(mine_trajectories(dsn, **kwargs))


def write_jsonl(samples: list[TrajectorySample], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for s in samples:
            fh.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
    return path


def read_jsonl(path: Path) -> list[TrajectorySample]:
    if not path.is_file():
        return []
    out: list[TrajectorySample] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(TrajectorySample.from_json(json.loads(line)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("skillopt: skipping malformed trajectory line: %s", exc)
    return out


def aggregate_evidence(samples: list[TrajectorySample]) -> dict[str, Any]:
    """Turn raw trajectories into the few counts a proposer can reason over.

    Everything here is arithmetic on the corpus — no model, no guessing. The
    proposer is handed this instead of hundreds of raw runs so its input stays
    inside a context window and its claims stay checkable.
    """
    ok = [s for s in samples if s.outcome == "ok"]
    fail = [s for s in samples if s.outcome == "fail"]

    def tool_freq(rows: list[TrajectorySample]) -> Counter:
        c: Counter = Counter()
        for s in rows:
            c.update(s.tool_trace)
        return c

    ok_tools, fail_tools = tool_freq(ok), tool_freq(fail)
    failed_tool_counts: Counter = Counter()
    for s in samples:
        failed_tool_counts.update(s.failed_tools)

    # Per-tool failure rate: of every call to this tool, how many came back
    # success=false. This is the signal that says "the skill's guidance about
    # this tool is not landing".
    call_counts: Counter = Counter()
    for s in samples:
        call_counts.update(s.tool_trace)
    failure_rates = {
        tool: round(failed_tool_counts[tool] / call_counts[tool], 3)
        for tool in call_counts
        if call_counts[tool] >= 5
    }

    errors: Counter = Counter()
    for s in samples:
        if s.error:
            errors[s.error[:160]] += 1

    def avg(rows: list[TrajectorySample], attr: str) -> float:
        vals = [len(getattr(r, attr)) for r in rows]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    return {
        "total": len(samples),
        "ok": len(ok),
        "fail": len(fail),
        "success_rate": round(len(ok) / len(samples), 3) if samples else 0.0,
        "avg_tools_ok": avg(ok, "tool_trace"),
        "avg_tools_fail": avg(fail, "tool_trace"),
        "tools_in_ok_runs": ok_tools.most_common(15),
        "tools_in_fail_runs": fail_tools.most_common(15),
        "tool_failure_rates": dict(sorted(failure_rates.items(), key=lambda kv: -kv[1])[:15]),
        "top_errors": errors.most_common(10),
        "models": Counter(s.model for s in samples if s.model).most_common(8),
    }


def evidence_markdown(ev: dict[str, Any]) -> str:
    """Render the aggregate as compact markdown for a prompt or a report."""
    lines = [
        f"- Corpus: **{ev['total']}** runs — {ev['ok']} succeeded, {ev['fail']} failed "
        f"({ev['success_rate'] * 100:.1f}% success).",
        f"- Tool calls per run: {ev['avg_tools_ok']} on success vs {ev['avg_tools_fail']} on failure.",
    ]
    if ev["tools_in_ok_runs"]:
        lines.append("- Tools in successful runs: "
                     + ", ".join(f"`{t}`×{n}" for t, n in ev["tools_in_ok_runs"]))
    if ev["tools_in_fail_runs"]:
        lines.append("- Tools in failed runs: "
                     + ", ".join(f"`{t}`×{n}" for t, n in ev["tools_in_fail_runs"]))
    if ev["tool_failure_rates"]:
        lines.append("- Per-tool failure rate (≥5 calls): "
                     + ", ".join(f"`{t}` {r * 100:.0f}%" for t, r in ev["tool_failure_rates"].items()))
    if ev["top_errors"]:
        lines.append("- Most common run errors:")
        lines += [f"    {n}× {e}" for e, n in ev["top_errors"]]
    return "\n".join(lines)


def default_dsn() -> str:
    return (
        os.getenv("HARVIS_SKILLOPT_DSN")
        or os.getenv("DATABASE_URL")
        or "postgresql://pguser:pgpassword@pgsql:5432/database"
    )
