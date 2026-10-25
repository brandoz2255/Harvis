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
    # first words that merely start with a question word must not read as questions
    "Isometric pixel art: generate an image of a castle",
    "Howl's castle: make a picture of it at night",
    "Dogs are great, make a picture of a dog",
    "Whoever you are, generate an image of a fox",
    # common subject lead-ins beyond "of"
    "create an image featuring a red panda",
    "generate an image with a fox in it",
    "make a picture that shows a lighthouse at dusk",
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


@pytest.mark.parametrize("text", [
    "Isometric pixel art: generate an image of a castle",
    "Dogs are great, make a picture of a dog",
    "create an image featuring a red panda",
    "generate an image with a fox in it",
])
def test_flag_off_notice_for_lead_in_phrasings(monkeypatch, text):
    monkeypatch.setattr(harvis_image, "_image_gen_enabled", lambda: False)
    out = _run(_body(text))
    assert out is not None and "disabled" in out


def test_real_questions_still_fall_through():
    assert not image_bridge._is_image_request("How do I make an image of a fox?")
    assert not image_bridge._is_image_request("Is it possible to generate an image of a fox")
    assert not image_bridge._is_image_request("Do you make a picture of a fox?")
    assert not image_bridge._is_image_request("Can I generate an image of a fox with python")


def test_draw_prompt_keeps_only_the_subject():
    assert image_bridge._extract_prompt("create an image featuring a red panda") == "a red panda"
    assert image_bridge._extract_prompt("generate an image with a fox in it") == "a fox in it"
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


@pytest.mark.parametrize("text", [
    # tech words in the SUBJECT must not veto a real request
    "generate an image of a fox in the style of a 90s app icon",
    "generate an image of a futuristic city with a network of flying cars",
    "make a picture of an old library with rows of books",
    "create an image of a snake with a python pattern on its back",
    "make a painting of a fox on canvas",
    # "way to" and "how about" outside a how-to question
    "make an image of a fox on its way to school",
    "how about you generate an image of a fox",
    "draw a tree",
    # a journey or a destination is a subject, not a how-to
    "generate an image of a signpost showing the way to the beach",
    "generate an image of a runner going all the way to the moon",
    # style phrases and ordinary nouns are pictures, not technical subjects
    "generate an image of a fox in the style of a circuit board",
    "generate an image of a city skyline with charts on billboards",
    "draw a fox in the style of a schematic",
    "generate an image of a circuit board",
    "generate an image of a castle with gothic architecture",
    "generate an image of a shipping container at sunset",
    # ordinary asks, including ones that share a word with a library name
    "make an image of a cat with a hat",
    "create a picture of a sunset featuring mountains",
    "draw a dragon",
    "make an image of a cat with a pillow",
    "create an image with a turtle on a beach",
    "generate a picture with a cat on a sofa",
    "create an image with a dragon flying over mountains",
    "generate an image of the moon in pillow clouds",
    "generate an image with two cats and a dog",
    "make a picture with her dog on a beach",
])
def test_tech_or_way_words_in_the_subject_do_not_veto_a_real_request(text):
    assert image_bridge._is_image_request(text)


@pytest.mark.parametrize("text", [
    "draw a binary tree for [1,2,3]",
    "draw a state machine for the login flow",
    "draw a schematic for an arduino circuit",
    "generate an image of a binary tree",
    "make a picture of a software architecture for a shop",
    "generate an image of a fox in python",
    "create an image of a cat using matplotlib",
    # a how-to stays a how-to
    "what is the best way to generate an image of a fox",
    "is there a way to make an image of a fox in gimp",
    "tell me the best way to create an image of a cat",
    # other how-to phrasings built on "way(s) to"
    "3 ways to make an image of a fox",
    "other ways to generate a picture of a cat",
    "quickest way to make an image of a fox?",
    "any way to generate an image of a fox?",
    "the cheapest way to generate an image of a fox",
    "a better way to make an image of a fox",
    # infrastructure and software subjects are for the model, not the image lane
    "generate an image of the kubernetes cluster architecture",
    "generate an image of the architecture of my flask api",
    "generate an image of a microservices architecture",
    "create an image of the network topology for my lab",
    "create a picture of my docker setup",
    "make an image of the ci pipeline",
    "draw a kubernetes cluster",
    "draw a docker compose setup",
    "draw an api gateway",
    "draw a react component tree",
    "draw an html page",
    "draw a flask app structure",
    "draw a network topology",
    "draw a microservice architecture",
    "draw an architecture for my app",
    "create an image with buildah for my flask app",
    # imaging-library and module coding requests are tooling, not subjects
    "create an image with opencv that draws a red rectangle",
    "generate an image with numpy and save it as a png",
    "make a picture with the turtle module",
    "create a photo with transparent background using pillow",
    "draw a house with the turtle library",
    "create an image with PIL showing a histogram of pixel values",
    "make an image of my app's home screen",
    "make a picture with rust and the image crate",
    "create an image with pygame",
    "make an image with tkinter",
    "create an image with a red background using cv2",
    # a bare "with <tool>" is no subject, whatever the tool is called
    "create an image with java",
    "make an image with pytorch",
    "make an image with tensorflow",
    "make a picture with keras",
    "create an image with C++",
    "create a picture with c#",
    "create a picture with golang",
    "create an image with rust",
    "generate an image with seaborn",
    "generate an image with plotly",
    "generate an image with ggplot2",
    "generate an image with p5.js",
    "create an image with three.js",
    "create an image with javafx",
    "create an image with java swing",
    "create an image with imageio",
    "create an image with scikit-image",
    "create an image with node canvas",
    "make an image with go's image package",
    "generate an image with diffusers",
    "create an image with bash",
    "create an image with a gradient in java",
    "generate an image with processing",
    "create an image with sharp in node",
    "create a picture using pillow",
    "create an image of a gradient in pillow",
    "generate a picture with a for loop",
    "make an image with a GAN in pytorch",
])
def test_technical_drawings_and_how_to_questions_still_reach_the_model(text):
    assert not image_bridge._is_image_request(text)


def test_flag_off_notice_and_fallthrough_follow_the_new_matching(monkeypatch):
    monkeypatch.setattr(harvis_image, "_image_gen_enabled", lambda: False)
    out = _run(_body("generate an image of a fox in the style of a 90s app icon"))
    assert out is not None and "disabled" in out
    assert _run(_body("draw a binary tree for [1,2,3]")) is None
    assert _run(_body("draw a state machine for the login flow")) is None


def test_notice_docstring_no_longer_claims_explicit_only():
    assert "explicit trigger only" not in (image_bridge._notice_sse.__doc__ or "")
