"""Where a prompt.submit lands in the transcript: appended, or replacing a turn.

Regenerate, edit-and-resend and Retry all resubmit text for a position that is
already in the transcript. The UI names the position with the 1-based
``row_id`` it read from session.history (linear_messages numbers the rows); this
module turns that into a cut point so the old turn and everything after it is
dropped rather than duplicated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

STALE = "That message is not in session history any more (it was already replaced or compressed). Reload the chat."


class RewindError(ValueError):
    pass


@dataclass
class Plan:
    cut: Optional[int] = None  # 0-based row the new user message replaces; None = append
    row_id_map: dict[str, Optional[int]] = field(default_factory=dict)
    inherit_files: list[dict] = field(default_factory=list)

    @property
    def user_row_id(self) -> Optional[int]:
        return None if self.cut is None else self.cut + 1


def failed_turn(msgs: list[dict], i: int) -> bool:
    nxt = msgs[i + 1] if i + 1 < len(msgs) else None
    return bool(nxt and nxt["role"] == "assistant" and nxt.get("error"))


def _flag(value: Any) -> bool:
    return value is True or str(value).lower() in ("1", "true", "yes")


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def plan(msgs: list[dict], params: dict, text: str) -> Plan:
    """The cut for this submit, or RewindError when the target is gone."""
    row_id = _int(params.get("truncate_before_row_id"))
    ordinal = _int(params.get("truncate_before_user_ordinal"))
    wants_cut = _flag(params.get("confirm_truncate")) and (row_id is not None or ordinal is not None)
    if wants_cut:
        if row_id is not None:
            cut = row_id - 1
        else:
            users = [i for i, m in enumerate(msgs) if m["role"] == "user" and not failed_turn(msgs, i)]
            if not 0 <= ordinal < len(users):
                raise RewindError(STALE)
            cut = users[ordinal]
        if not 0 <= cut < len(msgs) or msgs[cut]["role"] != "user":
            raise RewindError(STALE)
        if cut == 0 and not _flag(params.get("confirm_empty_truncate")):
            raise RewindError("This would empty the session. Resend with confirm_empty_truncate to continue.")
        return _planned(msgs, cut, params)
    # Retry after a failed turn: the same text again replaces the failed pair instead of stacking a copy.
    if msgs and not _flag(params.get("confirm_truncate")):
        for tail in (2, 1):
            if len(msgs) < tail:
                continue
            first = msgs[-tail]
            if first["role"] != "user" or (first["content"] or "").strip() != text.strip():
                continue
            if tail == 2 and not msgs[-1].get("error"):
                continue
            if tail == 1 and msgs[-1]["role"] != "user":
                continue
            return _planned(msgs, len(msgs) - tail, params)
    return Plan()


def _planned(msgs: list[dict], cut: int, params: dict) -> Plan:
    survivors = params.get("rebind_survivor_row_ids")
    id_map: dict[str, Optional[int]] = {}
    for raw in survivors if isinstance(survivors, list) else []:
        old = _int(raw)
        if old is not None:
            id_map[str(old)] = old if old <= cut + 1 else None
    # Every row at or after the cut is gone, except that the new user message takes the cut's own position.
    return Plan(cut=cut, row_id_map=id_map, inherit_files=list(msgs[cut].get("attachments") or []))
