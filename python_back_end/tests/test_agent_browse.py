"""Plain chat gets the browser through the teammate door.

Four things are pinned. The detector claims a request to *drive a site* and
nothing else — it must start with a driving verb aimed at a named site or a
bare domain, or ask for the browser by name; a web search stays a web search,
a question stays a question, an install stays a sandbox job, and talk about
code that happens to mention a site or "the browser" stays chat. The bridge
launches through the explicitly chosen default assistant via
``intake.create_agent_run`` and says the runner is down only when the user
asked for the browser outright. The run never uses the teammate's standing
clearances: every sign-in, payment, send and delete on this path pauses. And
a bot with web research off never browses at all.
"""

import asyncio
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.agents import browse  # noqa: E402
from plugins.hermes_ui import chat  # noqa: E402


# ─── what counts as driving a site ───────────────────────────────────────────

BROWSE = (
    "open instagram and scroll my feed for me",
    "scroll instagram for me",
    "go to newegg and find three laptops under $800",
    "go to example.com and tell me the main heading",
    "open youtube and play lofi music",
    "browse reddit for me and summarise the top posts",
    "use the browser to check my amazon order status",
    "browse amazon for a cheap 27 inch monitor",
    "log into my gmail and see if the bank wrote back",
    "open youtube.com and play some lofi",
    "visit reddit and read r/python",
    "scroll my instagram feed",
    "use the browser to look at my canvas grades",
    "pull up ebay and watch that auction",
    "go on facebook and like my sister's post",
    "Open https://news.ycombinator.com/ and scroll the front page",
    "hey harvis, can you open instagram and scroll my feed",
    "Please go to amazon and find a usb-c hub",
    "open it in the browser and tell me what you see",
)

NOT_BROWSE = (
    # Code, dates and datasets that happen to share a word with a site.
    "check the target date for the release",
    "can you check the canvas size in this code?",
    "check my threads implementation",
    "how do I store data in the browser with localStorage?",
    "does this code run in a browser?",
    "I like this post format, write one like it",
    "follow the account creation flow in auth.py",
    "use the computer science definition please",
    "how do I add a product to the cart in my react app",
    "open my timeline.py file",
    "check my feed parser",
    "check discord.py docs",
    "check the amazon review dataset I attached",
    # Lookups, questions and sandbox jobs.
    "search the web for the latest rust release",
    "google the weather in san bernardino",
    "web search: best laptops 2026",
    "what is instagram?",
    "how do I open a port on ubuntu",
    "open the file config.py and fix the bug",
    "open a PR for this branch",
    "install ComfyUI",
    "go to github and clone https://github.com/x/y",
    "open https://github.com/x/y and run it",
    "read this page https://example.com/post",
    "deep research quantum error correction",
    "write a web scraper for newegg",
    "tell me about my browsing history",
    "browse the repo for TODOs",
    "check my inbox",  # Harvis has its own inbox; a site must be named
    # "check" is not a driving verb even with a site: say "open linkedin and…".
    "check my linkedin notifications",
    "add a 4090 to my cart on newegg",
    # A site mentioned mid-sentence is a topic, not an instruction.
    "I was on instagram yesterday and saw a post about rust",
    "don't open a browser, just tell me what newegg sells",
    "",
)


@pytest.mark.parametrize("text", BROWSE)
def test_a_request_to_drive_a_site_is_a_browse(text):
    assert browse.is_browse_request(text), text


@pytest.mark.parametrize("text", NOT_BROWSE)
def test_everything_else_is_not(text):
    assert not browse.is_browse_request(text), text


@pytest.mark.parametrize("text, explicit", [
    ("use the browser to check my amazon order status", True),
    ("open it in the browser and tell me what you see", True),
    ("can you open the browser and go to newegg", True),
    ("open instagram and scroll my feed for me", False),   # wording only
    ("does this code run in a browser?", False),
    ("how do I store data in the browser with localStorage?", False),
    ("use the computer science definition please", False),
    ("don't use the browser, just tell me", False),
])
def test_asking_for_the_browser_by_name_is_explicit(text, explicit):
    assert browse.is_explicit_browser_request(text) is explicit, text


@pytest.mark.parametrize("text, mode", [
    # Only the ask-by-name is a mode request; wording stays "auto" and the
    # browse lane claims it there (so a down runner falls through to chat).
    ("use the browser to check my amazon order status", "browse"),
    ("open instagram and scroll my feed for me", None),
    ("go to newegg and find three laptops under $800", None),
    ("search the web for the latest rust release", None),
    ("what is the capital of peru", None),
    ("install ComfyUI", "agent"),
    ("use a team to open instagram and scroll my feed", "orchestrate"),
    ("just answer: what does instagram do", "chat"),
    ("don't open a browser, just tell me what newegg sells", "chat"),
])
def test_hermes_reads_an_explicit_browser_ask_out_of_the_wording(text, mode):
    assert chat.requested_mode(text) == mode
    assert "browse" in chat.CHAT_MODES


def test_the_turn_is_claimed_on_auto_or_browse_but_never_on_chat_or_orchestrate():
    msg = "open instagram and scroll my feed"
    assert browse.claims_turn({}, msg)
    assert browse.claims_turn({"harvis_mode": "auto"}, msg)
    assert browse.claims_turn({"harvis_mode": "agent"}, msg)
    assert browse.claims_turn({"harvis_mode": "browse"}, "do the thing we discussed")
    assert not browse.claims_turn({"harvis_mode": "chat"}, msg)
    assert not browse.claims_turn({"harvis_mode": "orchestrate"}, msg)
    assert not browse.claims_turn({}, "search the web for laptops")


def test_a_bot_with_web_research_off_never_browses():
    msg = "open instagram and scroll my feed"
    assert not browse.claims_turn({"harvis_research": False}, msg)
    assert not browse.claims_turn({"harvis_research": False, "harvis_mode": "browse"}, msg)
    assert browse.claims_turn({"harvis_research": True}, msg)


def test_the_goal_keeps_the_run_in_the_browser():
    goal = browse.browse_goal("  open instagram and scroll my feed  ")
    assert goal.startswith("open instagram and scroll my feed")
    assert "computer_open" in goal


def test_the_chat_model_is_the_last_pick_else_the_body_model():
    assert browse.chat_model_pick({"harvis_last_model": "qwen", "model": "llama3"}) == "qwen"
    assert browse.chat_model_pick({"model": "llama3"}) == "llama3"
    assert browse.chat_model_pick({}) == ""


# ─── the bridge ──────────────────────────────────────────────────────────────

def _request(pool="pool"):
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(pg_pool=pool)))


def _user(uid=7):
    return types.SimpleNamespace(id=uid)


def _body(text, **extra):
    return {"model": "llama3", "messages": [{"role": "user", "content": text}], "chat_id": "c1", **extra}


async def _drain(resp) -> str:
    """The assistant text carried by an OpenAI-SSE reply."""
    import json

    out = []
    async for chunk in resp.body_iterator:
        for line in chunk.splitlines():
            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                for choice in json.loads(line[5:]).get("choices", []):
                    out.append(choice.get("delta", {}).get("content") or "")
    return "".join(out)


# The user's default assistant, with clearances they granted it for its own
# jobs. The chat path must not use them.
AGENT = {"id": "a1b2c3d4-0000", "name": "Harvis", "avatar": {"mascot": "claw", "tint": "#7c5cff"},
         "autonomy": {"cleared_limits": ["send", "pay"]}, "user_id": 7}


def _wire(monkeypatch, *, ready=(True, ""), launches: list | None = None):
    from plugins.agents import intake, store

    async def _ready():
        return ready

    async def _default(pool, user_id):
        return AGENT

    async def _launch(**kw):
        (launches if launches is not None else []).append(kw)
        return {"workspace_id": "ws-77", "override": False, "model": "m", "model_source": "s"}

    monkeypatch.setattr(browse, "runner_ready", _ready)
    monkeypatch.setattr(store, "ensure_default_assistant", _default)
    monkeypatch.setattr(intake, "create_agent_run", _launch)


@pytest.fixture(autouse=True)
def _clean_withheld():
    from plugins.agents import computer as c

    c._WITHHELD_PENDING.clear()
    c._WITHHELD_RUNS.clear()
    yield
    c._WITHHELD_PENDING.clear()
    c._WITHHELD_RUNS.clear()


def test_a_normal_question_passes_through_untouched(monkeypatch):
    launches: list = []
    _wire(monkeypatch, launches=launches)
    out = asyncio.run(browse.maybe_handle_browse(_request(), _body("what is the capital of peru"), _user()))
    assert out is None and launches == []


def test_a_web_search_passes_through_to_web_search(monkeypatch):
    launches: list = []
    _wire(monkeypatch, launches=launches)
    out = asyncio.run(browse.maybe_handle_browse(_request(), _body("search the web for rust 2.0"), _user()))
    assert out is None and launches == []


def test_a_browse_request_launches_the_default_assistant_through_the_teammate_door(monkeypatch):
    launches: list = []
    _wire(monkeypatch, launches=launches)
    out = asyncio.run(browse.maybe_handle_browse(
        _request(), _body("open instagram and scroll my feed for me", harvis_last_model="qwen"), _user()))
    assert out is not None
    assert len(launches) == 1
    kw = launches[0]
    assert kw["agent"]["id"] == AGENT["id"]
    assert kw["agent"]["autonomy"] == {}  # the teammate's clearances stay on the Agents page
    assert kw["user_id"] == 7
    assert kw["goal"].startswith("open instagram and scroll my feed for me")
    assert kw["session_id"] == "c1"
    assert kw["last_pick"] == "qwen"
    assert kw["override"] is None  # the wording decides, exactly as for @teammate
    text = asyncio.run(_drain(out))
    assert 'type="workspace_run"' in text
    assert 'workspaceid="ws-77"' in text
    assert 'agentid="a1b2c3d4-0000"' in text  # the card draws the teammate panel + Computer view


def test_the_users_chat_model_stands_in_when_hermes_sent_no_last_pick(monkeypatch):
    launches: list = []
    _wire(monkeypatch, launches=launches)
    asyncio.run(browse.maybe_handle_browse(
        _request(), _body("open instagram and scroll my feed for me"), _user()))
    assert launches[0]["last_pick"] == "llama3"


def test_hermes_browse_mode_forces_the_lane_even_without_the_words(monkeypatch):
    launches: list = []
    _wire(monkeypatch, launches=launches)
    out = asyncio.run(browse.maybe_handle_browse(
        _request(), _body("now do the same for the second one", harvis_mode="browse"), _user()))
    assert out is not None and len(launches) == 1


def test_a_bot_with_research_off_gets_a_plain_answer(monkeypatch):
    launches: list = []
    _wire(monkeypatch, launches=launches)
    out = asyncio.run(browse.maybe_handle_browse(
        _request(), _body("open instagram and scroll my feed", harvis_research=False), _user()))
    assert out is None and launches == []


def test_a_down_runner_is_said_plainly_when_the_browser_was_asked_for(monkeypatch):
    launches: list = []
    _wire(monkeypatch, ready=(False, "The browser runner is not reachable."), launches=launches)
    for body in (_body("use the browser to check my amazon order status"),
                 _body("do the thing we discussed", harvis_mode="browse")):
        out = asyncio.run(browse.maybe_handle_browse(_request(), body, _user()))
        text = asyncio.run(_drain(out))
        assert "browser runner is not reachable" in text
        assert "workspace_run" not in text
    assert launches == []


def test_a_down_runner_lets_a_wording_only_request_fall_through_to_chat(monkeypatch):
    launches: list = []
    _wire(monkeypatch, ready=(False, "The browser runner is not reachable."), launches=launches)
    out = asyncio.run(browse.maybe_handle_browse(
        _request(), _body("open instagram and scroll my feed"), _user()))
    assert out is None and launches == []


def test_runner_ready_reads_the_runner_health_quickly(monkeypatch):
    from fastapi import HTTPException

    from plugins.agents import computer

    seen: dict = {}

    async def _down(method, path, **kw):
        seen.update(kw)
        raise HTTPException(status_code=503, detail="The browser runner is not reachable.")

    async def _headless(method, path, **kw):
        return {"ok": True, "headedAvailable": False}

    async def _up(method, path, **kw):
        return {"ok": True, "headedAvailable": True}

    monkeypatch.setattr(computer, "_runner", _down)
    ok, why = asyncio.run(browse.runner_ready())
    assert not ok and "not reachable" in why
    assert seen["timeout"] <= 3.0  # a down runner must not hold the chat turn
    monkeypatch.setattr(computer, "_runner", _headless)
    ok, why = asyncio.run(browse.runner_ready())
    assert not ok and "screen" in why
    monkeypatch.setattr(computer, "_runner", _up)
    assert asyncio.run(browse.runner_ready()) == (True, "")


# ─── the gate is the teammate's gate, minus the teammate's clearances ────────

def _screen(c, refs):
    c._remember({
        "session_id": "s-browse", "user_id": 7, "agent_id": AGENT["id"],
        "profile": c.profile_key_for(7, AGENT["id"]), "token": "a" * 32, "created_at": 0,
        "refs": refs,
    })


def test_a_login_or_payment_on_the_browse_path_pauses_for_approval():
    from owui_compat.workspace_method import LANE_EXTERNAL_SERVICES
    from plugins.agents import computer as c
    from workspace.orchestration.authz import authorize_action
    from workspace.orchestration.coordinator import computer_context

    # The default assistant's screen, after a snapshot of a login page and a
    # checkout page: the refs are what the gate judges the next call by.
    ctx = computer_context({**AGENT, "autonomy": {}}, user_id=7, run_id="ws-77", pool=None)
    _screen(c, {
        "ref_1": {"role": "textbox", "name": "Password", "type": "password"},
        "ref_2": {"role": "button", "name": "Place your order"},
        "ref_3": {"role": "link", "name": "Explore"},
    })
    try:
        for tool, args, limit, word in (
            ("computer_type", {"ref": "ref_1", "text": "hunter2"}, "sign_in", "signs in"),
            ("computer_click", {"ref": "ref_2"}, "pay", "money"),
        ):
            hard = c.hard_limit_for(ctx, tool, args)
            assert hard == limit, (tool, hard)
            res = asyncio.run(authorize_action(
                tool_name=tool, args=args, lane=LANE_EXTERNAL_SERVICES,
                permission_mode="agent", run_id="ws-77", emit=lambda _p: None, hard_limit=hard,
            ))
            assert res.needs_approval and res.tier == "hard", tool
            assert word in res.reason
        # Scrolling the feed is ordinary browsing and never asks.
        assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_3"}) is None
        plain = asyncio.run(authorize_action(
            tool_name="computer_scroll", args={"direction": "down"}, lane=LANE_EXTERNAL_SERVICES,
            permission_mode="agent", run_id="ws-77", emit=lambda _p: None,
        ))
        assert plain.allowed and not plain.needs_approval
    finally:
        c._forget("s-browse")


def test_the_teammates_standing_clearances_do_not_apply_to_a_chat_run(monkeypatch):
    """The coordinator re-reads the teammate from the database, clearances and
    all. The chat launcher announces the run before launch and binds its id
    after, so whichever side the gate reads first, a like or a payment pauses."""
    from plugins.agents import computer as c
    from workspace.orchestration.coordinator import computer_context

    ctx = computer_context(AGENT, user_id=7, run_id="ws-77", pool=None)  # as the coordinator builds it
    assert ctx["cleared_limits"] == ["send", "pay"]
    _screen(c, {
        "ref_1": {"role": "button", "name": "Like"},
        "ref_2": {"role": "button", "name": "Place your order"},
    })
    try:
        # A roster run of this teammate: the clearances the user granted hold.
        assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_1"}) is None
        assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_2"}) is None

        # Chat launch, before the run id exists (the launch is in flight).
        c.withhold_clearances(7, AGENT["id"])
        assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_1"}) == "send"
        assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_2"}) == "pay"
        # The launch returned: withholding follows the run id, and the
        # teammate's other runs get their clearances back.
        c.bind_withheld_run(7, AGENT["id"], "ws-77")
        assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_1"}) == "send"
        other = {**ctx, "run_id": "ws-roster"}
        assert c.hard_limit_for(other, "computer_click", {"ref": "ref_1"}) is None

        # A launch that failed releases its announcement.
        c.withhold_clearances(7, AGENT["id"])
        assert c.hard_limit_for(other, "computer_click", {"ref": "ref_1"}) == "send"
        c.release_withheld(7, AGENT["id"])
        assert c.hard_limit_for(other, "computer_click", {"ref": "ref_1"}) is None
    finally:
        c._forget("s-browse")


def test_the_bridge_withholds_clearances_around_the_launch(monkeypatch):
    from plugins.agents import computer as c

    launches: list = []
    _wire(monkeypatch, launches=launches)
    asyncio.run(browse.maybe_handle_browse(
        _request(), _body("open instagram and scroll my feed for me"), _user()))
    assert "ws-77" in c._WITHHELD_RUNS
    assert not c._WITHHELD_PENDING  # bound, so nothing is left to over-restrict a roster run


def test_a_failed_launch_releases_the_announcement(monkeypatch):
    from plugins.agents import computer as c, intake

    _wire(monkeypatch)

    async def _boom(**kw):
        raise RuntimeError("workspace down")

    monkeypatch.setattr(intake, "create_agent_run", _boom)
    out = asyncio.run(browse.maybe_handle_browse(
        _request(), _body("open instagram and scroll my feed for me"), _user()))
    assert "could not start" in asyncio.run(_drain(out))
    assert not c._WITHHELD_PENDING and not c._WITHHELD_RUNS
