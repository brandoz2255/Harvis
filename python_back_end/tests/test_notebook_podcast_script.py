"""Podcast scripts: right length, one voice per speaker, unreadable output is an error."""
import asyncio
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import podcast_audio as pa  # noqa: E402
from notebooks import podcast_script as ps  # noqa: E402

NAMES = ["Alex", "Sam"]


def run(coro):
    return asyncio.run(coro)


def test_speaker_labels_collapse_onto_the_requested_cast():
    turns = [
        {"speaker": "Host", "dialogue": "Welcome."},
        {"speaker": "Speaker 2", "dialogue": "Thanks for having me."},
        {"speaker": "ALEX", "dialogue": "Let's begin."},
        {"speaker": "**Sam**:", "dialogue": "Sam: Sure."},
        {"speaker": "Alex (laughing)", "dialogue": "Right."},
        {"speaker": "Guest", "dialogue": "Yes."},
    ]
    out = ps.normalize_turns(turns, NAMES)
    assert [t["speaker"] for t in out] == ["Alex", "Sam", "Alex", "Sam", "Alex", "Sam"]
    assert out[3]["dialogue"] == "Sure."


def test_extra_labels_never_exceed_the_cast_and_alternate():
    turns = [{"speaker": f"Person {chr(65 + i)}", "dialogue": f"line {i}"} for i in range(6)]
    out = ps.normalize_turns(turns, NAMES)
    assert {t["speaker"] for t in out} == set(NAMES)


def test_stage_directions_and_empty_lines_are_dropped():
    out = ps.normalize_turns(
        [{"speaker": "Alex", "dialogue": "*laughs* Hello [music fades] there."}, {"speaker": "Sam", "dialogue": "  "}], NAMES
    )
    assert out == [{"speaker": "Alex", "dialogue": "Hello there."}]


def test_one_voice_per_speaker_across_label_spelling():
    order: dict = {}
    assert pa.voice_for("Alex", order) == pa.voice_for(" alex ", order)
    assert len(order) == 1


def test_cast_is_one_to_four_names():
    assert ps.speaker_names(None, 2) == ["Alex", "Sam"]
    assert len(ps.speaker_names(None, 9)) == 4
    assert ps.speaker_names([{"name": "Mara"}, {"name": "mara"}, {"name": "Jo"}], 2) == ["Mara", "Jo"]
    assert ps.speaker_names(None, 1) == ["Alex"]


def test_length_follows_the_request():
    assert ps.target_words(10) == 1500
    assert sum(ps.plan_parts(1500)) == 1500 and len(ps.plan_parts(1500)) == 3
    assert ps.plan_parts(150) == [150]
    assert len(ps.plan_parts(ps.target_words(30))) == ps.MAX_PARTS
    assert ps.clamp_minutes(500) == 30 and ps.clamp_minutes(0) == 5


def fake_model(words_per_reply, prompts):
    async def call(prompt, budget):
        prompts.append((prompt, budget))
        line = " ".join(["word"] * (words_per_reply // 4))
        return json.dumps(
            {
                "outline": "part outline",
                "transcript": [{"speaker": "Host" if i % 2 == 0 else "Guest", "dialogue": line} for i in range(4)],
            }
        )

    return call


def test_ten_minute_request_is_written_in_parts_and_close_to_length():
    prompts = []
    out = run(
        ps.generate_script("source text " * 200, title="T", style="conversational", minutes=10, names=NAMES, call=fake_model(500, prompts))
    )
    assert len(prompts) == 3
    assert "greet" in prompts[0][0].lower() and "final part" in prompts[2][0].lower()
    assert "The script so far ends with" in prompts[1][0]
    assert out["target_words"] == 1500 and out["words"] >= 1200
    assert {t["speaker"] for t in out["transcript"]} == set(NAMES)


def test_short_model_replies_are_made_up_in_later_parts():
    prompts = []
    run(ps.generate_script("x " * 400, title="T", style="educational", minutes=10, names=NAMES, call=fake_model(200, prompts)))
    asked = [int(p[0].split("Write about ")[1].split(" spoken")[0]) for p in prompts]
    assert asked[1] > asked[0] // 1 - 1 and asked[2] >= asked[1]


@pytest.mark.parametrize("reply", ["", "Sure! Here is your podcast about cells.", "{not json", '{"transcript": []}', '{"transcript": [1,2]}'])
def test_unreadable_reply_is_an_error_not_a_finished_podcast(reply):
    async def call(prompt, budget):
        return reply

    with pytest.raises(ps.PodcastScriptError) as err:
        run(ps.generate_script("text", title="T", style="x", minutes=2, names=NAMES, call=call))
    assert str(err.value)


def test_fenced_json_and_bare_lists_are_accepted():
    outline, turns = ps.parse_turns('```json\n{"outline": "o", "transcript": [{"speaker": "A", "dialogue": "hi"}]}\n```')
    assert outline == "o" and turns[0]["dialogue"] == "hi"
    _, turns = ps.parse_turns('[{"speaker": "A", "text": "hello"}]')
    assert turns


def test_first_bad_reply_is_retried_once():
    replies = ["garbage", json.dumps({"transcript": [{"speaker": "Alex", "dialogue": "Hello there everyone."}]})]

    async def call(prompt, budget):
        return replies.pop(0)

    out = run(ps.generate_script("text", title="T", style="x", minutes=1, names=NAMES, call=call))
    assert out["transcript"][0]["speaker"] == "Alex"


# --- audio failure reaches the caller as an error with a reason -----------------------


def test_unreachable_speech_service_raises_with_a_reason(monkeypatch):
    monkeypatch.delenv("TTS_URL", raising=False)

    async def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(pa, "synthesize", boom)
    with pytest.raises(pa.PodcastAudioError) as err:
        run(pa.make_audio([{"speaker": "Alex", "text": "hi"}]))
    assert "could not be reached" in str(err.value)


def test_speech_http_error_is_named(monkeypatch):
    monkeypatch.delenv("TTS_URL", raising=False)

    async def bad(*a, **k):
        req = httpx.Request("POST", "http://x/v1/audio/speech")
        raise httpx.HTTPStatusError("x", request=req, response=httpx.Response(503, request=req))

    monkeypatch.setattr(pa, "synthesize", bad)
    with pytest.raises(pa.PodcastAudioError) as err:
        run(pa.make_audio([{"speaker": "Alex", "text": "hi"}]))
    assert "HTTP 503" in str(err.value)


def test_script_failure_becomes_a_saved_error_result(monkeypatch):
    from types import SimpleNamespace

    from notebooks import router as nr

    async def failing(content, **k):
        raise ps.PodcastScriptError("model says no")

    monkeypatch.setattr(ps, "generate_script", failing)
    req = SimpleNamespace(custom_speakers=None, speakers=2, title="T", style="conversational", duration_minutes=5, model="m")
    result = run(nr._generate_podcast_with_ollama("content", req, SimpleNamespace(warning=lambda *a, **k: None)))
    assert result["status"] == "error" and result["error"] == "model says no" and result["transcript"] == []
