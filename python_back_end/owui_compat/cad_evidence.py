"""The evidence layer's shared vocabulary (HE-3).

The engine measures; this module decides what the backend is willing to persist,
display and grade. It sits between them because the two have different jobs and
different trust:

* ``cad-engine/measure.py`` runs inside a networkless, killable child and owns the
  OpenCascade arithmetic. It is the only thing that touches geometry.
* ``cad_conformance`` grades numbers against a spec. It must never guess at a shape.

Between them is a wire, and a wire needs a contract. Everything the engine sends is
re-validated here — not because the engine is untrusted in the security sense, but
because a build from an *older engine image* is a completely ordinary thing to find
in this table, and a field it never wrote must read as absent rather than as zero.

Three rules are load-bearing and are the reason this file exists at all:

1. **A measurement that could not be taken has ``value: None``.** Never ``0.0``. Zero
   is a legitimate reading — a perfectly seated lid genuinely has zero interference —
   so coercing "unknown" into it would make the two indistinguishable exactly where
   the distinction decides a verdict.
2. **Unresolved target ⇒ ``unverified``, never ``failed``.** Not knowing whether a
   part is wrong is not the same as knowing it is.
3. **A measurement is displayed only under the revision it was taken on**, matched by
   ``source_hash``. This mirrors the check ``save_render`` already applies to captured
   images (``cad_store.py:1253-1256``): a number attached to the wrong geometry is
   worse than no number, because it looks like proof.
"""
from __future__ import annotations

import logging

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_TRUTHY = {"1", "true", "yes", "on"}

# The whole tranche's flag, on top of the existing `fab_cad.cad_enabled()`. Off means
# the pre-HE code path runs unchanged: measurements are neither requested nor stored.
FLAG = "HARVIS_CAD_EVIDENCE_V2"


def evidence_enabled() -> bool:
    return (os.getenv(FLAG) or "").strip().lower() in _TRUTHY


# A build asking for more than this is not measuring, it is scanning. The engine
# enforces its own cap in `measure_spec`; this is the backend's independent one, and
# they are deliberately allowed to differ — the tighter of the two wins, which is the
# correct failure direction.
MAX_MEASUREMENTS = 64

logger = logging.getLogger(__name__)

Unit = Literal["mm", "deg", "mm3", "count"]
Comparator = Literal["eq", "gte", "lte", "between"]
# REQUIRED on every circular dimension. "0.3 mm clearance" is ambiguous in ordinary
# speech and the two readings differ by a factor of two; a number without a basis
# cannot be graded.
Basis = Literal["radial", "diametral"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Tolerance(StrictModel):
    """What "correct" means for one dimension.

    ``plus``/``minus`` are magnitudes, always non-negative — a minus band is written
    ``minus=0.1``, not ``-0.1``, so that a sign slip cannot silently invert a bound.
    """

    kind: Literal["symmetric", "asymmetric", "min_only", "max_only"]
    nominal: float = Field(allow_inf_nan=False)
    plus: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    minus: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    unit: Unit


class TargetResolution(StrictModel):
    """Whether the thing to be measured was found, and how.

    ``candidates_considered`` is what separates "there was nothing to measure" from
    "there were two and I will not guess". Both are unresolved; only the second is a
    modelling ambiguity worth telling the user about.
    """

    resolved: bool
    candidates_considered: int = Field(ge=0)
    method: str = Field(min_length=1, max_length=64)
    # The resolver's own version, separate from the measurement method's. `targets.py`
    # has written it since HE-1; this model forbids extra keys, so leaving it undeclared
    # dropped every record the engine produced. Defaulted rather than required because
    # a build from an engine image older than HE-1 legitimately has no resolver version,
    # and an absent one must read as unknown rather than cost the measurement.
    method_version: str = Field(default="0", min_length=1, max_length=16)
    reason: str | None = Field(default=None, max_length=400)


class Measurement(StrictModel):
    """One number, everything needed to trust it, and everything needed to reproduce it.

    ``model_config`` forbids extra keys, but the engine legitimately adds a few
    kind-specific ones (``diametral_mm`` on a clearance) — those are named fields
    here rather than a free-form bag, so a new one is a deliberate change to this
    contract instead of an unnoticed passenger.
    """

    measurement_id: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=48)
    target: dict = Field(default_factory=dict)
    resolution: TargetResolution
    # None means not measured. It is never coerced, and no caller may default it.
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: Unit
    basis: Basis | None = None
    method: str = Field(min_length=1, max_length=64)
    method_version: str = Field(min_length=1, max_length=16)
    # From `BRep_Tool.Tolerance` on the participating faces. A reading inside this
    # band of nominal may not be called `failed` — see `within_numerical_error`.
    numeric_error_bound: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    # Solid indices, face counts, areas. Diagnostic only, and never a target: OCCT
    # solid ordering is not stable across a boolean, so an index cannot name a part.
    diagnostic: dict = Field(default_factory=dict)
    # The second reading of a circular dimension, present only where doubling means
    # something. A wall thickness has no diametral value; a fit clearance has both.
    diametral_mm: float | None = Field(default=None, allow_inf_nan=False)

    # --- provenance, stamped by the backend, not the engine -----------------------
    #
    # The engine knows the source hash because it built from that document. It does
    # not know which revision or build row the result will land in, and it must not:
    # those are database identity, and handing database identity to the geometry
    # worker is exactly the coupling the tool-surface rule forbids.
    revision_id: str | None = None
    build_id: str | None = None
    source_hash: str | None = Field(default=None, max_length=128)
    artifact_id: str | None = None

    @field_validator("value")
    @classmethod
    def _no_value_when_unresolved(cls, v, info):
        # Enforced here rather than trusted, because the combination it forbids —
        # a number with no resolution behind it — is precisely the shape a plausible
        # wrong answer takes.
        res = info.data.get("resolution")
        if v is not None and res is not None and not res.resolved:
            raise ValueError("an unresolved target cannot carry a value")
        return v

    def within_numerical_error(self, nominal: float) -> bool:
        """Is this reading indistinguishable from ``nominal`` at the kernel's own
        precision? If so it may grade `unverified`, never `failed`."""
        if self.value is None:
            return False
        return abs(self.value - nominal) <= self.numeric_error_bound


def parse(raw) -> list[Measurement]:
    """Validate what came back from the engine.

    ``None`` and ``[]`` both mean "this build measured nothing", which is the honest
    state of every build made before this gate and of every build that asked for
    nothing. Neither is an error.

    A malformed *entry* drops that entry and keeps the rest. This is the one place
    the module is lenient, and deliberately: the alternative is that one unreadable
    record costs every good measurement beside it, turning a partial answer into no
    answer. The dropped one simply never existed, so every check that wanted it
    grades `unverified` — which is what an absent measurement has always meant.
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("measurements must be a list")
    out: list[Measurement] = []
    seen: set[str] = set()
    dropped: list[str] = []
    for item in raw[:MAX_MEASUREMENTS]:
        if not isinstance(item, dict):
            dropped.append("<not an object>")
            continue
        try:
            m = Measurement.model_validate(item)
        except Exception as e:
            # Logged, because dropping silently is how a contract mismatch between the
            # engine and this model turns into "the jar graded unverified" with nothing
            # anywhere saying why. One added field on the engine side cost every
            # measurement on every build until this line existed.
            dropped.append(f"{item.get('measurement_id') or '<unnamed>'}: {e}")
            continue
        # Ids address measurements downstream; two rows answering to one name would
        # make "which number failed" unanswerable.
        if m.measurement_id in seen:
            continue
        seen.add(m.measurement_id)
        out.append(m)
    if dropped:
        logger.warning("cad_evidence.parse dropped %d of %d measurement(s): %s",
                       len(dropped), len(raw), "; ".join(dropped[:4]))
    return out


def stamp(measurements: list[Measurement], *, revision_id: str | None,
          build_id: str | None, artifact_id: str | None = None) -> list[dict]:
    """Bind each record to the rows it was taken on and return storable dicts.

    ``source_hash`` is *not* stamped here — the engine already knows it, because it
    is the hash of the document the engine actually built. Overwriting it from the
    backend's copy would defeat the whole point of the display check below: the two
    values would agree by construction rather than by evidence.
    """
    out = []
    for m in measurements:
        d = m.model_dump()
        d["revision_id"] = str(revision_id) if revision_id else None
        d["build_id"] = str(build_id) if build_id else None
        if artifact_id and not d.get("artifact_id"):
            d["artifact_id"] = str(artifact_id)
        out.append(d)
    return out


def visible_for(stored, source_hash: str | None) -> list[dict]:
    """The subset safe to show under a revision whose canonical source hash is
    ``source_hash``.

    A record with no hash is dropped, not trusted. It came from an engine that did
    not report one, so nothing can confirm which geometry it describes — and an
    unconfirmable number rendered beside a part reads exactly like a confirmed one.
    """
    if not stored or not source_hash:
        return []
    return [d for d in stored
            if isinstance(d, dict) and d.get("source_hash") == source_hash]


def by_id(stored) -> dict[str, dict]:
    """Index for the grader, which asks for measurements by name."""
    return {d["measurement_id"]: d for d in (stored or [])
            if isinstance(d, dict) and d.get("measurement_id")}
