"""Turn mined trajectories into a real proposed revision of a Harvis skill.

This replaces the placeholder that used to echo the base skill back inside a
note reading "trainer not run". The optimizer here is deliberately modest and
deliberately honest about what it is:

  aggregate the corpus (arithmetic) → ask a local model to revise the skill
  against that evidence → validate the result structurally → hand a human a
  DRAFT for review.

It is not microsoft/skillopt. There is no rollout loop and no held-out
empirical gate, because Harvis cannot replay a past Build run against a revised
skill — the repos, branches and sandboxes are gone. `held_out_pass` therefore
stays None and the reason is recorded on the proposal rather than papered over
with a number that would look like a measurement.

The model runs on the local Ollama endpoint, so nothing leaves the box.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .trajectories import TrajectorySample, aggregate_evidence, evidence_markdown, redact

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("HARVIS_SKILLOPT_MODEL") or "gpt-oss:20b"
_REQUEST_TIMEOUT = int(os.getenv("HARVIS_SKILLOPT_TIMEOUT") or "600")

# Tool names the runner actually offers. A proposal that invents a tool would
# teach the model to call something that does not exist, so this is a hard
# check rather than advice. Imported live when the backend package is on the
# path; the literal list is the fallback for a standalone trainer run and is
# kept in sync with workspace/orchestration/tools.py:WIRE_TOOL_SCHEMA.
_FALLBACK_TOOLS = {
    "read_file", "edit_file", "str_replace", "apply_patch", "exec", "run_tests",
    "run_code", "git_commit", "finish", "propose_skill", "screenshot_preview",
    "generate_image", "agent_reach_web_search", "agent_reach_web_read",
    "agent_reach_yt_transcript", "agent_reach_gh_view", "agent_reach_rss_read",
}


def known_tool_names() -> set[str]:
    try:
        from workspace.orchestration.tools import WIRE_TOOL_SCHEMA  # type: ignore

        live = {
            str(t.get("function", {}).get("name") or t.get("name") or "")
            for t in WIRE_TOOL_SCHEMA
        }
        live.discard("")
        if live:
            return live | _FALLBACK_TOOLS
    except Exception as exc:  # noqa: BLE001 — standalone run, no backend on path
        logger.debug("skillopt: live tool schema unavailable (%s), using fallback list", exc)
    return set(_FALLBACK_TOOLS)


@dataclass
class SkillOptProposal:
    skill_name: str
    proposed_md: str
    rationale: str
    held_out_pass: bool | None = None
    held_out_note: str = ""
    validation_pass: bool = False
    checks: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    changed: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


_SYSTEM = """You revise operating instructions for a coding agent.

You are given the CURRENT skill document and EVIDENCE aggregated from real runs
of an agent that was following it. Produce a REVISED version of the document.

Hard rules:
- Output the complete revised markdown document and nothing else. No preamble,
  no explanation, no code fence around the whole document.
- Keep the YAML frontmatter block, and keep the `name:` value byte-identical.
- Never invent a tool. Only the tool names that already appear in the current
  document, or that appear in the evidence, exist.
- Never grant capabilities, raise a permission lane, or instruct the agent to
  bypass a gate. Skills are text guidance only.
- Change only what the evidence supports. Where the evidence says nothing,
  leave the existing text alone. A near-identical document is a valid answer.
- Add guidance that is concrete and checkable. "Be careful" is worthless;
  "`str_replace` fails 41% of the time — re-read the file immediately before
  each call and copy the line verbatim" is useful.
"""

_USER = """## CURRENT SKILL

{base}

## EVIDENCE FROM {total} REAL RUNS

{evidence}

## FAILURE EXAMPLES

{failures}

Revise the skill so an agent following it would have failed less often in the
runs above. Output the complete revised document only."""


def _failure_examples(samples: list[TrajectorySample], limit: int = 8) -> str:
    rows = [s for s in samples if s.outcome == "fail" and (s.error or s.failed_tools)]
    rows.sort(key=lambda s: -len(s.failed_tools))
    if not rows:
        return "(no failing run in the corpus recorded an error message or a failed tool call)"
    out = []
    for s in rows[:limit]:
        bits = [f"- task: {s.prompt_excerpt[:160]!r}"]
        if s.failed_tools:
            bits.append(f"  failed tool calls: {', '.join(s.failed_tools[:6])}")
        if s.error:
            bits.append(f"  error: {s.error[:180]}")
        out.append("\n".join(bits))
    return "\n".join(out)


def _ollama_base() -> str:
    return (
        os.getenv("HARVIS_SKILLOPT_LLM_URL")
        or os.getenv("HARVIS_LLM_BASE_URL")
        or os.getenv("OLLAMA_URL")
        or "http://host.docker.internal:11434"
    ).rstrip("/")


def call_local_model(system: str, user: str, model: str) -> tuple[str, str]:
    """Return (text, error). Never raises — an unreachable model is a result."""
    url = f"{_ollama_base()}/api/chat"
    body = json.dumps({
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.2, "num_ctx": 16384},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return "", f"HTTP {exc.code} from {url}: {exc.read()[:200].decode(errors='replace')}"
    except Exception as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__} calling {url}: {exc}"
    text = str((payload.get("message") or {}).get("content") or "").strip()
    if not text:
        return "", f"model {model} returned an empty message"
    return text, ""


_FENCE_RE = re.compile(r"^\s*```(?:markdown|md)?\s*\n(.*)\n```\s*$", re.S)


def _strip_wrapping_fence(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


# Local models like to retype ASCII hyphens as non-breaking hyphens and NBSPs.
# Left alone, every reviewer's diff fills with churn that isn't a change.
_TYPOGRAPHIC_NOISE = {"‑": "-", " ": " ", "​": ""}


def _normalize(text: str) -> str:
    for bad, good in _TYPOGRAPHIC_NOISE.items():
        text = text.replace(bad, good)
    return text


def _frontmatter(md: str) -> tuple[dict[str, str], str]:
    """Shallow top-level key scrape — enough to check `name`, not a YAML parser."""
    if not md.startswith("---"):
        return {}, md
    end = md.find("\n---", 3)
    if end == -1:
        return {}, md
    block = md[3:end]
    keys: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            keys[m.group(1)] = m.group(2).strip()
    return keys, md[end + 4:]


_TOOL_TOKEN_RE = re.compile(r"`([a-z][a-z0-9_.]{2,40})`")
# Deliberately narrow. "self-activate" is NOT here: the base skill says
# "never self-activates", and a gate that fires on the document's own safety
# language rejects correct proposals. Each pattern below is an instruction to
# do something the human review step exists to prevent.
_ESCALATION_RE = re.compile(
    r"(mark (it|this|the skill|the draft) (as )?supported|set (the )?(audit )?verdict|"
    r"risk_lane\s*:\s*[45]|bypass (the )?(gate|lane|approval|verdict)|"
    r"enable (it|yourself|this skill|the skill) yourself)",
    re.I,
)


def validate_proposal(
    proposed_md: str,
    base_md: str,
    skill_name: str,
    observed_tools: set[str] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Structural gate. Every check is mechanical and its failure is reported.

    `observed_tools` are tool names that actually appear in the mined corpus.
    They count as real: the proposer is told it may reference what the evidence
    shows, and runs legitimately call tools from other lanes (MCP, research)
    that are not in the Build runner's own wire schema.
    """
    checks: dict[str, Any] = {}
    tools = known_tool_names() | (observed_tools or set())

    checks["non_empty"] = bool(proposed_md.strip())

    fm, body = _frontmatter(proposed_md)
    base_fm, _ = _frontmatter(base_md)
    checks["has_frontmatter"] = bool(fm)
    checks["name_preserved"] = fm.get("name", "").strip().strip('"\'') == skill_name

    base_len = max(len(base_md), 1)
    ratio = len(proposed_md) / base_len
    checks["length_ratio"] = round(ratio, 2)
    checks["length_sane"] = 0.5 <= ratio <= 3.0

    # A tool token is a backticked lowercase identifier. Anything matching that
    # shape which is not a real tool AND does not already appear anywhere in the
    # base document is an invention. Matching against the base's whole
    # vocabulary — not just its backticked spans — keeps parameter names like
    # old_str, which the base mentions in prose, from reading as new tools.
    # rstrip('.'): the character class also matches a sentence-ending period, so
    # "…copy into str_replace old_str." would otherwise register as `old_str.`
    # and leave the real token looking invented.
    base_vocab = {
        w.rstrip(".") for w in re.findall(r"[a-z][a-z0-9_.]{2,40}", base_md)
    }
    invented = sorted(
        t for t in set(_TOOL_TOKEN_RE.findall(proposed_md))
        if t not in tools and t not in base_vocab and "_" in t
    )
    checks["invented_tools"] = invented
    checks["no_invented_tools"] = not invented

    # A phrase already present verbatim in the base document cannot be an
    # escalation the proposal introduced.
    esc = next(
        (m for m in _ESCALATION_RE.finditer(proposed_md) if m.group(0) not in base_md),
        None,
    )
    checks["escalation_phrase"] = esc.group(0) if esc else ""
    checks["no_escalation"] = esc is None

    checks["no_secrets"] = redact(proposed_md) == proposed_md

    base_lane = base_fm.get("risk_lane") or ""
    prop_lane = fm.get("risk_lane") or ""
    checks["risk_lane_not_raised"] = not (prop_lane and base_lane and prop_lane > base_lane)

    gates = [
        "non_empty", "has_frontmatter", "name_preserved", "length_sane",
        "no_invented_tools", "no_escalation", "no_secrets", "risk_lane_not_raised",
    ]
    passed = all(bool(checks.get(g)) for g in gates)
    checks["failed_gates"] = [g for g in gates if not checks.get(g)]
    return passed, checks


_HELD_OUT_NOTE = (
    "Not evaluated. A held-out gate would require replaying past Build runs against "
    "the revised skill; those runs' repos, branches and sandboxes no longer exist, so "
    "no empirical pass/fail can be produced. The structural checks below are what was "
    "actually verified. Treat this as a draft for human review, not a measured win."
)


def propose_skill_diff(
    base_skill_md: str,
    samples: list[TrajectorySample],
    *,
    skill_name: str = "harvis-build",
    model: str | None = None,
) -> SkillOptProposal:
    """Propose a revised skill from the corpus. Falls back honestly."""
    evidence = aggregate_evidence(samples)
    model = model or DEFAULT_MODEL

    if not samples:
        return SkillOptProposal(
            skill_name=skill_name,
            proposed_md=base_skill_md,
            rationale="No trajectories in the corpus — nothing to learn from, so the skill is "
                      "returned unchanged. Mine runs first (`--from-db`).",
            held_out_note=_HELD_OUT_NOTE,
            validation_pass=False,
            checks={"failed_gates": ["empty_corpus"]},
            evidence=evidence,
            model=model,
            changed=False,
        )

    prompt = _USER.format(
        base=base_skill_md.strip(),
        total=evidence["total"],
        evidence=evidence_markdown(evidence),
        failures=_failure_examples(samples),
    )
    text, err = call_local_model(_SYSTEM, prompt, model)

    if err or not text:
        return SkillOptProposal(
            skill_name=skill_name,
            proposed_md=base_skill_md,
            rationale=f"Optimizer could not run: {err or 'no output'}. The skill is returned "
                      f"UNCHANGED — this is a failure, not a no-op proposal. Evidence was still "
                      f"aggregated and is recorded below.",
            held_out_note=_HELD_OUT_NOTE,
            validation_pass=False,
            checks={"failed_gates": ["model_unreachable"], "error": err},
            evidence=evidence,
            model=model,
            changed=False,
        )

    proposed = _normalize(_strip_wrapping_fence(text).strip()) + "\n"
    observed = {t for s in samples for t in s.tool_trace}
    ok, checks = validate_proposal(proposed, base_skill_md, skill_name, observed_tools=observed)
    changed = proposed.strip() != base_skill_md.strip()

    if ok:
        rationale = (
            f"Revised against {evidence['total']} real runs "
            f"({evidence['ok']} ok / {evidence['fail']} failed, "
            f"{evidence['success_rate'] * 100:.1f}% success) by {model} on the local endpoint. "
            f"All {len(checks) - 2} structural checks passed. "
            f"{'Text changed.' if changed else 'Model returned the document unchanged.'}"
        )
    else:
        rationale = (
            f"Proposal REJECTED by the structural gate: {', '.join(checks['failed_gates'])}. "
            f"The text below is what the model produced and is kept only so the failure is "
            f"inspectable — do not promote it."
        )

    return SkillOptProposal(
        skill_name=skill_name,
        proposed_md=proposed,
        rationale=rationale,
        held_out_note=_HELD_OUT_NOTE,
        validation_pass=ok,
        checks=checks,
        evidence=evidence,
        model=model,
        changed=changed,
    )
