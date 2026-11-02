"""Per-source context levels: what a chat is shown for insights / full / off and for notes.

The fake pool answers only the four SQL shapes context_builder sends and applies the owner
and notebook clauses the same way the real queries do, so a query that forgets one hands a
foreign row back and a test below fails.
"""
import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notebooks import context_builder as cb  # noqa: E402
from notebooks.auto_insights import QUESTIONS_MARKER, SUMMARY_MARKER  # noqa: E402

ME, OTHER = 1, 2
NB, NB_OTHER = uuid.uuid4(), uuid.uuid4()
S1, S2, S3, S_FOREIGN, S_PENDING = (uuid.uuid4() for _ in range(5))
NOTE1, NOTE_FOREIGN = uuid.uuid4(), uuid.uuid4()


def run(coro):
    return asyncio.run(coro)


class FakeConn:
    def __init__(self, sources, insights, notes):
        self.sources, self.insights, self.notes = sources, insights, notes
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append(sql)
        if "FROM notebook_transformations" in sql:
            ids, user = args[0], args[1]
            notebook = args[2] if "t.notebook_id" in sql else None
            return [
                {"source_id": r["source_id"], "transformed_content": r["text"], "custom_prompt": r["marker"]}
                for r in self.insights  # newest first, as the query orders them
                if r["source_id"] in ids and r["user"] == user and (notebook is None or r["nb"] == notebook)
            ]
        if "FROM notebook_notes" in sql:
            ids, nb, user, cap = args
            return [
                {"id": nid, "title": n["title"], "content": n["content"][:cap]}
                for nid, n in self.notes.items() if nid in ids and n["nb"] == nb and n["user"] == user
            ]
        if "SELECT s.id, s.title, LENGTH" in sql:
            ids, nb, user, head = args
            return [
                {"id": sid, "title": s["title"], "chars": len(s["text"]), "head": s["text"][:head]}
                for sid, s in self.sources.items()
                if sid in ids and s["nb"] == nb and s["owner"] == user and s["status"] == "ready"
            ]
        if "SELECT s.id, s.content_text" in sql:
            ids, nb, user = args
            return [
                {"id": sid, "content_text": s["text"]}
                for sid, s in self.sources.items() if sid in ids and s["nb"] == nb and s["owner"] == user
            ]
        raise AssertionError(f"unexpected sql: {sql[:70]}")


def make(text_sizes=(400, 400, 400), notes=None):
    sources = {
        S1: {"nb": NB, "owner": ME, "title": "Alpha", "text": "A" * text_sizes[0], "status": "ready"},
        S2: {"nb": NB, "owner": ME, "title": "Beta", "text": "B" * text_sizes[1], "status": "ready"},
        S3: {"nb": NB, "owner": ME, "title": "Gamma", "text": "G" * text_sizes[2], "status": "ready"},
        S_FOREIGN: {"nb": NB_OTHER, "owner": OTHER, "title": "Secret", "text": "SECRET-TEXT" * 20, "status": "ready"},
        S_PENDING: {"nb": NB, "owner": ME, "title": "Pending", "text": "P" * 300, "status": "processing"},
    }
    insights = [
        {"source_id": S1, "user": ME, "nb": NB, "text": "Suggested question one?", "marker": QUESTIONS_MARKER},
        {"source_id": S1, "user": ME, "nb": NB, "text": "Key points of alpha.", "marker": "custom-x"},
        {"source_id": S1, "user": ME, "nb": NB, "text": "Dense summary of alpha.", "marker": SUMMARY_MARKER},
        {"source_id": S_FOREIGN, "user": OTHER, "nb": NB_OTHER, "text": "SECRET-INSIGHT", "marker": SUMMARY_MARKER},
    ]
    notes = notes if notes is not None else {
        NOTE1: {"nb": NB, "user": ME, "title": "My note", "content": "N" * 300},
        NOTE_FOREIGN: {"nb": NB_OTHER, "user": OTHER, "title": "Their note", "content": "SECRET-NOTE"},
    }
    return FakeConn(sources, insights, notes)


def sel(sources=None, notes=None):
    return cb.ContextSelection(
        {str(k): v for k, v in (sources or {}).items()}, {str(k): "full" for k in (notes or [])}
    )


# ── modes and selections ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("insights", "insights"), ("Insights", "insights"), ("full content", "full"), ("full", "full"),
    ("FULL_CONTENT", "full"), ("not in", "off"), ("not_in", "off"), ("off", "off"), ("none", "off"),
    ("", "off"), (None, "off"), ("nonsense", "off"),
])
def test_normalize_mode(raw, expected):
    assert cb.normalize_mode(raw) == expected


def test_not_in_is_left_out_of_a_config_selection():
    cfg = {"sources": {str(S1): "full content", str(S2): "not in", str(S3): "insights", "junk": "full"},
           "notes": {str(NOTE1): "full content", str(NOTE_FOREIGN): "not in"}}
    got = cb.selection_from_config(cfg)
    assert got.sources == {str(S1): "full", str(S3): "insights"}
    assert got.notes == {str(NOTE1): "full"}


def test_config_selection_survives_garbage():
    assert cb.selection_from_config(None).is_empty
    assert cb.selection_from_config({"sources": ["x"], "notes": 3}).is_empty


def test_payload_without_levels_means_search_everything():
    assert cb.selection_from_context(None) is None
    assert cb.selection_from_context({}) is None
    assert cb.selection_from_context({"sources": [{"id": str(S1)}], "notes": []}) is None
    assert cb.selection_from_context({"sources": [str(S1)]}) is None


def test_payload_with_levels_is_mode_aware():
    ctx = {"sources": [{"id": str(S1), "mode": "insights"}, {"id": str(S2), "mode": "full"}],
           "notes": [{"id": str(NOTE1), "mode": "full"}]}
    got = cb.selection_from_context(ctx)
    assert got.sources == {str(S1): "insights", str(S2): "full"}
    assert got.notes == {str(NOTE1): "full"}


def test_explicit_empty_selection_means_nothing_is_ticked():
    got = cb.selection_from_context({"sources": [], "notes": []})
    assert got is not None and got.is_empty


def test_selection_caps_how_many_items_it_keeps():
    ids = [uuid.uuid4() for _ in range(cb.MAX_SELECTED + 10)]
    got = cb.selection_from_config({"sources": {str(i): "full" for i in ids}})
    assert len(got.sources) == cb.MAX_SELECTED


# ── building ──────────────────────────────────────────────────────────────────

def build(conn, selection, budget=9000, user=ME, nb=NB):
    return run(cb.build_context(conn, notebook_id=nb, user_id=user, selection=selection, budget=budget))


def test_insights_mode_uses_the_dense_summary_first_and_drops_suggested_questions():
    plan = build(make(), sel({S1: "insights"}))
    assert plan.stuffed and plan.retrieve_source_ids == []
    [item] = plan.items
    assert item.kind == "insight" and item.id == str(S1)
    assert item.text.startswith("Dense summary of alpha.")
    assert "Key points of alpha." in item.text
    assert "Suggested question" not in item.text


def test_insights_mode_falls_back_to_the_start_of_the_text_without_an_insight():
    plan = build(make(text_sizes=(400, 4000, 400)), sel({S2: "insights"}))
    [item] = plan.items
    assert item.kind == "insight" and item.text == "B" * cb.INSIGHT_FALLBACK_CHARS


def test_full_sources_that_fit_are_stuffed_with_their_whole_text():
    plan = build(make(), sel({S1: "full", S2: "full"}, [NOTE1]))
    assert plan.stuffed
    kinds = [(i.kind, i.id) for i in plan.items]
    assert kinds[:2] == [("source", str(S1)), ("source", str(S2))] and kinds[2] == ("note", str(NOTE1))
    assert plan.items[0].text == "A" * 400
    assert plan.indicators()["mode"] == "stuffed"
    assert plan.source_modes == {str(S1): "full", str(S2): "full"}


def test_off_sources_are_never_read():
    conn = make()
    plan = build(conn, sel({S1: "full"}))
    assert [i.id for i in plan.items] == [str(S1)]
    assert str(S2) not in plan.source_modes


def test_sources_that_do_not_fit_are_retrieved_and_notes_and_insights_still_stuffed():
    plan = build(make(text_sizes=(8000, 8000, 400)), sel({S1: "full", S2: "full", S3: "insights"}, [NOTE1]), budget=9000)
    assert not plan.stuffed
    assert plan.retrieve_source_ids == [str(S1), str(S2)]
    assert {(i.kind, i.id) for i in plan.items} == {("insight", str(S3)), ("note", str(NOTE1))}
    ind = plan.indicators(retrieved_chars=1200)
    assert ind["mode"] == "retrieved" and set(ind["sources"]) == {str(S1), str(S2), str(S3)}
    assert ind["chars"] == sum(len(i.text) for i in plan.items) + 1200


def test_notes_go_first_when_the_small_parts_do_not_fit_either():
    plan = build(make(), sel({S1: "insights", S3: "insights"}, [NOTE1]), budget=440)
    assert not plan.stuffed
    by_id = {i.id: i for i in plan.items}
    assert by_id[str(S1)].truncated is False
    assert by_id[str(S3)].truncated is True  # the insight that crossed the limit is cut, not dropped
    assert str(NOTE1) in plan.dropped and str(NOTE1) not in by_id


def test_truncate_to_fit_keeps_priority_order_and_cuts_the_item_that_crosses_the_limit():
    items = [cb.ContextItem("note", "n", "Note", "n" * 500), cb.ContextItem("source", "s", "Src", "s" * 500)]
    kept, dropped = cb.truncate_to_fit(items, budget=cb.ContextItem("source", "s", "Src", "s" * 500).cost + 300)
    assert [i.kind for i in kept] == ["source", "note"]
    assert kept[1].truncated and kept[1].text.endswith("…") and dropped == []
    kept, dropped = cb.truncate_to_fit(items, budget=cb.ContextItem("source", "s", "Src", "s" * 500).cost + 10)
    assert [i.kind for i in kept] == ["source"] and [i.kind for i in dropped] == ["note"]


def test_another_users_source_note_and_insight_are_invisible():
    conn = make()
    plan = build(conn, sel({S_FOREIGN: "full", S1: "insights"}, [NOTE_FOREIGN]), user=ME, nb=NB)
    blob = " ".join(i.text for i in plan.items)
    assert "SECRET" not in blob
    assert [i.id for i in plan.items] == [str(S1)]
    # Same ids asked for as the OTHER user, against the wrong notebook: nothing.
    plan = build(conn, sel({S1: "full"}, [NOTE1]), user=OTHER, nb=NB)
    assert plan.empty and plan.items == []


def test_an_id_from_another_notebook_is_ignored_even_for_its_owner():
    plan = build(make(), sel({S_FOREIGN: "full"}), user=OTHER, nb=NB)
    assert plan.empty


def test_sources_still_processing_are_skipped():
    plan = build(make(), sel({S_PENDING: "full"}))
    assert plan.empty


def test_an_empty_selection_reads_nothing():
    conn = make()
    plan = build(conn, cb.ContextSelection())
    assert plan.empty and conn.calls == []


# ── the preview's counter ─────────────────────────────────────────────────────

def test_estimate_chars_follows_the_level():
    s = sel({S1: "full", S2: "insights", S3: "insights"}, [NOTE1])
    got = cb.estimate_chars(
        s, chunk_chars={str(S1): 5000, str(S2): 9000, str(S3): 100}, note_chars={str(NOTE1): 9999},
        insight_chars={str(S2): 700},
    )
    # full 5000 + saved insights 700 + short text 100 (no insight: the text itself) + note capped
    assert got == 5000 + 700 + 100 + cb.NOTE_CAP_CHARS


def test_saved_insight_chars_skips_the_question_list():
    sizes = run(cb.saved_insight_chars(make(), [str(S1)], ME))
    assert sizes == {str(S1): len(cb.insight_text([
        {"transformed_content": "Dense summary of alpha.", "custom_prompt": SUMMARY_MARKER},
        {"transformed_content": "Key points of alpha.", "custom_prompt": "custom-x"},
    ]))}


def test_saved_insight_chars_swallows_a_failing_query():
    class Boom:
        async def fetch(self, *a):
            raise RuntimeError("db down")
    assert run(cb.saved_insight_chars(Boom(), [str(S1)], ME)) == {}
