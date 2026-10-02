"""Numbered first-run steps for the Messaging page.

The backend writes these, not the UI, because the right steps depend on how
this install runs a platform. Every platform the gateway sidecar runs reads
what the page saves, on docker compose and on Kubernetes alike: the token goes
into the user's settings, the gateway pulls it on the next sync. Only when the
legacy in-process Discord bot is actually running (token in ``.env``) do the
page's fields do nothing for Discord, and the steps have to say so — worded
for compose or for the cluster, since ``docker compose up`` is meaningless on k3s.
"""
from __future__ import annotations

from . import messaging_gateway

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
    where = "On the cluster node" if messaging_gateway.on_kubernetes() else "On the Harvis machine"
    return [
        *_CREDENTIAL_STEPS["discord"],
        f"{where}, open the .env file next to docker-compose.yaml and add two lines: "
        f"DISCORD_BOT_TOKEN=<the token> and {who} (so Discord uses your account's models and settings). "
        "This install's Discord bot reads its token from .env, not from the fields below.",
        messaging_gateway.apply_env_instruction("backend"),
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
    steps.append("Paste the values into Required below and press Save changes. Harvis stores them encrypted and "
                 "hands them to its messaging service; no file edit or redeploy is needed.")
    steps.append("Turn the platform on with its Enabled switch.")
    if not gateway_up:
        steps.append(f"Start the messaging service: {messaging_gateway.gateway_start_command()}")
    steps.append("Wait for Connected, then send the bot a message. The first message from a new chat gets a pairing "
                 "code to approve under Pairing on this page.")
    return steps
