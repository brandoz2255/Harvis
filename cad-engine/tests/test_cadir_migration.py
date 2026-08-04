"""Schema-migration fixtures for CadIR.

``tests/fixtures/cadir/v0_1/templates.json`` is a frozen snapshot of what schema 0.1
means: the normalized form of each template after parsing, its resolved defaults, and
the canonical source hash those produce. These tests fail whenever that meaning
changes.

That is the point, and the failures are not noise:

* A hash change means two revisions that *were* the same build are now different ones,
  or worse, two that were different now collide. ``cad_revisions`` compares on this,
  so a silent change re-identifies stored history.
* A normalized-form change means a document written against 0.1 no longer round-trips
  through 0.1's parser — a field gained a default, lost one, or changed name.

Either is a schema migration, and the correct response is to bump
:data:`cadir.SCHEMA_VERSION`, add a ``v0_2`` fixture directory beside this one, and
write the upgrade path — never to regenerate this file so the test goes green. A
regenerated fixture proves only that today's code agrees with itself.

The one legitimate reason to touch ``v0_1/templates.json`` is a *bug* in the frozen
snapshot itself, and that is a deliberate, explained change, not a refresh.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from cadir import TEMPLATES, canonical_source_hash, parse
from cadir.budget import resolve_params

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "cadir" / "v0_1" / "templates.json"

FROZEN = json.loads(FIXTURE.read_text())


def test_the_fixture_covers_every_template():
    """A new template that ships without a fixture entry is unpinned — its identity
    could change between releases and nothing would notice."""
    assert set(FROZEN) == set(TEMPLATES)


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_normalized_document_is_unchanged(name):
    doc = parse(TEMPLATES[name])
    assert doc.model_dump(mode="json", exclude_defaults=False) == FROZEN[name]["document"]


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_resolved_defaults_are_unchanged(name):
    doc = parse(TEMPLATES[name])
    assert resolve_params(doc, {}) == FROZEN[name]["default_params"]


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_canonical_hash_is_unchanged(name):
    """The identity ``cad_revisions`` is compared on. If this moves, stored revisions
    stop matching the documents that produced them."""
    doc = parse(TEMPLATES[name])
    resolved = resolve_params(doc, {})
    assert canonical_source_hash(doc, resolved) == FROZEN[name]["canonical_source_hash"]


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_frozen_document_still_parses(name):
    """The migration property that matters most: a document *stored* under 0.1 must
    still load under 0.1. Parsing the frozen dump rather than the live template is what
    distinguishes "the schema still accepts its own output" from "the schema still
    accepts the literal we happen to ship"."""
    doc = parse(FROZEN[name]["document"])
    assert doc.schema_version == "0.1"
    assert canonical_source_hash(doc, resolve_params(doc, {})) == \
        FROZEN[name]["canonical_source_hash"]
