"""The general Terms of Use and Acceptable Use for Harvis, readable by anyone at any time.

This is not the sign-up checkbox. ``terms.py`` holds the house rules a guest ticks on
someone else's shared Harvis; this is the text for the software itself, on every
install, signed in or not. ``GET /api/legal`` serves both so the sign-in screen and
Settings ▸ About show one source.

What the text says about data is what the code does. Checked 2026-10-28: no
analytics, tracking or usage reporting anywhere in the backend or the UI. The web
build makes no update check (``/hermes/update/check`` answers locally and the
desktop shim stubs ``updates.check``); the separate Electron shell asks GitHub
(electron/main.ts, ``git ls-remote``) and falls under "GitHub" in TERMS. The outbound calls
that exist are the ones TERMS names: among them three the viewer allows first:
remote images, sound and video in chat (components/chat/remote-image-gate.tsx
waits for a click), chat link embeds (store/embed-consent.ts defaults to a
placeholder until you allow it) and the Hermes bots "Browse hub" frame
(skills-hub.tsx, loaded after its toggle). Add a new
default outbound call, and this text must name it in the same change.

Bump LEGAL_VERSION whenever TERMS or ACCEPTABLE_USE change in substance.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from . import terms

LEGAL_VERSION = "2026-10-30"

TERMS = (
    {
        "heading": "Using Harvis",
        "body": (
            "Harvis is free, open-source software under the MIT license. You may use, copy, change and "
            "share it under that license; the full text is the LICENSE file in the source. Some parts "
            "come from other open-source projects and keep their own licenses; see the NOTICE file and "
            "the license files beside those parts. It comes with no warranty. It can go down, lose data or give wrong answers, so keep your own copy of "
            "anything important."
        ),
    },
    {
        "heading": "Whoever runs it is the operator",
        "body": (
            "Harvis is self-hosted. The person who installs and runs a copy is its operator. The operator "
            "is responsible for that copy, for who they let in, and for what is done with it. The Harvis "
            "project does not run your copy, cannot see it, and cannot reset a password or recover data "
            "for you."
        ),
    },
    {
        "heading": "Your data stays on the machine",
        "body": (
            "Your chats, files, settings and saved keys live in the database and folders of the computer "
            "running Harvis. Harvis has no analytics, no tracking and no usage reporting, and it does not "
            "send your data to the Harvis project. On a shared Harvis, the operator can see what people "
            "send through it."
        ),
    },
    {
        "heading": "What does leave the machine",
        "body": (
            "Only what is listed here. Chatting with a cloud model sends that "
            "chat to the provider whose key is in use. Downloading a model fetches it from where it is "
            "hosted, such as the Ollama registry or Hugging Face. The voice service is on by default. When it "
            "starts, it downloads its speech models from GitHub and Hugging Face, and it checks Hugging "
            "Face for its browser voice files each time it starts. The operator can stop the start-up downloads and the check by setting "
            "VOICE_PREFETCH=0 and VOICE_BROWSER_ASSETS=0; the speech models are then fetched the first time they are used. The optional advanced voice can contact OpenAI's public "
            "file host, to download its speech-to-text model the first time and to check the connection. "
            "Web search goes to the search engine. Asking Harvis "
            "to read a web page sends that address to a reader service, r.jina.ai. GitHub and Google Maps "
            "are contacted only if you use those features. The default theme loads its font from Google "
            "Fonts each time the interface opens, including on the sign-in screen, and some other themes "
            "do too. An image, sound or video from "
            "another website in a chat, including one a model puts in its reply, loads from that website "
            "only after you click to load it. Video, music, social and map links in "
            "chat load from their own site only after you allow it. The Hermes bots page loads the "
            "skills hub from its host only after you open the hub browser. A page an agent writes for "
            "you runs in a sandbox, but it can still load files from other websites. Apart from the "
            "font and the voice service start-up, nothing here runs unless you or the operator use it."
        ),
    },
    {
        "heading": "Models",
        "body": (
            "The models Harvis runs are made by other people, and each has its own license and use "
            "limits. The operator and anyone using a model are responsible for following that license. "
            "Harvis does not change a model's terms."
        ),
    },
    {
        "heading": "Cloud providers and your keys",
        "body": (
            "If you connect a cloud provider with your own API key, that provider's terms and privacy "
            "policy apply to what you send it, and it bills you, not the Harvis project. Keys you save in "
            "the interface are stored encrypted on the machine running Harvis. Keys the operator puts in "
            "the server's settings file are not encrypted. A key you save for a provider is used for your own "
            "chats. A key saved for the agent model proxy is used for everyone's requests through that "
            "proxy, and on a shared Harvis only an admin can set it."
        ),
    },
    {
        "heading": "Game art in the island",
        "body": (
            "The island can optionally use art from a game you own. You bring your own copy from your "
            "own computer. It stays in your browser, is never uploaded or served by Harvis, and Harvis "
            "does not include any of it. Do not share those files or post them anywhere."
        ),
    },
    {
        "heading": "Changes to these terms",
        "body": (
            "When these terms change in substance, the version date changes with them. The current "
            "version is always shown at the top of this page."
        ),
    },
)

ACCEPTABLE_USE = (
    {
        "heading": "Use it lawfully",
        "body": "Do not use Harvis for anything that is illegal where you or the people affected live.",
    },
    {
        "heading": "No harm to other systems or people",
        "body": (
            "Do not use it to spread malware or cause damage, to attack or probe systems you do not "
            "have permission to test, or to harass, threaten or stalk anyone."
        ),
    },
    {
        "heading": "Security testing and research",
        "body": (
            "Harvis can support professional security work, including penetration testing, red, blue "
            "and purple team exercises, vulnerability research, malware analysis, detection "
            "engineering, incident response, training and capture-the-flag events. Test only systems "
            "you own or have written permission to test, stay within the agreed scope and rules of "
            "engagement, and stop when you reach something outside them. Run phishing or other "
            "social engineering exercises only as part of an authorised programme, and never collect "
            "real credentials or personal data from people who have not agreed to take part. Keep "
            "live malware and exploit code inside an isolated test environment."
        ),
    },
    {
        "heading": "Other AI providers and online services",
        "body": (
            "Cloud model providers, search engines and other online services have their own usage "
            "policies. Security questions sent to them, such as requests about exploits or attack "
            "techniques, may be refused or flagged, and may lead to action on your account with that "
            "provider. Harvis does not change those policies and does not help anyone get around "
            "them. You are responsible for following the policy of each service you use through "
            "Harvis. For sensitive security work, prefer a model that runs on your own machine. Do "
            "not use Harvis to test another company's AI system or service, including with prompt "
            "injection or jailbreak attempts, unless that company allows it, for example through a "
            "published bug bounty or a written agreement."
        ),
    },
    {
        "heading": "Handle findings responsibly",
        "body": (
            "Treat what you find as confidential: vulnerabilities, captured credentials, logs and "
            "client data. Keep it within the engagement, share it only with the people entitled to "
            "it, and delete it when the engagement ends or as your agreement requires. Report a "
            "vulnerability to the affected owner privately and give them reasonable time to fix it "
            "before you disclose it. Traffic from web search, browsing and terminals in Harvis "
            "leaves from the network Harvis runs on, so follow that network's own rules as well. To "
            "report a security problem in Harvis itself, use the private reporting described in "
            "the SECURITY.md file in the source, not a public issue."
        ),
    },
    {
        "heading": "Never involving minors",
        "body": "Do not create, request or share sexual content involving minors.",
    },
    {
        "heading": "No impersonation or fraud",
        "body": "Do not use it to pretend to be someone else, to deceive people for gain, or to run scams.",
    },
    {
        "heading": "Respect someone else's Harvis",
        "body": (
            "On a Harvis that someone else runs, follow their house rules and limits. Do not work around "
            "daily limits, a turned-off account or a waiting room, and do not scrape, resell or share "
            "access to their Harvis."
        ),
    },
)

router = APIRouter(tags=["people"])


async def _onboarding(request: Request) -> bool:
    """True while no account exists yet: the first account is the host's own and accepts no house rules."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            return (await conn.fetchval("SELECT COUNT(*) FROM users")) == 0
    except Exception:  # noqa: BLE001 — a public page must render even if the database blips
        return False


def payload(onboarding: bool = False) -> dict:
    return {
        "version": LEGAL_VERSION,
        "terms": [dict(s) for s in TERMS],
        "acceptable_use": [dict(s) for s in ACCEPTABLE_USE],
        "house_rules": terms.config(onboarding),
    }


@router.get("/api/legal")
async def get_legal(request: Request) -> dict:
    """Public, no sign-in: it must load on the sign-in screen. Static text and the house rules the
    sign-up form already gets from /api/config; nothing about this host."""
    return payload(await _onboarding(request))
