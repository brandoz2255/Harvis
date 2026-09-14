"""Schema-migration fixtures for CadIR.

``tests/fixtures/cadir/v0_N/templates.json`` is a frozen snapshot of what schema 0.N
means: the normalized form of each template after parsing, its resolved defaults, and
the canonical source hash those produce. These tests fail whenever that meaning
changes.

That is the point, and the failures are not noise:

* A hash change means two revisions that *were* the same build are now different ones,
  or worse, two that were different now collide. ``cad_revisions`` compares on this,
  so a silent change re-identifies stored history.
* A normalized-form change means a document written against the frozen version no
  longer round-trips through its parser — a field gained a default, lost one, or
  changed name.

Either is a schema migration, and the correct response is to bump
:data:`cadir.SCHEMA_VERSION`, add a ``v0_N+1`` fixture directory beside the old one, and
write the upgrade path — never to regenerate an existing file so the test goes green. A
regenerated fixture proves only that today's code agrees with itself.

**That is what happened at 0.2** (Gate 7D). ``component`` on every operation and
``intersect`` in ``mode`` are additive and change nothing about what a 0.1 document
means, but ``model_dump(exclude_defaults=False)`` writes the new key into operations
that never mention it, so every frozen form and every frozen hash moved. ``v0_1`` was
left exactly as it was and ``v0_2`` was added.

What each older fixture is still asserted on, and why the list is shorter:

* **It still parses, and keeps its declared version.** This is the migration property
  that actually matters — a document stored under 0.1 must still load, and loading must
  not silently rewrite what its author wrote.
* **Its resolved defaults are unchanged.** Parameter resolution is version-independent;
  if a 0.1 document's defaults moved, the values a stored revision was built from moved
  with them.
* **Not its hash, and not its normalized form.** Both are properties of the *current*
  schema: the hash mixes in the live ``SCHEMA_VERSION`` by design, so no 0.1 hash is
  reproducible once the constant moves. Freezing it again would only assert that the
  constant has not changed, which is not what a migration test is for.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from cadir import SCHEMA_VERSION, TEMPLATES, canonical_source_hash, parse
from cadir.budget import resolve_params

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "cadir"

CURRENT_DIR = FIXTURES / f"v{SCHEMA_VERSION.replace('.', '_')}"
CURRENT = json.loads((CURRENT_DIR / "templates.json").read_text())

# Every fixture directory, current one included, as (version, snapshot) pairs.
ALL_VERSIONS = sorted(
    (d.name.removeprefix("v").replace("_", "."), json.loads((d / "templates.json").read_text()))
    for d in FIXTURES.iterdir() if d.is_dir() and (d / "templates.json").exists()
)
OLDER = [(v, snap) for v, snap in ALL_VERSIONS if v != SCHEMA_VERSION]

_CURRENT_CASES = sorted(CURRENT)
_OLDER_CASES = [(v, name) for v, snap in OLDER for name in sorted(snap)]
_BY_VERSION = dict(ALL_VERSIONS)


def test_the_current_version_has_a_fixture_directory():
    """A bump that forgets its snapshot leaves the new meaning unpinned, and the
    ``v0_1``-era tests below would keep passing while nothing watched 0.2."""
    assert CURRENT_DIR.is_dir(), f"no fixture directory for schema {SCHEMA_VERSION}"


def test_the_fixture_covers_every_template():
    """A new template that ships without a fixture entry is unpinned — its identity
    could change between releases and nothing would notice."""
    assert set(CURRENT) == set(TEMPLATES)


@pytest.mark.parametrize("name", _CURRENT_CASES)
def test_the_normalized_document_is_unchanged(name):
    doc = parse(TEMPLATES[name])
    assert doc.model_dump(mode="json", exclude_defaults=False) == CURRENT[name]["document"]


@pytest.mark.parametrize("name", _CURRENT_CASES)
def test_the_resolved_defaults_are_unchanged(name):
    doc = parse(TEMPLATES[name])
    assert resolve_params(doc, {}) == CURRENT[name]["default_params"]


@pytest.mark.parametrize("name", _CURRENT_CASES)
def test_the_canonical_hash_is_unchanged(name):
    """The identity ``cad_revisions`` is compared on. If this moves, stored revisions
    stop matching the documents that produced them."""
    doc = parse(TEMPLATES[name])
    resolved = resolve_params(doc, {})
    assert canonical_source_hash(doc, resolved) == CURRENT[name]["canonical_source_hash"]


@pytest.mark.parametrize("version,name", _OLDER_CASES)
def test_a_document_frozen_under_an_older_schema_still_parses(version, name):
    """The migration property that matters most: a document *stored* under an older
    version must still load, and must still say it is that version. Parsing the frozen
    dump rather than the live template is what distinguishes "the schema still accepts
    its own output" from "the schema still accepts the literal we happen to ship"."""
    frozen = _BY_VERSION[version][name]["document"]
    doc = parse(frozen)
    assert doc.schema_version == version


@pytest.mark.parametrize("version,name", _OLDER_CASES)
def test_an_older_documents_defaults_still_resolve_the_same(version, name):
    """Parameter resolution does not depend on the schema version, so a 0.1 document's
    defaults must still be the values it was originally built from."""
    frozen = _BY_VERSION[version]
    doc = parse(frozen[name]["document"])
    assert resolve_params(doc, {}) == frozen[name]["default_params"]
