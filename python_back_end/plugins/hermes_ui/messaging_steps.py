"""Numbered first-run steps for the Messaging page.

The backend writes these, not the UI, because the right steps depend on how
this install runs a platform. On a default install Discord is the in-process
bot, which reads its token from ``.env`` only, so the page's token field does
nothing for it and the steps have to say so. Everything else runs in the
messaging-gateway sidecar, which reads what the page saves.
"""
from __future__ import annotations

from .messaging_gateway import GATEWAY_START_COMMAND

# How to get the credentials, per platform. Only the platforms the gateway runs.
_CREDENTIAL_STEPS: dict[str, list[str]] = {
    "discord": [
        "Open discord.com/developers/applications, press New Application and give it a name.",
        "Open Bot, press Reset Token and copy the token. On the same page turn on Message Content Intent "
        "and save.",
        "Open OAuth2 → URL Generator. Tick bot, then Send Messages, Read Message History and View Channels. "
        "Open the link it makes and add the bot to your server.",
    ],
    "telegram": [
        "In Telegram, message @BotFather, send /newbot and copy the token it gives you.",
        "Message @userinfobot to get your numeric user ID.",
    ],
    "slack": [
        "Create an app at api.slack.com/apps and turn on Socket Mode.",
        "Create an app-level token (xapp-) with connections:write, install the app to your workspace and "
        "copy the bot token (xoxb-).",
    ],
}


def _legacy_discord_steps(owner: int) -> list[str]:
    who = f"DISCORD_DEFAULT_USER_ID={owner}" if owner else "DISCORD_DEFAULT_USER_ID=<your Harvis user id>"
    return [
        *_CREDENTIAL_STEPS["discord"],
        "On the Harvis machine, open the .env file next to docker-compose.yaml and add two lines: "
        f"DISCORD_BOT_TOKEN=<the token> and {who} (so Discord uses your account's models and settings). "
        "This install's Discord bot reads its token from .env, not from the fields below.",
        "In that folder run: docker compose up -d backend. A plain restart does not re-read .env.",
        "Come back here and wait for Connected, then @mention the bot in your server with a question. "
        "It ignores messages that don't mention it.",
    ]


def setup_steps(pid: str, *, supported: bool, legacy_discord: bool, gateway_up: bool, owner: int) -> list[str]:
    """First-run steps for one platform, or [] when the page's own hint is enough."""
    if not supported:
        return []
    if pid == "discord" and legacy_discord:
        return _legacy_discord_steps(owner)
    steps = list(_CREDENTIAL_STEPS.get(pid, []))
    steps.append("Paste the values into Required below and press Save changes.")
    steps.append("Turn the platform on with its Enabled switch.")
    if not gateway_up:
        steps.append(f"Start the messaging service on the Harvis machine: {GATEWAY_START_COMMAND}")
    steps.append("Wait for Connected, then send the bot a message.")
    return steps
