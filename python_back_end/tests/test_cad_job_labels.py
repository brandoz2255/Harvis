"""The caption the timeline puts on the spec step (HE-4/HE-5 fallout).

`_spec_label` is the one line a person reads to learn what Harvis thought the request
pinned down. It is composed from the extractor's `stated` map and nothing else, so it
can only ever be wrong in one direction — by knowing fewer keys than the extractor
writes. That is exactly what happened: regex/v2 writes part-scoped keys
(`body_height_mm`, `lid_cavity_depth_mm`) and the caption knew only the v1 envelope
ones, so the jar this whole tranche was built around announced that nothing in the
request could be read as a requirement, on a build that went on to measure nine.
"""

from __future__ import annotations

from owui_compat.cad_jobs import _spec_label

# The exact map `cad_designspec` + `cad_designspec_v2` stored for the plan's §6 jar
# prompt, read off the live revision row rather than invented.
JAR_STATED = {
    "coaxial": True,
    "body_base_mm": 4.0,
    "body_wall_mm": 2.5,
    "body_height_mm": 115.0,
    "separate_parts": 2,
    "fit_clearance_mm": 0.3,
    "fit_clearance_basis": "diametral",
    "lid_cavity_depth_mm": 5.5,
}


def test_the_jar_caption_names_every_dimension_the_extractor_read():
    label = _spec_label(JAR_STATED)
    assert "no dimension" not in label
    for phrase in ("115 mm tall body", "2.5 mm body wall", "4 mm body base",
                   "5.5 mm deep lid cavity", "0.3 mm diametral clearance",
                   "2 separate parts", "concentric"):
        assert phrase in label, f"{phrase!r} missing from {label!r}"


def test_the_clearance_basis_is_named_because_the_number_is_ambiguous_without_it():
    """"0.3 mm clearance" means two different gaps depending on the basis, and the
    spec recorded which one it assumed. A caption that hid that would be stating a
    number the reader cannot check."""
    assert "diametral" in _spec_label(JAR_STATED)
    assert "radial" in _spec_label({**JAR_STATED, "fit_clearance_basis": "radial"})


def test_the_v1_envelope_caption_is_unchanged():
    """HE-4 extends the extractor; it does not replace it. A recipe part still states
    its envelope the way it always did."""
    assert _spec_label({"overall_mm": [20, 40, 60]}) == "Read the request — 60 × 40 × 20 mm"
    assert _spec_label({"cube_edge_mm": 15.0}) == "Read the request — 15 mm cube"


def test_a_request_nothing_could_be_read_from_still_says_so():
    """The honest empty case has to survive: a caption that always found something
    would be inventing it."""
    assert _spec_label({}) == (
        "Read the request — no dimension in it could be read as a requirement")
