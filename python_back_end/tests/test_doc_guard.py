"""The document guard: a refusal to make a file is followed by the real thing.

Fake SSE streams stand in for the model and a fake lane stands in for the second ask, so
nothing here calls a model. What matters is when the lane is called, what body it gets,
and that the trailer lands before [DONE].
"""

import asyncio
import json
import os
import sys

import pytest
from fastapi.responses import JSONResponse, StreamingResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import chat_abilities, chat_completion, doc_guard  # noqa: E402
from owui_compat.doc_bridge import DOC_PROMPT_MARKER, doc_system_prompt  # noqa: E402

REFUSAL = "I do not have a visible tool for creating presentation files, but I can write an outline."
DECK_ANSWER = "Here is your deck.\n\n````harvis-doc\n---\nkind: deck\ntitle: Dogs\n---\n# Dogs\n````"


def _sse(*pieces):
    out = []
    for p in pieces:
        out.append(("data: " + json.dumps({"choices": [{"delta": {"content": p}}]}) + "\n\n").encode())
    out.append(b"data: [DONE]\n\n")
    return out


def _stream(chunks):
    async def gen():
        for c in chunks:
            yield c

    return StreamingResponse(gen(), media_type="text/event-stream")


def _completion(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _body(user="make me a slide show", extra_systems=()):
    body = {"stream": True, "messages": [{"role": "system", "content": "be nice"}]
            + [{"role": "system", "content": s} for s in extra_systems]
            + [{"role": "user", "content": user}]}
    chat_completion._inject_block_vocabulary(body)
    chat_abilities.inject_abilities(body)
    return body


class Lane:
    def __init__(self, answer=DECK_ANSWER, delay=0.0, raises=None):
        self.bodies = []
        self.answer, self.delay, self.raises = answer, delay, raises

    async def __call__(self, body):
        self.bodies.append(body)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise self.raises
        return _completion(self.answer)


def _drain(response):
    async def go():
        return [c async for c in response.body_iterator]

    return b"".join(asyncio.run(go()))


def _texts(raw):
    out = []
    for line in raw.split(b"\n"):
        if line.startswith(b"data:") and b"[DONE]" not in line:
            out.append(json.loads(line[5:])["choices"][0]["delta"]["content"])
    return out


def _guard(response, body, lane, user_text=None):
    return asyncio.run(doc_guard.append_doc_guard(None, response, body, lane, user_text=user_text))


def test_a_refusal_triggers_one_document_retry_with_the_trailer_before_done():
    body, lane = _body(), Lane()
    chunks = _sse("I do not have a visible tool ", "for creating presentation files.")
    out = _drain(_guard(_stream(chunks), body, lane))

    assert len(lane.bodies) == 1
    retry = lane.bodies[0]
    msgs = retry["messages"]
    assert DOC_PROMPT_MARKER in msgs[-2]["content"] and msgs[-2]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "make me a slide show"}
    assert all(chat_completion.BLOCK_VOCABULARY not in m["content"] for m in msgs if m["role"] == "system")
    assert all(chat_abilities.NOTE_HEADING not in m["content"] for m in msgs if m["role"] == "system")
    assert retry["stream"] is False

    assert _texts(out)[-1] == "\n\n---\n\n" + DECK_ANSWER
    assert out.count(b"[DONE]") == 1 and out.rstrip().endswith(b"data: [DONE]")  # trailer first, [DONE] last
    assert _texts(out)[:2] == ["I do not have a visible tool ", "for creating presentation files."]


def test_the_original_body_is_not_touched_by_the_retry():
    body, lane = _body(), Lane()
    before = json.dumps(body, sort_keys=True)
    _drain(_guard(_stream(_sse(REFUSAL)), body, lane))
    assert json.dumps(body, sort_keys=True) == before


def test_a_normal_answer_passes_through_unchanged_and_the_lane_is_not_called():
    body, lane = _body(), Lane()
    chunks = _sse("Sure, here you go.", " Anything else?")
    out = _drain(_guard(_stream(chunks), body, lane))
    assert lane.bodies == []
    assert out == b"".join(chunks)


def test_an_answer_that_already_carries_a_document_is_not_re_asked():
    body, lane = _body(), Lane()
    answer = "I can't attach a file here, so make a deck from this.\n````harvis-doc\n---\nkind: deck\n---\n# A\n````"
    _drain(_guard(_stream(_sse(answer)), body, lane))
    assert lane.bodies == []


def test_a_turn_that_already_has_a_document_prompt_is_never_guarded():
    body = _body(extra_systems=[doc_system_prompt("deck")])
    lane = Lane()
    response = _stream(_sse(REFUSAL))
    assert _guard(response, body, lane) is response
    assert lane.bodies == []


def test_words_that_are_not_about_a_file_are_never_guarded():
    lane = Lane()
    response = _stream(_sse("I cannot create a time machine."))
    assert _guard(response, _body("can you build me a time machine"), lane) is response
    assert lane.bodies == []


def test_summarising_a_document_is_not_a_request_to_make_one():
    lane = Lane()
    response = _stream(_sse("I don't have access to create a summary of the document."))
    assert _guard(response, _body("summarize this document"), lane) is response


def test_an_outline_offer_with_no_document_triggers_the_retry():
    body, lane = _body("my teacher wants slides, can u help"), Lane()
    out = _drain(_guard(_stream(_sse("Sure! Here is an outline you can paste into PowerPoint:\n1. Intro")), body, lane))
    assert len(lane.bodies) == 1
    assert "---" in _texts(out)[-1]


def test_a_lane_timeout_yields_no_trailer(monkeypatch):
    monkeypatch.setattr(doc_guard, "_BUDGET_S", 0.05)
    body, lane = _body(), Lane(delay=1.0)
    chunks = _sse(REFUSAL)
    out = _drain(_guard(_stream(chunks), body, lane))
    assert out == b"".join(chunks)


def test_a_lane_error_yields_no_trailer():
    body, lane = _body(), Lane(raises=RuntimeError("model down"))
    chunks = _sse(REFUSAL)
    assert _drain(_guard(_stream(chunks), body, lane)) == b"".join(chunks)


def test_an_empty_retry_answer_adds_nothing():
    body, lane = _body(), Lane(answer="  ")
    chunks = _sse(REFUSAL)
    assert _drain(_guard(_stream(chunks), body, lane)) == b"".join(chunks)


def test_client_disconnect_does_not_await_in_finally():
    body, lane = _body(), Lane()
    response = _guard(_stream(_sse(REFUSAL)), body, lane)

    async def go():
        it = response.body_iterator
        first = await it.__anext__()  # the client reads one frame, then goes away
        await it.aclose()
        return first

    asyncio.run(go())
    assert lane.bodies == []


def test_a_stream_with_no_done_gets_no_trailer():
    body, lane = _body(), Lane()
    chunks = _sse(REFUSAL)[:-1]
    assert _drain(_guard(_stream(chunks), body, lane)) == b"".join(chunks)
    assert lane.bodies == []


def test_a_done_split_into_its_own_chunk_after_other_frames_is_still_caught():
    body, lane = _body(), Lane()
    chunks = _sse(REFUSAL)
    merged = [chunks[0] + chunks[1]]  # frame and [DONE] arrive in one chunk
    out = _drain(_guard(_stream(merged), body, lane))
    assert len(lane.bodies) == 1 and out.rstrip().endswith(b"data: [DONE]")


def test_a_non_streamed_reply_gets_the_trailer_appended():
    body, lane = _body(), Lane()
    body["stream"] = False
    out = _guard(_completion(REFUSAL), body, lane)
    assert out["choices"][0]["message"]["content"] == REFUSAL + "\n\n---\n\n" + DECK_ANSWER
    assert len(lane.bodies) == 1


def test_a_json_response_reply_gets_the_trailer_appended():
    body, lane = _body(), Lane()
    out = _guard(JSONResponse(_completion(REFUSAL)), body, lane)
    assert json.loads(out.body)["choices"][0]["message"]["content"].endswith(DECK_ANSWER)


def test_the_switch_turns_it_off(monkeypatch):
    monkeypatch.setenv("HARVIS_DOC_GUARD", "0")
    response = _stream(_sse(REFUSAL))
    assert _guard(response, _body(), Lane()) is response


def test_user_text_argument_wins_over_a_message_polluted_by_injection():
    body = _body("what's up")
    body["messages"][-1]["content"] += "\n\nWeb results: a slide deck report"
    lane = Lane()
    out = _drain(_guard(_stream(_sse(REFUSAL)), body, lane, user_text="make me a slide show"))
    assert len(lane.bodies) == 1 and b"---" in out


def test_without_a_user_text_argument_the_last_message_is_read():
    lane = Lane()
    _drain(_guard(_stream(_sse(REFUSAL)), _body("make me a pdf"), lane))
    assert len(lane.bodies) == 1


def test_a_body_with_no_user_message_is_left_alone():
    response = _stream(_sse(REFUSAL))
    assert _guard(response, {"messages": [{"role": "system", "content": "x"}]}, Lane()) is response


@pytest.mark.parametrize("text,kind", [
    ("make me a slide show", "deck"), ("my teacher wants slides", "deck"), ("get me a pdf", "pdf"),
    ("I need an excel sheet for my budget", "sheet"), ("write a report on dogs", "doc"),
    ("export a pdf of the spreadsheet", "pdf"), ("hello", "doc"),
    ("how do I convert a word doc to pdf", "pdf"), ("convert this pdf into slides", "deck"),
    ("can you turn this report into a pdf", "pdf"), ("export my spreadsheet as a csv", "sheet"),
    ("make me a deck about word of mouth", "deck"), ("convert it to nothing useful, I want a report", "doc"),
    ("my teacher wants slides on how to turn a report into a pdf, can u help", "deck"),
    ("my class needs a presentation on how to convert word files to pdf", "deck"),
    ("help me with my presentation on converting excel to pdf", "deck"),
    ("my boss wants a report on how we can turn our spreadsheet into slides", "doc"),
    ("I have a word doc, can you convert it to pdf", "pdf"),
    ("report on how we can turn our spreadsheet into slides", "doc"),
    ("I have a word doc, how do I convert it to pdf", "pdf"),
    ("my excel sheet, what's the easiest way to export it to pdf", "pdf"),
    ("my powerpoint on the civil war is done, can you export it as a pdf", "pdf"),
    ("here is my report about dogs, turn it into slides", "deck"),
])
def test_kind_follows_the_first_file_word(text, kind):
    assert doc_guard.kind_from_text(text) == kind


@pytest.mark.parametrize("answer", [
    "I cannot create PowerPoint files.", "I can’t make a pptx for you.", "I'm unable to generate a spreadsheet.",
    "Sorry, I don't have the ability to produce a PDF.", "I have no visible tool to build a deck.",
    "I can't actually create or export files like documents.",
    "I can't create PDF files, but here's a Python script you can run:\n```python\nfrom reportlab.pdfgen import canvas\n```",
    "I'm unable to generate PowerPoint files directly. You can use python-pptx:\n```python\nfrom pptx import Presentation\n```",
])
def test_refusals_that_fire(answer):
    assert doc_guard.should_fire(answer)


@pytest.mark.parametrize("answer", [
    "Here is your deck about dogs.", "Sure, I will write that now.", "", "I cannot browse the web.",
    "I can't create a deck.\n````harvis-doc\n---\nkind: deck\n---\n# x\n````",
])
def test_answers_that_do_not_fire(answer):
    assert not doc_guard.should_fire(answer)


def test_run_chat_completion_wires_the_note_and_the_guard_on_the_native_lane(monkeypatch):
    """Through the real run_chat_completion, with only the model replaced by a fake."""
    from types import SimpleNamespace

    import workspace.model_proxy as model_proxy

    calls = []

    async def fake_model(request, body):
        calls.append(body)
        first = len(calls) == 1
        text = "I cannot create PowerPoint files." if first else DECK_ANSWER
        if not body.get("stream", True):
            return _completion(text)
        return _stream(_sse(text))

    monkeypatch.setattr(model_proxy, "execute_chat_completion", fake_model)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=None)), state=SimpleNamespace())
    body = {"model": "gemma4:e4b", "stream": True,
            "messages": [{"role": "user", "content": "my teacher wants slides, can u help"}]}

    async def go():
        response = await chat_completion.run_chat_completion(request, body, user_id=None)
        return b"".join([c async for c in response.body_iterator])

    out = asyncio.run(go())
    assert len(calls) == 2
    first_system = calls[0]["messages"][0]["content"]
    assert first_system.startswith("## Ground rules") and chat_abilities.NOTE_HEADING in first_system
    retry_systems = [m["content"] for m in calls[1]["messages"] if m["role"] == "system"]
    assert any(DOC_PROMPT_MARKER in s for s in retry_systems)
    assert not any(chat_abilities.NOTE_HEADING in s or chat_completion.BLOCK_VOCABULARY in s for s in retry_systems)
    assert _texts(out)[-1].endswith(DECK_ANSWER) and out.rstrip().endswith(b"data: [DONE]")


@pytest.mark.parametrize("answer,closer", [
    ("no fences at all", ""),
    ("```\ncode\n```", ""),
    ("```python\nprint(1)", "```"),
    ("````\nouter\n```\ninner\n```", "````"),
    ("~~~\nx", "~~~"),
])
def test_open_fence_closer(answer, closer):
    assert doc_guard.open_fence_closer(answer) == closer


def test_a_refusal_that_ends_inside_a_fence_closes_it_before_the_trailer():
    """The transcript reads fences line by line: an open one would swallow the document as code."""
    body, lane = _body(), Lane()
    out = _drain(_guard(_stream(_sse("I cannot create a deck. Outline:\n\n```\n1. Intro")), body, lane))
    assert _texts(out)[-1] == "\n```\n\n---\n\n" + DECK_ANSWER


def test_a_cut_off_reply_is_not_given_a_guessed_closer(monkeypatch):
    monkeypatch.setattr(doc_guard, "_SCAN_CHARS", 60)
    body, lane = _body(), Lane()
    long_reply = "I cannot create a deck. ```\n" + "x" * 200
    out = _drain(_guard(_stream(_sse(long_reply)), body, lane))
    assert _texts(out)[-1] == "\n\n---\n\n" + DECK_ANSWER


# The reviewer's false positives: ordinary coding and how-to turns must never hold the
# stream open for a second generation.
@pytest.mark.parametrize("user,answer", [
    ("write a python script to convert a csv to json",
     "Here's a Python script that reads the CSV and writes JSON:\n```python\nimport csv\n```"),
    ("how do I get this table into excel?", "Select the table, copy it, and paste it into Excel."),
    ("how do i structure my report for history class",
     "Here's a structure that works well for most history reports: intro, body, conclusion."),
    ("why can't pandas export my excel file", "Pandas cannot export the xlsx file because openpyxl is not installed."),
    ("can you summarize this document", "I don't have access to create a summary of the document."),
    ("please summarize this pdf", "I'm unable to create a summary of the pdf without the file."),
    ("what does this word mean, can you help", "I cannot create a definition of the word without context."),
    # Review round 2: a refusal that crosses a sentence, a file word used as a modifier,
    # and "slide-by-slide" describing rehearsal rather than an outline.
    ("I need a pdf reader for linux",
     "I can't install software for you. Evince and Okular are good choices; to create PDF files you can use LibreOffice."),
    ("need help with my presentation skills, I get nervous",
     "Here's a slide-by-slide approach to rehearsing: practice each slide out loud, then time yourself."),
    ("I want to learn excel formulas",
     "I can't build a spreadsheet for you to practice in here, but here's an outline of formulas to learn"),
])
def test_ordinary_turns_never_fire_the_guard(user, answer):
    lane = Lane()
    response = _stream(_sse(answer))
    assert _guard(response, _body(user), lane) is response
    assert lane.bodies == []


def test_a_code_answer_to_a_real_file_request_is_not_re_asked_as_an_outline_offer():
    lane = Lane()
    answer = "Here's a Python script that builds the deck:\n```python\nprint(1)\n```"
    out = _drain(_guard(_stream(_sse(answer)), _body("make me a slide show"), lane))
    assert lane.bodies == [] and b"---" not in out


@pytest.mark.parametrize("user", [
    "I need a pdf reader for linux", "need help with my presentation skills, I get nervous",
    "I want to learn excel formulas", "I need a pdf editor", "help with my excel skills",
])
def test_a_file_word_used_as_a_modifier_is_not_an_ask(user):
    assert not doc_guard.looks_like_file_request(user)


@pytest.mark.parametrize("answer", [
    "I can't install software for you. To create PDF files you can use LibreOffice.",
    "I can't do that, but you could create a pdf file in LibreOffice.",
    "Here's a slide-by-slide approach to rehearsing your talk.",
])
def test_a_clause_boundary_or_a_but_stops_a_refusal_match(answer):
    assert not doc_guard.should_fire(answer)


@pytest.mark.parametrize("answer", [
    "I cannot create a PDF file here.",
    "I can't directly generate .pptx files, sorry.",
    "Here's a slide-by-slide outline you can use.",
    "Here is a slide-by-slide breakdown of the talk.",
])
def test_real_refusals_and_outline_offers_still_fire(answer):
    assert doc_guard.should_fire(answer)


def test_group_room_turns_are_left_alone():
    lane = Lane()
    user = '[Group chat: "lab"] You are @hermes ...\n  You (user): make a deck about dogs\n'
    response = _stream(_sse("I can't create presentation files in this room."))
    assert _guard(response, _body(user), lane) is response
    assert lane.bodies == []


@pytest.mark.parametrize("user", [
    "can you summarize this document", "please summarize this pdf", "what does this word mean, can you help",
    "write a python script to convert a csv to json", "how do I get this table into excel?",
    "why can't pandas export my excel file", "how do i structure my report for history class",
])
def test_the_file_gate_needs_a_verb_that_governs_the_file_word(user):
    assert not doc_guard.looks_like_file_request(user)


@pytest.mark.parametrize("user", [
    "make me a slide show", "my teacher wants slides, can u help", "I need an excel sheet for my budget",
    "write a report on dogs", "turn these notes into slides", "convert this to a pdf", "slides on dogs",
    "get me a pdf of this", "help me with my presentation", "slides pls",
])
def test_the_file_gate_still_passes_real_requests(user):
    assert doc_guard.looks_like_file_request(user)


@pytest.mark.parametrize("answer", [
    "Here's a Python script that reads the CSV:\n```python\nprint(1)\n```",
    "Here's a structure that works well for most history reports.",
    "Select the table, copy it, and paste it into Excel.",
    "Pandas cannot export the xlsx file because openpyxl is not installed.",
    "I don't have access to create a summary of the document.",
    "Here's a script you can run:\n```bash\nls\n```",
    "Here is an outline of the code:\n```python\nx = 1\n```",
])
def test_answers_about_code_and_how_to_do_not_fire(answer):
    assert not doc_guard.should_fire(answer)


@pytest.mark.parametrize("answer", [
    "Here is a slide-by-slide outline.", "Here's a speaker script for your talk.",
    "Here is an outline. Copy it into PowerPoint.", "I'll give you a presentation template.",
])
def test_document_offers_still_fire(answer):
    assert doc_guard.should_fire(answer)


def test_a_refusal_line_inside_a_code_answer_does_not_fire():
    howto = ("Run this:\n```bash\npandoc notes.md -o notes.pdf\n```\n"
             "I can't run commands here, so I can't generate the PDF for you.")
    assert not doc_guard.should_fire(howto)
    assert doc_guard.should_fire("I can't run commands here, so I can't generate the PDF for you.")
    lane = Lane()
    out = _drain(_guard(_stream(_sse(howto)), _body("make me a pdf from my notes"), lane))
    assert lane.bodies == [] and b"---" not in out


def test_the_fire_log_has_the_kind_reason_and_length_but_not_the_users_words(caplog):
    user = "make me a slide show about my secret project orchid"
    lane = Lane()
    with caplog.at_level("INFO", logger="owui_compat.doc_guard"):
        _drain(_guard(_stream(_sse(REFUSAL)), _body(user), lane))
    fired = [r.getMessage() for r in caplog.records if "doc_guard fired" in r.getMessage()]
    assert len(fired) == 1
    assert "kind=deck" in fired[0] and "reason=refusal" in fired[0] and f"message_chars={len(user)}" in fired[0]
    assert "orchid" not in caplog.text and "slide show" not in caplog.text
