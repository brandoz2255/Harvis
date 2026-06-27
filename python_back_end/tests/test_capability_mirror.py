"""Drift guard: the Python _PROVIDER_MIRROR + PREFERABLE_CAPS in
owui_compat/capabilities.py must stay a subset of / equal to the FRONTEND source of
truth in front_end/owui/src/lib/integrations/catalog.ts.

Self-contained: reads BOTH source files (the capabilities.py constants via `ast`,
the catalog via regex) — no heavy backend imports, so it runs anywhere Python +
the two files are present. If a file is missing / unparsable, the test SKIPS — this
is a drift guard, not a hard gate (per the Phase C1 plan).
"""

import ast
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, ".."))
CAPS = os.path.join(BACKEND, "owui_compat", "capabilities.py")
CATALOG = os.path.normpath(
    os.path.join(BACKEND, "..", "front_end", "owui", "src", "lib", "integrations", "catalog.ts")
)


def _load_py_const(name):
    if not os.path.exists(CAPS):
        pytest.skip(f"capabilities.py not found at {CAPS}")
    with open(CAPS, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    target, value = t.id, node.value
        if target == name and value is not None:
            return ast.literal_eval(value)
    pytest.skip(f"{name} not found in capabilities.py")


def _catalog_src():
    if not os.path.exists(CATALOG):
        pytest.skip(f"catalog.ts not found at {CATALOG}")
    with open(CATALOG, encoding="utf-8") as f:
        return f.read()


def _catalog_provides():
    """({id: set(provides)}, set(all ids)). Each `provides: [...]` is associated with
    the nearest preceding `id: '...'`."""
    src = _catalog_src()
    ids = [(m.start(), m.group(1)) for m in re.finditer(r"id:\s*'([^']+)'", src)]
    all_ids = {i for _, i in ids}
    provides = {}
    for m in re.finditer(r"provides:\s*\[([^\]]*)\]", src):
        prior = [i for pos, i in ids if pos < m.start()]
        if not prior:
            continue
        provides[prior[-1]] = set(re.findall(r"'([^']+)'", m.group(1)))
    return provides, all_ids


def test_mirror_ids_are_catalog_ids():
    mirror = _load_py_const("_PROVIDER_MIRROR")
    _provides, all_ids = _catalog_provides()
    missing = sorted(pid for pid in mirror if pid not in all_ids)
    assert not missing, f"mirror provider ids not in catalog.ts: {missing}"


def test_mirror_capabilities_subset_of_catalog_provides():
    mirror = _load_py_const("_PROVIDER_MIRROR")
    provides, _all = _catalog_provides()
    for pid, meta in mirror.items():
        cat = provides.get(pid)
        if cat is None:
            pytest.skip(f"no provides parsed for {pid}")
        extra = set(meta["capabilities"]) - cat
        assert not extra, f"{pid}: mirror caps {sorted(extra)} not in catalog provides {sorted(cat)}"


def test_preferable_caps_match_ts():
    caps = _load_py_const("PREFERABLE_CAPS")
    src = _catalog_src()
    m = re.search(r"PREFERABLE_CAPABILITIES\s*:[^=]*=\s*\[([^\]]*)\]", src)
    if not m:
        pytest.skip("PREFERABLE_CAPABILITIES not parsed from catalog.ts")
    ts = set(re.findall(r"'([^']+)'", m.group(1)))
    assert set(caps) == ts, f"py {sorted(caps)} != ts {sorted(ts)}"
