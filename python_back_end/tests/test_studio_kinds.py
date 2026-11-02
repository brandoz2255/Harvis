"""Studio data tables, slide decks, custom report prompts and the Brief / Critique podcast presets."""
import asyncio
import csv
import io
import json
import os
import sys
import uuid

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import podcast_script as ps  # noqa: E402
from onb_compat import studio_generate as sg  # noqa: E402
from onb_compat import studio_kinds as sk  # noqa: E402
from onb_compat import studio_routes  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# -- data table ---------------------------------------------------------------------------

def test_table_with_rows_as_objects_lists_and_a_source_column():
    t = sk.normalize_data_table({
        "title": "Planets",
        "columns": ["Name", {"name": "Moons"}, "Source"],
        "rows": [
            {"cells": ["Mars", "2", "Atlas"], "source": ""},
            ["Earth", "1", "Guide"],
            {"Name": "Venus", "Moons": "0", "Source": "Atlas"},
            {"cells": ["", "", ""]},
        ],
    })
    assert t["columns"] == ["Name", "Moons"]
    assert [(r["cells"], r["source"]) for r in t["rows"]] == [
        (["Mars", "2"], "Atlas"), (["Earth", "1"], "Guide"), (["Venus", "0"], "Atlas")
    ]


def test_table_pads_short_rows_and_caps_size():
    rows = [{"cells": ["a"], "source": "s"} for _ in range(200)]
    t = sk.normalize_data_table({"columns": [f"c{i}" for i in range(30)], "rows": rows})
    assert len(t["columns"]) == sk.MAX_COLUMNS and len(t["rows"]) == sk.MAX_ROWS
    assert all(len(r["cells"]) == sk.MAX_COLUMNS for r in t["rows"])


@pytest.mark.parametrize("bad", [None, [], {}, {"columns": ["only"], "rows": [["x"]]},
                                 {"columns": ["a", "b"], "rows": []}, {"columns": "ab", "rows": [["x", "y"]]}])
def test_unusable_table_is_empty(bad):
    assert sk.normalize_data_table(bad) == {}


def test_csv_puts_source_last_defuses_formulas_and_has_a_bom():
    content = {"columns": ["Name", "Note"], "rows": [
        {"cells": ["=HYPERLINK(\"http://x\")", "café, bar"], "source": "Doc A"},
        {"cells": ["-1", "plain"], "source": ""},
    ]}
    raw = sk.table_to_csv(content)
    assert raw.startswith("﻿".encode("utf-8"))
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0] == ["Name", "Note", "Source"]
    assert rows[1][0].startswith("'=") and rows[1][1] == "café, bar" and rows[1][2] == "Doc A"
    assert rows[2][0] == "'-1"


def test_csv_without_any_source_has_no_source_column():
    raw = sk.table_to_csv({"columns": ["A", "B"], "rows": [{"cells": ["1", "2"], "source": ""}]})
    assert list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))[0] == ["A", "B"]


def test_safe_filename():
    name = sk.safe_filename("../../etc/passwd\r\nX", "x", "csv")
    assert "/" not in name and "\n" not in name and name.endswith(".csv")
    assert sk.safe_filename("", "data-table", "csv") == "data-table.csv"


# -- slides -------------------------------------------------------------------------------

def test_slides_are_normalised_from_loose_shapes():
    d = sk.normalize_slides({"title": "Deck", "slides": [
        {"title": "One", "bullets": ["- a", "* b", "", "c\x00d"], "notes": "say it", "source": "Doc"},
        {"heading": "Two", "points": "First point. Second point."},
        {"title": "No bullets", "bullets": []},
        "junk",
    ]})
    assert d["title"] == "Deck"
    assert d["slides"][0]["bullets"] == ["a", "b", "c d"] and d["slides"][0]["source"] == "Doc"
    assert d["slides"][1]["title"] == "Two" and d["slides"][1]["bullets"] == ["First point.", "Second point."]
    assert len(d["slides"]) == 2


def test_slides_caps_and_empty():
    many = [{"title": f"S{i}", "bullets": [f"b{j}" for j in range(20)]} for i in range(50)]
    d = sk.normalize_slides({"slides": many})
    assert len(d["slides"]) == sk.MAX_SLIDES and len(d["slides"][0]["bullets"]) == sk.MAX_BULLETS
    assert d["title"] == "S0"
    assert sk.normalize_slides({"slides": []}) == {} and sk.normalize_slides("x") == {}


def test_pptx_is_a_real_deck_with_notes():
    pptx = pytest.importorskip("pptx")
    deck = sk.normalize_slides({"title": "My deck", "slides": [
        {"title": "Intro", "bullets": ["alpha", "beta"], "notes": "Speak slowly", "source": "Doc A"},
        {"title": "Wrap", "bullets": ["done"]},
    ]})
    raw = sk.slides_to_pptx(deck)
    assert raw[:2] == b"PK"
    prs = pptx.Presentation(io.BytesIO(raw))
    assert len(prs.slides) == 3  # cover + two
    assert prs.slides[0].shapes.title.text == "My deck"
    assert prs.slides[1].shapes.title.text == "Intro"
    assert [p.text for p in prs.slides[1].placeholders[1].text_frame.paragraphs] == ["alpha", "beta"]
    assert "Speak slowly" in prs.slides[1].notes_slide.notes_text_frame.text
    assert "Source: Doc A" in prs.slides[1].notes_slide.notes_text_frame.text


def test_pptx_refuses_an_empty_deck():
    pytest.importorskip("pptx")
    with pytest.raises(ValueError):
        sk.slides_to_pptx({"title": "x", "slides": []})


# -- generate_structured ------------------------------------------------------------------

def test_generate_data_table_and_slides_use_their_prompts(monkeypatch):
    seen = []

    async def fake_ask(prompt, schema, model, url, temperature):
        seen.append((prompt, schema))
        if "data table" in prompt:
            return json.dumps({"columns": ["A", "B"], "rows": [{"cells": ["1", "2"], "source": "S"}]})
        return json.dumps({"title": "D", "slides": [{"title": "T", "bullets": ["x"]}]})

    monkeypatch.setattr(sg, "_ask", fake_ask)
    title, table = run(sg.generate_structured("data_table", "=== SOURCE: S ===\nbody", "m", "http://x"))
    assert title.startswith("Data table") and table["rows"][0]["source"] == "S"
    assert seen[0][1] is sk.DATA_TABLE_SCHEMA and "body" in seen[0][0]
    title, deck = run(sg.generate_structured("slides", "text", "m", "http://x"))
    assert title == "Slides · D" and deck["slides"][0]["bullets"] == ["x"]


def test_malformed_json_retries_then_gives_a_plain_error(monkeypatch):
    replies = ["not json at all", json.dumps({"columns": ["A", "B"], "rows": [["1", "2"]]})]

    async def fake_ask(*a, **k):
        return replies.pop(0)

    monkeypatch.setattr(sg, "_ask", fake_ask)
    _, table = run(sg.generate_structured("data_table", "x", "m", "http://x"))
    assert table["rows"][0]["cells"] == ["1", "2"]

    async def never(*a, **k):
        return "{}"

    monkeypatch.setattr(sg, "_ask", never)
    with pytest.raises(sg.StudioError) as err:
        run(sg.generate_structured("slides", "x", "tiny:1b", "http://x"))
    assert "slide deck" in str(err.value) and "tiny:1b" in str(err.value)


def test_instruction_and_language_reach_the_prompt_before_the_cut_content(monkeypatch):
    seen = []

    async def fake_ask(prompt, *a):
        seen.append(prompt)
        return json.dumps({"questions": [{"q": "Q?", "options": ["a", "b"], "answer": 0}]})

    monkeypatch.setattr(sg, "_ask", fake_ask)
    run(sg.generate_structured(
        "quiz", "x" * 20000, "m", "http://x", language="Answer in French.", instruction="Only about {content} risks"
    ))
    p = seen[0]
    assert "USER INSTRUCTION: Only about  risks" in p and "Answer in French." in p
    assert p.index("USER INSTRUCTION") < p.index("xxxx") and p.index("Answer in French.") < p.index("xxxx")
    assert p.count("x") < 20000 + 200  # content still cut


def test_structured_kinds_include_the_new_ones():
    assert {"quiz", "flashcards", "mindmap", "data_table", "slides"} <= set(sg.STRUCTURED_KINDS)


# -- custom prompt ------------------------------------------------------------------------

def test_instruction_is_cleaned_and_capped():
    assert sk.clean_instruction(None) == "" and sk.clean_instruction(5) == ""
    assert sk.clean_instruction("  focus\x00 on cost {content} ") == "focus  on cost"
    assert len(sk.clean_instruction("a" * 9000)) == sk.MAX_INSTRUCTION_CHARS


def test_apply_instruction_goes_before_content_slot_and_is_a_noop_when_empty():
    base = "Write a briefing.\n\n{content}"
    assert sk.apply_instruction(base, "") == base
    out = sk.apply_instruction(base, "for a CFO")
    assert out.endswith("{content}") and "USER INSTRUCTION: for a CFO" in out
    assert out.count("{content}") == 1


# -- podcast presets ----------------------------------------------------------------------

def test_brief_is_capped_at_three_minutes_and_critique_is_not():
    assert ps.style_minutes("brief", 20) == 3 and ps.style_minutes("brief", 2) == 2
    assert ps.style_minutes("critique", 12) == 12 and ps.style_minutes("debate", 99) == ps.MAX_MINUTES


def test_presets_have_style_notes_and_listing():
    assert {p["id"] for p in ps.PRESET_STYLES} == {"brief", "critique"}
    assert all(p["id"] in ps.STYLE_NOTES for p in ps.PRESET_STYLES)


def test_preset_prompts_carry_their_rules():
    kw = dict(title="T", names=["Alex", "Sam"], part=1, parts=1, words=300, material="m", previous=[])
    critique = ps.build_prompt(style="critique", **kw)
    assert "weaknesses" in critique and "outside facts" in critique and ".." not in critique.split("MATERIAL")[0]
    assert "bite-sized" in ps.build_prompt(style="brief", **kw)
    assert "ONLY facts from the material" in critique


def test_generate_script_for_brief_asks_for_the_short_length():
    asked = []

    async def call(prompt, budget):
        asked.append(prompt)
        return json.dumps({"outline": "o", "transcript": [{"speaker": "Alex", "dialogue": "Hi there."}]})

    out = run(ps.generate_script("body", title="T", style="brief", minutes=15, names=["Alex", "Sam"], call=call))
    assert out["target_words"] == 3 * ps.WORDS_PER_MINUTE and len(asked) == 1


# -- routes -------------------------------------------------------------------------------

NB, ART, OWNER, OTHER = uuid.uuid4(), uuid.uuid4(), 1, 2


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    async def fetchrow(self, sql, art, nb, user):
        self.queries.append((sql, art, nb, user))
        for r in self.rows:
            if r["id"] == art and r["nb"] == nb and r["user"] == user:
                return r
        return None


class FakePool:
    def __init__(self, rows):
        self.conn = FakeConn(rows)

    def acquire(self):
        pool = self

        class Ctx:
            async def __aenter__(self_inner):
                return pool.conn

            async def __aexit__(self_inner, *a):
                return False

        return Ctx()


class FakeManager:
    def __init__(self, rows):
        self.db_pool = FakePool(rows)


def _client(rows, user_id=OWNER):
    router = APIRouter(prefix="/onb-api")

    async def auth():
        return {"id": user_id}

    manager = FakeManager(rows)

    async def get_manager():
        return manager

    studio_routes.register(router, auth=auth, get_manager=get_manager, clean_uuid=uuid.UUID)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), manager


def _row(kind, content, art=ART, nb=NB, user=OWNER, title="T"):
    return {"id": art, "nb": nb, "user": user, "kind": kind, "title": title, "content": content}


TABLE = {"title": "Planets", "columns": ["Name"], "rows": [{"cells": ["Mars"], "source": "Atlas"}]}
DECK = {"title": "Deck", "slides": [{"title": "One", "bullets": ["a"], "notes": "n", "source": ""}]}


def test_csv_route_streams_an_attachment_and_is_owner_scoped():
    client, manager = _client([_row("data_table", TABLE)])
    r = client.get(f"/onb-api/notebooks/{NB}/artifacts/{ART}/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="Planets.csv"' in r.headers["content-disposition"]
    assert "Mars,Atlas" in r.content.decode("utf-8-sig")
    sql, _, _, user = manager.db_pool.conn.queries[0]
    assert "user_id = $3" in sql and "notebook_id = $2" in sql and user == OWNER


def test_another_user_or_notebook_gets_404():
    client, _ = _client([_row("data_table", TABLE)], user_id=OTHER)
    assert client.get(f"/onb-api/notebooks/{NB}/artifacts/{ART}/export.csv").status_code == 404
    client, _ = _client([_row("data_table", TABLE)])
    assert client.get(f"/onb-api/notebooks/{uuid.uuid4()}/artifacts/{ART}/export.csv").status_code == 404


def test_wrong_kind_and_bad_ids():
    client, _ = _client([_row("quiz", {"questions": []})])
    assert client.get(f"/onb-api/notebooks/{NB}/artifacts/{ART}/export.csv").status_code == 400
    assert client.get(f"/onb-api/notebooks/{NB}/artifacts/{ART}/export.pptx").status_code == 400
    assert client.get(f"/onb-api/notebooks/nope/artifacts/{ART}/export.pptx").status_code == 400


def test_content_stored_as_json_text_is_read():
    client, _ = _client([_row("data_table", json.dumps(TABLE))])
    assert client.get(f"/onb-api/notebooks/{NB}/artifacts/{ART}/export.csv").status_code == 200


def test_pptx_route_streams_a_deck():
    pytest.importorskip("pptx")
    client, _ = _client([_row("slides", DECK)])
    r = client.get(f"/onb-api/notebooks/{NB}/artifacts/{ART}/export.pptx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert r.headers["content-type"] == studio_routes.PPTX_TYPE
    assert 'filename="Deck.pptx"' in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_pptx_route_empty_deck_is_409():
    pytest.importorskip("pptx")
    client, _ = _client([_row("slides", {"title": "x", "slides": []})])
    assert client.get(f"/onb-api/notebooks/{NB}/artifacts/{ART}/export.pptx").status_code == 409


def test_migration_file_widens_only_and_names_both_constraints():
    sql = open(sk._MIGRATION, encoding="utf-8").read().upper()
    assert "'DATA_TABLE'" in sql and "'SLIDES'" in sql and "'BRIEF'" in sql and "'CRITIQUE'" in sql
    for word in ("TRUNCATE", "DROP TABLE", "DROP COLUMN", "DELETE FROM"):
        assert word not in sql
    # every old kind and style is still allowed
    for old in ("'QUIZ'", "'FLASHCARDS'", "'STUDY_GUIDE'", "'BRIEFING'", "'FAQ'", "'TIMELINE'", "'MINDMAP'",
                "'CONVERSATIONAL'", "'INTERVIEW'", "'EDUCATIONAL'", "'DEBATE'", "'STORYTELLING'"):
        assert old in sql


def test_ensure_constraints_runs_once_and_survives_failure():
    calls = []

    class Conn:
        async def execute(self, sql):
            calls.append(sql)

    class Pool:
        def acquire(self):
            class Ctx:
                async def __aenter__(s):
                    return Conn()

                async def __aexit__(s, *a):
                    return False

            return Ctx()

    sk._migrated = False
    run(sk.ensure_kind_constraints(Pool()))
    run(sk.ensure_kind_constraints(Pool()))
    assert len(calls) == 1 and "onb_notebook_artifacts_kind_check" in calls[0]

    class Broken:
        def acquire(self):
            raise RuntimeError("db down")

    sk._migrated = False
    run(sk.ensure_kind_constraints(Broken()))  # must not raise
    assert sk._migrated is False
    sk._migrated = False


# -- the real onb_compat router: dispatch and registration ---------------------------------

def _onb_app(monkeypatch, captured):
    from onb_compat import podcasts as onb_podcasts
    from onb_compat import router as mod

    class Mgr:
        db_pool = None

        async def get_notebook(self, nb, user):
            return object()

        async def get_chat_config(self, nb, user):
            return {"output_language": "French"}

    async def content(*a, **k):
        return "=== SOURCE: Atlas ===\nMars has two moons."

    async def model(*a, **k):
        return "gemma:test"

    async def structured(kind, text, model, url, **kw):
        captured["structured"] = (kind, kw)
        return "T", {"columns": ["A", "B"], "rows": []}

    async def llm(prompt, text, model, **kw):
        captured["markdown_prompt"] = prompt
        return "## Overview\n" + "A real briefing paragraph that is long enough to pass the check. " * 2

    async def persist(manager, nb, user, kind, title, fmt, content_obj, model):
        captured["persisted"] = (kind, fmt)
        return {"kind": kind}

    async def ensure(pool):
        captured["ensured"] = True

    monkeypatch.setattr(onb_podcasts, "_resolve_notebook_content", content)
    monkeypatch.setattr(mod, "_person_model", model)
    monkeypatch.setattr(mod, "generate_structured", structured)
    monkeypatch.setattr(mod, "_run_transformation_llm", llm)
    monkeypatch.setattr(mod, "_persist_and_return_artifact", persist)
    monkeypatch.setattr(mod._studio_kinds, "ensure_kind_constraints", ensure)
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[mod.get_current_user_from_request] = lambda: {"id": 1}
    app.dependency_overrides[mod.get_notebook_manager] = lambda: Mgr()
    return TestClient(app), mod


def test_export_routes_are_registered_on_the_onb_router():
    from onb_compat import router as mod
    paths = {r.path for r in mod.router.routes}
    assert "/onb-api/notebooks/{notebook_id}/artifacts/{artifact_id}/export.csv" in paths
    assert "/onb-api/notebooks/{notebook_id}/artifacts/{artifact_id}/export.pptx" in paths


@pytest.mark.parametrize("kind", ["data_table", "slides"])
def test_generate_route_accepts_new_kinds_with_language_instruction_and_migration(monkeypatch, kind):
    captured = {}
    client, _ = _onb_app(monkeypatch, captured)
    r = client.post(f"/onb-api/notebooks/{NB}/generate", json={"kind": kind, "prompt": "only the moons"})
    assert r.status_code == 200, r.text
    k, kw = captured["structured"]
    assert k == kind and kw["instruction"] == "only the moons" and "French" in kw["language"]
    assert captured["persisted"] == (kind, "json") and captured["ensured"] is True


def test_generate_route_quiz_does_not_run_the_migration(monkeypatch):
    captured = {}
    client, _ = _onb_app(monkeypatch, captured)
    assert client.post(f"/onb-api/notebooks/{NB}/generate", json={"kind": "quiz"}).status_code == 200
    assert "ensured" not in captured


def test_custom_report_prompt_reaches_the_markdown_generator(monkeypatch):
    captured = {}
    client, _ = _onb_app(monkeypatch, captured)
    r = client.post(f"/onb-api/notebooks/{NB}/generate", json={"kind": "briefing", "prompt": "write it for a CFO"})
    assert r.status_code == 200, r.text
    assert "USER INSTRUCTION: write it for a CFO" in captured["markdown_prompt"]
    assert captured["markdown_prompt"].endswith("{content}")
    captured.clear()
    client.post(f"/onb-api/notebooks/{NB}/generate", json={"kind": "briefing"})
    assert "USER INSTRUCTION" not in captured["markdown_prompt"]


def test_unknown_kind_is_still_rejected(monkeypatch):
    client, _ = _onb_app(monkeypatch, {})
    assert client.post(f"/onb-api/notebooks/{NB}/generate", json={"kind": "infographic"}).status_code == 400
    assert client.post(f"/onb-api/notebooks/{NB}/generate", json={"kind": "video"}).status_code == 400


def test_every_podcast_surface_lists_brief_and_critique():
    """The notebook picker, the notebook-scoped enum and the /onb-api episode profiles must agree."""
    import asyncio
    from notebooks.models import PodcastStyle
    from notebooks.router import list_podcast_styles
    from onb_compat import podcasts

    assert {"brief", "critique"} <= {s.value for s in PodcastStyle}
    listed = {s["id"] for s in asyncio.run(list_podcast_styles())["styles"]}
    assert {"conversational", "brief", "critique"} <= listed

    async def fake_default():
        return "m"
    import onb_compat.router as onb_router
    orig = onb_router._default_chat_model
    onb_router._default_chat_model = fake_default
    try:
        profiles = {p["id"] for p in asyncio.run(podcasts._build_episode_profiles())}
    finally:
        onb_router._default_chat_model = orig
    assert {"conversational", "brief", "critique"} <= profiles


def test_schema_sql_allows_the_new_studio_kinds_and_podcast_styles():
    import os
    sql = open(os.path.join(os.path.dirname(__file__), "..", "notebooks", "schema.sql")).read()
    assert sql.count("'data_table', 'slides'") == 2  # CREATE TABLE and the startup widening block
    assert "'brief', 'critique'" in sql
