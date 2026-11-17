"""owui_compat.vision_bridge: a text-only model gets image descriptions instead of images."""

import asyncio

from owui_compat import vision_bridge as vb

NEMO = "nemotron:30b"
HOSTS = [
    {"base": "http://pair", "tags": {NEMO: 1, "qwen:27b": 20}, "loaded": set(),
     "caps": {NEMO: None, "qwen:27b": None}},          # a router that reports nothing
    {"base": "http://local", "tags": {NEMO: 1, "gemma:e4b": 5, "qwen:27b": 20}, "loaded": {"qwen:27b"},
     "caps": {NEMO: ["completion", "tools"], "gemma:e4b": ["completion", "vision"],
              "qwen:27b": ["completion", "vision"]}},
]


def _body(*urls):
    return [{"role": "user", "content": [{"type": "text", "text": "what is this?"}]
             + [{"type": "image_url", "image_url": {"url": u}} for u in urls]}]


def test_capabilities_come_from_whichever_host_reports_them():
    assert vb.can_see(NEMO, HOSTS) is False
    assert vb.can_see("qwen:27b", HOSTS) is True
    assert vb.can_see("unknown:1b", HOSTS) is None   # unknown → images are left alone


def test_vision_model_choice():
    assert vb.pick_vision(HOSTS) == ("http://local", "qwen:27b")          # already in memory
    hosts = [{**HOSTS[1], "loaded": set()}]
    assert vb.pick_vision(hosts) == ("http://local", "gemma:e4b")         # else the smallest
    assert vb.pick_vision(hosts, "qwen:27b") == ("http://local", "qwen:27b")  # HARVIS_VISION_MODEL
    assert vb.pick_vision([HOSTS[0]]) is None


def test_images_become_descriptions_and_are_described_once():
    vb._cache.clear()
    calls = []

    async def describe(b64, mime):
        calls.append((b64, mime))
        return "a red error dialog"

    for _ in range(2):  # the same image again next turn comes from the cache
        msgs = _body("data:image/png;base64,QUJD")
        n = asyncio.run(vb.replace_images(msgs, NEMO, describe, "gemma:e4b"))
        assert n == 1 and not vb.has_images(msgs)
        assert "a red error dialog" in msgs[0]["content"][1]["text"]
    assert calls == [("QUJD", "image/png")]


def test_failures_and_remote_links_become_notes_not_errors():
    vb._cache.clear()

    async def boom(b64, mime):
        raise RuntimeError("model down")

    msgs = _body("data:image/png;base64,WFla", "https://example.com/cat.png")
    assert asyncio.run(vb.replace_images(msgs, NEMO, boom, "gemma:e4b")) == 0
    texts = [p["text"] for p in msgs[0]["content"][1:]]
    assert "could not describe" in texts[0] and "not fetched" in texts[1]
    assert not vb.has_images(msgs)


def test_no_vision_model_installed_says_so():
    msgs = _body("data:image/png;base64,QUJD")
    asyncio.run(vb.replace_images(msgs, NEMO, None, None))
    assert "no image-reading model is installed" in msgs[0]["content"][1]["text"]


def test_bridge_leaves_a_seeing_or_unknown_model_alone(monkeypatch):
    async def hosts():
        return HOSTS
    monkeypatch.setattr(vb, "_hosts", hosts)
    for model in ("qwen:27b", "unknown:1b"):
        body = {"model": model, "messages": _body("data:image/png;base64,QUJD")}
        asyncio.run(vb.bridge(body))
        assert vb.has_images(body["messages"])
