"""A matched image request must get an honest reason when generation is off, never a model guessing.

The natural-language image trigger stays strict: "draw a cat" counts, ordinary mentions of an image do not,
and a deck that merely mentions a picture is not claimed by the image lane.
"""

import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from image import harvis_image, provider as image_provider  # noqa: E402
from owui_compat import image_bridge  # noqa: E402


def _body(text, **extra):
    return {"messages": [{"role": "user", "content": text}], **extra}


def _run(body):
    """Run the interceptor; return None, or the assistant text the notice carried."""
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=None)))
    user = SimpleNamespace(id=1)
    resp = asyncio.run(image_bridge.maybe_handle_image_generation(request, body, user))
    if resp is None:
        return None

    async def drain():
        return [chunk async for chunk in resp.body_iterator]

    text = ""
    for line in asyncio.run(drain()):
        line = line.strip()
        if line.startswith("data: {"):
            delta = json.loads(line[6:])["choices"][0]["delta"]
            text += delta.get("content") or ""
    return text


class _NotReady:
    id = "none"

    async def readiness(self):
        return {"ready": False, "reason": "a1111: unreachable; comfyui: unreachable"}


def test_flag_off_natural_request_says_it_is_disabled(monkeypatch):
    monkeypatch.setattr(harvis_image, "_image_gen_enabled", lambda: False)
    text = _run(_body("generate an image of a fox"))
    assert text is not None
    assert "disabled" in text
    assert "HARVIS_OWUI_IMAGE_GENERATION" in text


def test_flag_off_explicit_request_says_it_is_disabled(monkeypatch):
    monkeypatch.setattr(harvis_image, "_image_gen_enabled", lambda: False)
    text = _run(_body("hello", harvis_image_generate=True))
    assert text is not None and "disabled" in text


def test_no_ready_provider_gives_the_readiness_reason(monkeypatch):
    monkeypatch.setattr(harvis_image, "_image_gen_enabled", lambda: True)

    async def none_ready():
        return _NotReady()

    monkeypatch.setattr(image_provider, "resolve_provider", none_ready)
    text = _run(_body("make me a picture of a fox"))
    assert text is not None
    assert "isn't ready" in text
    assert "a1111: unreachable" in text


def test_not_an_image_request_still_falls_through(monkeypatch):
    monkeypatch.setattr(harvis_image, "_image_gen_enabled", lambda: False)
    assert _run(_body("explain this image to me")) is None
    assert _run(_body("create a function for photo resize")) is None


@pytest.mark.parametrize("text", [
    "draw a cat",
    "Draw me a dragon",
    "please draw an owl in a hat",
    "generate an image of a fox",
])
def test_requests_that_count(text):
    assert image_bridge._is_image_request(text)


@pytest.mark.parametrize("text", [
    "explain this image",
    "create a function for photo resize",
    "make this picture bigger",
    "search for pictures of dogs",
    "make a presentation with a picture of a cat",
    "can you draw a conclusion from this",
    "draw a diagram of the network",
    "I will draw a cat tomorrow",
    "draw a network diagram of my homelab",
    "draw a sequence diagram for login",
    "draw a UML class diagram",
    "draw a mermaid diagram of the services",
    "draw a bar chart of our monthly sales",
    "draw a pie chart of expenses",
    "draw a flow chart for the build",
    "draw a box around the button",
    "draw a circle with python turtle",
    "draw an ascii art cat",
    "how do I create an image in docker",
    "create a photo gallery website",
    "how do I render an image in React?",
    "make an image smaller in css",
    "how do I make a picture frame",
    "make a photo upload form in flask",
    "generate image thumbnails with python",
    "create a drawing app in javascript",
    "what is the best way to make art as a beginner?",
    "how to build and make an image for kubernetes",
    # the extraction and idiom senses of "draw"
    "draw an inference from the data",
    "draw a random sample of 10 rows from this csv",
    "draw a card from a standard deck",
    "draw a number between 1 and 10",
    "draw a lesson from this story",
    "draw a breath and relax",
    "draw a crowd to my event",
    "draw a salary of 50k",
    "draw a red herring",
    "draw a bath",
    # how-to questions phrased as instructions
    "tell me how to generate an image of a fox in stable diffusion",
    "show me how to make a picture of a dog in GIMP",
    "I want to learn to generate an image of a cat",
    "teach me to create an image of a house",
    "explain how to make a picture of a tree",
])
def test_requests_that_do_not_count(text):
    assert not image_bridge._is_image_request(text)


def test_draw_prompt_keeps_only_the_subject():
    assert image_bridge._extract_prompt("draw me a cat on a wall") == "a cat on a wall"
    assert image_bridge._extract_prompt("generate an image of a red fox") == "a red fox"


@pytest.mark.parametrize("text", [
    "how do I create an image in docker",
    "create a photo gallery website",
    "draw a network diagram of my homelab",
    "make an image smaller in css",
    "draw a bar chart of our monthly sales",
    "draw an inference from the data",
    "draw a random sample of 10 rows from this csv",
    "draw a card from a standard deck",
    "draw a number between 1 and 10",
    "draw a lesson from this story",
    "draw a bath",
    "tell me how to generate an image of a fox in stable diffusion",
    "show me how to make a picture of a dog in GIMP",
    "I want to learn to generate an image of a cat",
])
def test_flag_off_does_not_hijack_ordinary_chat(monkeypatch, text):
    monkeypatch.setattr(harvis_image, "_image_gen_enabled", lambda: False)
    assert _run(_body(text)) is None


@pytest.mark.parametrize("mode", ["agent", "orchestrate"])
def test_agent_and_orchestrate_skip_the_natural_language_lane(monkeypatch, mode):
    monkeypatch.setattr(harvis_image, "_image_gen_enabled", lambda: False)
    assert _run(_body("generate an image of a fox", harvis_mode=mode)) is None
    # the explicit + button still gets its honest notice
    text = _run(_body("hello", harvis_image_generate=True, harvis_mode=mode))
    assert text is not None and "disabled" in text
