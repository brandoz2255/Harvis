"""Offline SkillOpt job — mine real Build runs, propose a revised skill.

Upstream inspiration: https://github.com/microsoft/skillopt (MIT). This is not
that trainer and does not claim to be; see `proposer.py` for exactly what it
does and what it deliberately does not measure.

NOT on the chat hot path. Never runs per turn, never ships in the default
image's startup. The loop it closes is:

    workspace_runs/workspace_events   (real Build history)
      → trajectories.mine_trajectories
      → proposer.propose_skill_diff   (local model, no egress)
      → structural gate
      → DRAFT skill in owui_skills, enabled=FALSE, no audit verdict
      → human marks it 'supported' in Customize → Skills

The last step is a person. Nothing here can activate a skill; the verdict gate
in `chat_completion._inject_skills` withholds an unaudited skill's body
regardless of what this job writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .proposer import SkillOptProposal, propose_skill_diff
from .trajectories import (
    DEFAULT_SKILL_NAME,
    TrajectorySample,
    default_dsn,
    evidence_markdown,
    mine_trajectories,
    read_jsonl,
    write_jsonl,
)

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def skillopt_enabled() -> bool:
    """Offline trainer master switch — default OFF."""
    return (os.getenv("HARVIS_SKILLOPT_ENABLED") or "").strip().lower() in _TRUTHY


def collect_trajectories_stub(source_dir: Path) -> list[TrajectorySample]:
    """Load a previously mined `trajectories.jsonl` from disk.

    Kept as the file-backed path (and under its original name, which other
    modules import). `mine_trajectories` is the source that actually fills it.
    """
    path = source_dir / "trajectories.jsonl"
    if not path.is_file():
        logger.info("skillopt: no trajectories at %s", path)
        return []
    return read_jsonl(path)


async def _publish_draft(
    proposal: SkillOptProposal, *, dsn: str, user_id: int
) -> dict[str, Any]:
    """Insert the proposal as a DRAFT skill for human review.

    enabled=FALSE and meta.audit={} — the same double lock Phase F's
    run→skill extraction uses. A draft is inert until a human records a
    'supported' verdict in Customize → Skills.
    """
    import asyncpg

    sid = str(uuid.uuid4())
    meta = {
        "requires_capabilities": [],
        "risk_lane": 3,
        "allowed_targets": ["repo_sandbox"],
        "draft": True,
        "audit": {},
        "skillopt": {
            "base_skill": proposal.skill_name,
            "model": proposal.model,
            "validation_pass": proposal.validation_pass,
            "held_out_pass": proposal.held_out_pass,
            "held_out_note": proposal.held_out_note,
            "checks": proposal.checks,
            "evidence": proposal.evidence,
            "created_at": proposal.created_at,
        },
    }
    name = f"{proposal.skill_name} (SkillOpt candidate)"
    desc = (
        f"Proposed revision of {proposal.skill_name} from "
        f"{proposal.evidence.get('total', 0)} real Build runs. Draft — review before enabling."
    )
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO owui_skills (id, user_id, name, description, content, emoji, meta, enabled) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, FALSE)",
            sid, int(user_id), name, desc, proposal.proposed_md, "🧬", json.dumps(meta),
        )
    finally:
        await conn.close()
    return {"skill_id": sid, "name": name, "enabled": False}


def run_offline_job(
    *,
    trajectories_dir: Path,
    skill_path: Path,
    out_dir: Path,
    from_db: bool = False,
    dsn: str | None = None,
    limit: int = 500,
    min_tool_calls: int = 1,
    model: str | None = None,
    skill_name: str = DEFAULT_SKILL_NAME,
    publish_draft_user: int | None = None,
) -> dict[str, Any]:
    if not skillopt_enabled():
        return {
            "ok": False,
            "reason": "HARVIS_SKILLOPT_ENABLED is off — refusing to run trainer",
        }

    if not skill_path.is_file():
        return {"ok": False, "reason": f"base skill not found at {skill_path}"}
    base = skill_path.read_text(encoding="utf-8")

    if from_db:
        dsn = dsn or default_dsn()
        try:
            samples = asyncio.run(
                mine_trajectories(
                    dsn, limit=limit, skill_name=skill_name, min_tool_calls=min_tool_calls
                )
            )
        except Exception as exc:  # noqa: BLE001 — a dead DB is a reported result
            return {"ok": False, "reason": f"could not mine trajectories: {exc}"}
        write_jsonl(samples, trajectories_dir / "trajectories.jsonl")
    else:
        samples = collect_trajectories_stub(trajectories_dir)

    proposal = propose_skill_diff(base, samples, skill_name=skill_name, model=model)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "best_skill.candidate.md"
    out_json = out_dir / "proposal.json"
    out_report = out_dir / "evidence.md"
    out_md.write_text(proposal.proposed_md, encoding="utf-8")
    out_json.write_text(json.dumps(asdict(proposal), indent=2), encoding="utf-8")
    out_report.write_text(
        f"# SkillOpt evidence — {proposal.skill_name}\n\n"
        f"_{proposal.created_at} · model `{proposal.model}`_\n\n"
        f"{evidence_markdown(proposal.evidence)}\n\n"
        f"## Verdict\n\n{proposal.rationale}\n\n"
        f"## Held-out gate\n\n{proposal.held_out_note}\n",
        encoding="utf-8",
    )

    result: dict[str, Any] = {
        "ok": True,
        "samples": len(samples),
        "changed": proposal.changed,
        "validation_pass": proposal.validation_pass,
        "failed_gates": proposal.checks.get("failed_gates", []),
        "held_out_pass": proposal.held_out_pass,
        "model": proposal.model,
        "success_rate": proposal.evidence.get("success_rate"),
        "out_md": str(out_md),
        "out_json": str(out_json),
        "out_report": str(out_report),
    }

    if publish_draft_user is not None:
        if not proposal.validation_pass:
            result["published"] = None
            result["publish_skipped"] = (
                "proposal failed the structural gate — not published as a draft"
            )
        else:
            try:
                result["published"] = asyncio.run(
                    _publish_draft(proposal, dsn=dsn or default_dsn(), user_id=publish_draft_user)
                )
            except Exception as exc:  # noqa: BLE001
                result["published"] = None
                result["publish_error"] = str(exc)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Harvis SkillOpt offline job")
    p.add_argument(
        "--trajectories",
        type=Path,
        default=Path(os.getenv("HARVIS_SKILLOPT_TRAJECTORIES", "/data/skillopt")),
        help="directory holding (or receiving) trajectories.jsonl",
    )
    p.add_argument("--skill", type=Path, default=Path("skills/Harvis/harvis-build/SKILL.md"))
    p.add_argument("--out", type=Path, default=Path(os.getenv("HARVIS_SKILLOPT_OUT", "/data/skillopt/out")))
    p.add_argument("--from-db", action="store_true",
                   help="mine trajectories from workspace_runs instead of reading the JSONL")
    p.add_argument("--dsn", default=None, help="Postgres DSN (default: $DATABASE_URL)")
    p.add_argument("--limit", type=int, default=500, help="max runs to mine")
    p.add_argument("--min-tool-calls", type=int, default=1,
                   help="drop runs with fewer tool calls than this (chat-only noise)")
    p.add_argument("--model", default=None, help="local model for the proposer")
    p.add_argument("--skill-name", default=DEFAULT_SKILL_NAME)
    p.add_argument("--publish-draft", type=int, metavar="USER_ID", default=None,
                   help="insert the proposal as a DISABLED draft skill owned by this user id")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = run_offline_job(
        trajectories_dir=args.trajectories,
        skill_path=args.skill,
        out_dir=args.out,
        from_db=args.from_db,
        dsn=args.dsn,
        limit=args.limit,
        min_tool_calls=args.min_tool_calls,
        model=args.model,
        skill_name=args.skill_name,
        publish_draft_user=args.publish_draft,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
