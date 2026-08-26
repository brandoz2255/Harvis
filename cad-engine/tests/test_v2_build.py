"""Gate 3: ``/cad/v2/build`` — caller-chosen formats, raw bytes, frozen v1.

Two things are actually being tested, and the second is the one worth the file:

* the multipart framing survives a round trip, checked against **v1's** bytes for
  the same input rather than against the sha the same server just computed. A
  server that framed the body wrong and hashed the wrong bytes would agree with
  itself all day.
* ``/cad/execute`` still answers exactly as it did. v2 exists so v1 never has to
  change, and a test that only exercises v2 would not notice v1 breaking.

Run inside the container:  docker exec harvis-cad python -m pytest tests -q
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient

import exporters
import server

client = TestClient(server.app, raise_server_exceptions=False)

GOLDEN_PARAMS = {"arm_len_mm": 90}


# --- a deliberately independent reader ------------------------------------------
# Written against RFC 7578 rather than reusing anything the server imports, because
# a parser sharing code with the framer proves only that they are consistent.

def parse_multipart(content_type: str, body: bytes) -> tuple[dict, dict[str, bytes]]:
    assert content_type.startswith("multipart/form-data; boundary="), content_type
    boundary = content_type.split("boundary=", 1)[1].strip()
    sep = b"--" + boundary.encode()

    assert body.startswith(sep + b"\r\n"), "body does not open on the boundary"
    assert body.endswith(sep + b"--\r\n"), "body does not close on the terminator"

    parts: dict[str, bytes] = {}
    headers_by_name: dict[str, dict[str, str]] = {}
    # Strip the terminator, then split. The leading empty chunk is the preamble.
    for chunk in body[: -len(sep) - 4].split(sep + b"\r\n"):
        if not chunk:
            continue
        head, _, payload = chunk.partition(b"\r\n\r\n")
        headers = {}
        for line in head.decode("utf-8").split("\r\n"):
            if not line:
                continue
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        disp = headers["content-disposition"]
        name = disp.split('name="', 1)[1].split('"', 1)[0]
        assert payload.endswith(b"\r\n"), f"part {name} is not CRLF-terminated"
        parts[name] = payload[:-2]
        headers_by_name[name] = headers

    for name, blob in parts.items():
        if name == "result":
            continue
        declared = headers_by_name[name].get("content-length")
        assert declared is not None, f"part {name} declares no length"
        assert int(declared) == len(blob), f"part {name} length header disagrees"

    result = json.loads(parts.pop("result"))
    return result, parts


_STEP_DATE = re.compile(rb"'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d'")


def _undated(step: bytes) -> bytes:
    return _STEP_DATE.sub(b"'<ts>'", step)


def build_v2(**body):
    r = client.post("/cad/v2/build", json={"recipe": "helmet_hanger_v1", **body})
    return r


def _assert_invalid(r):
    """Gate 1A answers every schema failure as a structured 400, never a bare 422."""
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error_code"] == "invalid_request"


def ok_v2(**body):
    r = build_v2(**body)
    assert r.status_code == 200, r.text
    return parse_multipart(r.headers["content-type"], r.content)


# --- the round trip --------------------------------------------------------------

def test_default_formats_match_v1_bytes():
    """The framed STL and STEP are the same bytes v1 base64s for the same input."""
    v1 = client.post("/cad/execute",
                     json={"recipe": "helmet_hanger_v1", "params": GOLDEN_PARAMS})
    assert v1.status_code == 200, v1.text
    v1 = v1.json()

    result, files = ok_v2(params=GOLDEN_PARAMS)

    assert set(files) == {"stl", "step"}
    assert files["stl"] == base64.b64decode(v1["stl_b64"])
    # STEP only after normalising its header: it embeds a wall-clock timestamp at
    # one-second resolution, so two correct builds differ whenever they straddle a
    # second boundary. That is the Gate 2 finding, not a framing fault.
    assert _undated(files["step"]) == _undated(base64.b64decode(v1["step_b64"]))
    assert result["ok"] is True
    assert result["meta"] == v1["meta"]


def test_artifact_refs_describe_the_parts():
    result, files = ok_v2(params=GOLDEN_PARAMS)
    refs = {a["format"]: a for a in result["artifacts"]}
    assert set(refs) == set(files)
    for fmt, blob in files.items():
        assert refs[fmt]["size_bytes"] == len(blob)
        assert refs[fmt]["sha256"] == hashlib.sha256(blob).hexdigest()
        assert refs[fmt]["media_type"] == exporters.MEDIA_TYPES[fmt]


def test_nosniff_on_the_response():
    r = build_v2(params=GOLDEN_PARAMS)
    assert r.headers["x-content-type-options"] == "nosniff"


# --- format selection ------------------------------------------------------------

def test_caller_chooses_formats():
    """STL is always *built* — the mesh report needs it — but only sent if asked."""
    result, files = ok_v2(params=GOLDEN_PARAMS, formats=["glb", "3mf"])
    assert set(files) == {"glb", "3mf"}
    assert result["validation"]["mesh"]["triangle_count"] > 0
    assert files["glb"][:4] == b"glTF"
    assert files["3mf"][:2] == b"PK"


def test_single_format():
    _result, files = ok_v2(params=GOLDEN_PARAMS, formats=["step"])
    assert set(files) == {"step"}
    assert files["step"].startswith(b"ISO-10303-21;")


def test_duplicates_are_deduped_not_exported_twice():
    _result, files = ok_v2(params=GOLDEN_PARAMS, formats=["stl", "stl", "step"])
    assert set(files) == {"stl", "step"}


def test_every_declared_format_round_trips():
    result, files = ok_v2(params=GOLDEN_PARAMS, formats=list(exporters.FORMATS))
    assert set(files) == set(exporters.FORMATS)
    assert all(a["size_bytes"] > 0 for a in result["artifacts"])


def test_unknown_format_is_a_400():
    r = build_v2(params=GOLDEN_PARAMS, formats=["dwg"])
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "unknown_format"


def test_empty_format_list_is_rejected():
    _assert_invalid(build_v2(params=GOLDEN_PARAMS, formats=[]))


# --- the deadline can only be shortened ------------------------------------------

def test_caller_may_shorten_the_deadline():
    _result, files = ok_v2(params=GOLDEN_PARAMS, deadline_s=15.0)
    assert files


def test_caller_may_not_lengthen_it():
    """Unclamped, this field would invert engine < client < nginx and strand work."""
    import runner
    _assert_invalid(build_v2(params=GOLDEN_PARAMS, deadline_s=runner.DEADLINE_S + 1))


def test_zero_deadline_is_rejected():
    _assert_invalid(build_v2(params=GOLDEN_PARAMS, deadline_s=0))


# --- v2 inherits every Gate 1A/2 refusal ------------------------------------------

def test_unknown_recipe():
    r = client.post("/cad/v2/build", json={"recipe": "nope"})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "unknown_recipe"


def test_nan_is_refused_at_parse_time():
    r = client.post("/cad/v2/build", content=json.dumps(
        {"recipe": "helmet_hanger_v1", "params": {"arm_len_mm": float("nan")}}),
        headers={"content-type": "application/json"})
    _assert_invalid(r)


def test_unknown_key_is_refused():
    r = client.post("/cad/v2/build",
                    json={"recipe": "helmet_hanger_v1", "colour": "red"})
    _assert_invalid(r)


def test_out_of_range_param():
    r = build_v2(params={"arm_len_mm": 5000})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] in ("param_out_of_range", "unknown_param")


def test_cost_cap_still_refuses_the_oversized_brick():
    r = client.post("/cad/v2/build", json={
        "recipe": "studded_brick_v1", "params": {"studs_x": 14, "studs_y": 14}})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "too_complex"


def test_brick_round_trip():
    r = client.post("/cad/v2/build", json={
        "recipe": "studded_brick_v1", "params": {"studs_x": 4, "studs_y": 2},
        "formats": ["stl", "glb"]})
    assert r.status_code == 200, r.text
    result, files = parse_multipart(r.headers["content-type"], r.content)
    assert set(files) == {"stl", "glb"}
    assert result["validation"]["solid_count"] == 1
    assert result["validation"]["brep_valid"] is True


# --- v1 is frozen -----------------------------------------------------------------

def test_v1_response_shape_is_unchanged():
    r = client.post("/cad/execute",
                    json={"recipe": "helmet_hanger_v1", "params": GOLDEN_PARAMS})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ok", "meta", "stl_b64", "step_b64", "params", "validation"}
    assert body["meta"]["bbox_mm"] == [96.0, 40.0, 44.0]


def test_v1_rejects_a_formats_field():
    """v1 gaining `formats` silently would be the drift v2 exists to prevent."""
    r = client.post("/cad/execute", json={
        "recipe": "helmet_hanger_v1", "params": GOLDEN_PARAMS, "formats": ["glb"]})
    _assert_invalid(r)
