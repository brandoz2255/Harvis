import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass

import discord
from discord import app_commands
import httpx
from fastapi import Request

from workspace.workspace_router import launch_workspace_internal
from workspace.task_detector import detect_workspace_task

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscordWorkspaceConfig:
    enabled: bool
    token: str
    default_user_id: int
    mention_only: bool
    allowed_channel_ids: set[int]
    agent_id: str
    model_name: str
    max_wait_seconds: int
    enable_interactive: bool


def _parse_int_set(csv: str) -> set[int]:
    out: set[int] = set()
    for part in (csv or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def load_discord_workspace_config() -> DiscordWorkspaceConfig:
    enabled = os.getenv("DISCORD_WORKSPACE_ENABLED", "true").lower() == "true"
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    default_user_id = int(os.getenv("DISCORD_DEFAULT_USER_ID", "2"))
    mention_only = os.getenv("DISCORD_MENTION_ONLY", "true").lower() == "true"
    allowed_channel_ids = _parse_int_set(os.getenv("DISCORD_ALLOWED_CHANNEL_IDS", ""))
    agent_id = os.getenv("DISCORD_WORKSPACE_AGENT_ID", "main").strip() or "main"
    model_name = os.getenv("DISCORD_WORKSPACE_MODEL_NAME", "").strip()
    max_wait_seconds = int(os.getenv("DISCORD_WORKSPACE_MAX_WAIT_SECONDS", "1200"))
    enable_interactive = os.getenv("DISCORD_WORKSPACE_ENABLE_INTERACTIVE", "false").lower() == "true"
    return DiscordWorkspaceConfig(
        enabled=enabled,
        token=token,
        default_user_id=default_user_id,
        mention_only=mention_only,
        allowed_channel_ids=allowed_channel_ids,
        agent_id=agent_id,
        model_name=model_name,
        max_wait_seconds=max_wait_seconds,
        enable_interactive=enable_interactive,
    )


# ── Runtime model override (mutable, changed via !model command) ─────────────

_model_override: str = ""  # when set, overrides cfg.model_name everywhere

_model_pref_cache: dict[int, tuple[float, str, str]] = {}

async def _get_user_model_preference(pool, user_id: int) -> tuple[str, str]:
    """Return (agent_id, model_name) matching the user's saved preference."""
    now = time.monotonic()
    if user_id in _model_pref_cache:
        cached_at, agent_id, model_name = _model_pref_cache[user_id]
        if now - cached_at < 30.0:
            return agent_id, model_name

    res_agent = "main"
    res_model = ""
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT provider_type, model_id FROM openclaw_llm_config WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 1",
                    user_id
                )
            if row:
                provider = row["provider_type"]
                model = row["model_id"] or ""
                if provider == "ollama":
                    res_agent = "local"
                    res_model = model
                elif provider == "moonshot":
                    res_agent = "kimi"
                    res_model = model
                elif provider == "nvidia":
                    res_agent = "nvidia-kimi"
                    res_model = model
                else:
                    res_agent = "main"
                    res_model = model
        except Exception as exc:
            logger.warning("Failed to fetch user model preference: %s", exc)

    _model_pref_cache[user_id] = (now, res_agent, res_model)
    return res_agent, res_model

# One workspace at a time per (channel/thread id, user id) so OpenClaw sessionKey stays singular.
_discord_workspace_locks: dict[tuple[int, int], asyncio.Lock] = {}


def _discord_workspace_lock(message: discord.Message) -> asyncio.Lock:
    cid = int(getattr(message.channel, "id", 0))
    uid = int(message.author.id)
    key = (cid, uid)
    if key not in _discord_workspace_locks:
        _discord_workspace_locks[key] = asyncio.Lock()
    return _discord_workspace_locks[key]


# ── Fast-path: simple questions answered directly via local Ollama ──────────

_LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
_FAST_MODEL = os.getenv("DISCORD_FAST_MODEL", "")  # blank = use cfg.model_name or default

# ── Quick regex pre-filter: skip the AI classifier for obviously simple messages ──
# These patterns strongly indicate the message NEEDS tools/browser/workspace.
# Messages NOT matching any of these get the fast path directly, avoiding the
# 2-5s Ollama classifier call for greetings, short questions, etc.
_WORKSPACE_SIGNALS = re.compile(
    r"(https?://|\.com\b|\.org\b|\.io\b|\.dev\b|\.net\b"
    r"|screenshot|screen\s*shot|browse|open\s+.*website"
    r"|write\s+(?:a\s+)?(?:file|code|script|program|function)"
    r"|create\s+(?:a\s+)?(?:file|repo|project|pr|pull\s*request)"
    r"|run\s+(?:a\s+)?(?:command|script|test|code)"
    r"|search\s+(?:the\s+)?(?:web|internet|google)"
    r"|download|upload|install|deploy|build|compile"
    r"|fix\s+(?:the\s+)?(?:bug|error|issue|code)"
    r"|debug|refactor|merge|commit|push|pull"
    r"|read\s+(?:the\s+)?file|edit\s+(?:the\s+)?file"
    r"|research\s|analyze\s+(?:the\s+)?(?:code|repo|log))",
    re.IGNORECASE,
)


def _is_obviously_simple(text: str) -> bool:
    """Return True for messages that are clearly conversational and don't need
    the AI classifier at all. This saves 2-5s of Ollama classification latency
    for greetings, short questions, etc."""
    # Very long messages are likely complex — route to classifier
    if len(text) > 300:
        return False
    # Any workspace tool signal → needs classifier
    if _WORKSPACE_SIGNALS.search(text):
        return False
    # Short messages without tool signals are conversational
    if len(text) < 200:
        return True
    return False


def _discord_openclaw_session_id(message: discord.Message) -> str:
    """
    One OpenClaw session per Discord channel (or thread) + user.

    Previously we used message.id in the session key, so every new message looked
    like a brand-new Discord/OpenClaw context. That encouraged the model to
    re-introduce "Discord" / identity boilerplate and treat sub-agent spawns as
    separate integrations. Reusing the same session keeps a single logical instance.
    """
    chan_id = getattr(message.channel, "id", "dm")
    return f"discord-{chan_id}-{message.author.id}"


async def _fast_llm_reply(content: str, model: str) -> str:
    """Call local Ollama directly for a quick conversational answer."""
    base_url = _LOCAL_OLLAMA_URL.rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Harvis, a helpful AI assistant on Discord. "
                    "Give concise, direct answers. Keep responses under 1800 characters. "
                    "Do not use markdown headers. Use plain text or simple formatting."
                ),
            },
            {"role": "user", "content": content},
        ],
        "stream": True,
        "reasoning_effort": "none",
        "options": {"num_ctx": 4096},
    }

    parts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            async with client.stream(
                "POST", f"{base_url}/v1/chat/completions", json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    logger.warning("fast_llm_reply: Ollama %s: %s", resp.status_code, body[:300])
                    return ""
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        tok = delta.get("content", "")
                        if tok:
                            parts.append(tok)
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        logger.warning("fast_llm_reply error: %s", exc)
        return ""

    return "".join(parts).strip()


async def _wait_for_workspace_completion(
    *, request: Request, workspace_id: str, timeout_s: int
) -> tuple[str, str | None, str | None]:
    """
    Return (status, final_summary, error_message).
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return ("error", None, "Database not available")

    deadline = asyncio.get_running_loop().time() + max(5, timeout_s)
    while asyncio.get_running_loop().time() < deadline:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, final_summary, error_message FROM workspace_runs WHERE id = $1",
                workspace_id,
            )
        if row:
            status = row.get("status") or "running"
            if status != "running":
                return (status, row.get("final_summary"), row.get("error_message"))
        
        # adaptive polling
        iters = getattr(asyncio.current_task(), "_wait_iters", 0) + 1
        setattr(asyncio.current_task(), "_wait_iters", iters)
        if iters <= 10:
            await asyncio.sleep(0.3)
        elif iters <= 30:
            await asyncio.sleep(1.0)
        else:
            await asyncio.sleep(2.0)

    return ("error", None, f"Timed out after {timeout_s}s waiting for workspace completion")


# ── Friendly tool name mapping for Discord progress updates ──────────────────

_TOOL_LABELS: dict[str, str] = {
    "exec": "Running command",
    "read": "Reading file",
    "write": "Writing file",
    "run_code": "Running code",
    "browser/session": "Opening browser",
    "browser/navigate": "Navigating to page",
    "browser/screenshot": "Taking screenshot",
    "browser/act": "Interacting with page",
    "browser/close": "Closing browser",
}


def _format_progress_line(event_type: str, payload: dict) -> str | None:
    """Convert a workspace_event row into a short Discord-friendly progress line."""
    if event_type == "log":
        msg = (payload.get("message") or "").strip()
        if msg:
            return f"\u2022 {msg[:120]}"
        return None

    if event_type == "tool_call":
        tool = payload.get("tool", "unknown")
        label = _TOOL_LABELS.get(tool, f"Using {tool}")
        # Show inline command preview for exec
        if tool == "exec":
            cmd = (payload.get("args") or {}).get("command", "")
            if cmd:
                cmd_short = cmd[:80] + ("\u2026" if len(cmd) > 80 else "")
                return f"\u2699\ufe0f {label}: `{cmd_short}`"
        return f"\u2699\ufe0f {label}"

    if event_type == "tool_result":
        success = payload.get("success", True)
        tool = payload.get("tool", "")
        if success:
            return f"\u2705 {_TOOL_LABELS.get(tool, tool or 'Tool')} complete"
        else:
            return f"\u274c {_TOOL_LABELS.get(tool, tool or 'Tool')} failed"

    if event_type == "agent_start":
        label = payload.get("agent_label", "Agent")
        model = payload.get("model") or ""
        suffix = f" ({model})" if model else ""
        return f"\U0001f916 {label} started{suffix}"

    if event_type == "agent_end":
        label = payload.get("agent_label", "Agent")
        return f"\U0001f3c1 {label} finished"

    return None


async def _wait_with_progress(
    *,
    request: Request,
    workspace_id: str,
    timeout_s: int,
    progress_msg: discord.Message,
) -> tuple[str, str | None, str | None]:
    """
    Poll workspace_events and edit the Discord progress message with live updates.
    Returns (status, final_summary, error_message).
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return ("error", None, "Database not available")

    deadline = asyncio.get_running_loop().time() + max(5, timeout_s)
    last_seq = -1
    progress_lines: list[str] = ["\u23f3 Starting workspace\u2026"]
    last_edit_text = ""
    edit_interval = 2.5  # seconds between Discord message edits (rate limit friendly)
    last_edit_time = 0.0
    start_time = asyncio.get_running_loop().time()
    notified_long = False

    while asyncio.get_running_loop().time() < deadline:
        # Check if workspace is done
        async with pool.acquire() as conn:
            run_row = await conn.fetchrow(
                "SELECT status, final_summary, error_message FROM workspace_runs WHERE id = $1",
                workspace_id,
            )
        if run_row:
            status = run_row.get("status") or "running"
            if status != "running":
                return (status, run_row.get("final_summary"), run_row.get("error_message"))

        # Fetch new events since last_seq
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT seq, event_type, payload
                FROM workspace_events
                WHERE workspace_id = $1 AND seq > $2
                ORDER BY seq ASC
                LIMIT 20
                """,
                workspace_id, last_seq,
            )

        new_lines = False
        for row in rows:
            last_seq = row["seq"]
            payload = row.get("payload") or {}
            if not isinstance(payload, dict):
                try:
                    payload = json.loads(str(payload))
                except Exception:
                    payload = {}

            line = _format_progress_line(row["event_type"], payload)
            if line:
                progress_lines.append(line)
                new_lines = True
                # Cap displayed lines to avoid exceeding Discord limit
                if len(progress_lines) > 15:
                    progress_lines = progress_lines[-15:]

        # Long task notification
        now_time = asyncio.get_running_loop().time()
        if now_time - start_time > 120.0 and not notified_long:
            progress_lines.append("\u23f3 Task is taking longer than usual, but Harvis is still working on it\u2026")
            new_lines = True
            notified_long = True

        # Edit the progress message if we have new content (rate limited)
        now = time.monotonic()
        if new_lines and (now - last_edit_time) >= edit_interval:
            edit_text = f"**Workspace `{workspace_id}`**\n" + "\n".join(progress_lines)
            # Only edit if text actually changed
            if edit_text != last_edit_text:
                try:
                    await progress_msg.edit(content=edit_text[:2000])
                    last_edit_text = edit_text
                    last_edit_time = now
                except discord.HTTPException:
                    pass  # rate limited or message deleted

        # adaptive polling
        iters = getattr(asyncio.current_task(), "_wait_iters_prog", 0) + 1
        setattr(asyncio.current_task(), "_wait_iters_prog", iters)
        if iters <= 10:
            await asyncio.sleep(0.3)
        elif iters <= 30:
            await asyncio.sleep(1.0)
        else:
            await asyncio.sleep(2.0)

    return ("error", None, f"Timed out after {timeout_s}s waiting for workspace completion")


def _extract_detail_from_text(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r'"detail"\s*:\s*"([^"]+)"', text)
    if m:
        return m.group(1)
    return None


def _extract_artifact_path_from_text(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r'"artifact_path"\s*:\s*"([^"]+)"', text)
    if m:
        return m.group(1).strip()
    # Fallback for plain text formats like: Screenshot saved at: browser/xxx.png
    m2 = re.search(r"(browser/[A-Za-z0-9._\-]+\.png)", text)
    if m2:
        return m2.group(1).strip()
    return None


def _strip_screenshot_path_lines(text: str) -> str:
    """
    Remove "Screenshot: browser/....png" lines from the message text so the
    user sees the attached image rather than a path listing.
    """
    if not text:
        return ""
    # Remove inline screenshot mentions (with or without backticks)
    text = re.sub(
        r"(Screenshot(\s+saved\s+at)?\s*:\s*`?)(browser/[A-Za-z0-9._\-]+\.png)`?\s*(\(for reference\))?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(Screenshot\s+path\s*:\s*)(browser/[A-Za-z0-9._\-]+\.png)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Clean up leftover punctuation/extra whitespace
    text = re.sub(r"\n\s*\n", "\n\n", text).strip()
    return text


async def _find_latest_screenshot_file(
    *, request: Request, workspace_id: str
) -> tuple[str | None, str | None]:
    """
    Return (absolute_path, relative_artifact_path) for latest screenshot if found.
    Uses workspace_events payload text to locate artifact_path.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return (None, None)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_type, payload
            FROM workspace_events
            WHERE workspace_id = $1
            ORDER BY seq DESC
            LIMIT 160
            """,
            workspace_id,
        )

    rel_path: str | None = None
    for row in rows:
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            try:
                payload = json.loads(str(payload))
            except Exception:
                payload = {}

        # Try fields where artifact paths usually appear
        for key in ("output", "message", "content", "summary"):
            val = payload.get(key)
            if isinstance(val, str):
                rel_path = _extract_artifact_path_from_text(val)
                if rel_path:
                    break
        if rel_path:
            break

    if not rel_path:
        return (None, None)

    artifact_root = os.path.abspath(os.getenv("ARTIFACT_STORAGE_DIR", "/data/artifacts"))
    abs_path = os.path.abspath(os.path.join(artifact_root, rel_path))
    # Prevent path traversal; must remain under artifact root.
    if not (abs_path + os.sep).startswith(artifact_root + os.sep) and abs_path != artifact_root:
        return (None, None)
    if not os.path.isfile(abs_path):
        return (None, rel_path)
    return (abs_path, rel_path)


async def _best_workspace_message(
    *, request: Request, workspace_id: str, final_summary: str | None
) -> str:
    """
    Build the full response text from workspace events.

    Strategy:
      1) Concatenate ALL token events in order (the actual LLM response stream).
      2) If no tokens, fall back to final_summary from workspace_runs.
      3) If neither, try tool_result outputs or log messages.
      4) Last resort: "Done."
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return (final_summary or "Done.").strip()

    # Fetch all events in forward order to reconstruct full response
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_type, payload
            FROM workspace_events
            WHERE workspace_id = $1
            ORDER BY seq ASC
            """,
            workspace_id,
        )

    token_parts: list[str] = []
    latest_detail: str | None = None
    latest_log: str | None = None
    done_summary: str | None = None

    for row in rows:
        event_type = row.get("event_type")
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            try:
                payload = json.loads(str(payload))
            except Exception:
                payload = {}

        if event_type == "token":
            content = str(payload.get("content") or "")
            if content:
                token_parts.append(content)

        elif event_type == "done":
            s = str(payload.get("summary") or "").strip()
            if s:
                done_summary = s

        elif event_type == "tool_result" and latest_detail is None:
            output = str(payload.get("output") or "")
            detail = _extract_detail_from_text(output)
            if detail:
                latest_detail = detail

        elif event_type == "log" and latest_log is None:
            msg = str(payload.get("message") or "").strip()
            if msg:
                detail = _extract_detail_from_text(msg)
                latest_log = detail or msg

    # Prefer the full concatenated token stream (the actual LLM output)
    full_tokens = "".join(token_parts).strip()
    if full_tokens:
        return full_tokens

    # Fall back to summaries
    if final_summary and final_summary.strip():
        return final_summary.strip()
    if done_summary:
        return done_summary

    return (latest_detail or latest_log or "Done.").strip()


async def _send_long_message(
    channel: discord.abc.Messageable,
    text: str,
    *,
    file: discord.File | None = None,
) -> None:
    """Send text to Discord, splitting into multiple messages if > 2000 chars.
    The file attachment (if any) is sent with the first chunk."""
    if not text:
        text = "Done."
    limit = 1990  # small margin under 2000
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at a newline near the limit
        split_at = text.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit  # no good newline, hard split
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    for i, chunk in enumerate(chunks):
        kwargs: dict = {"content": chunk}
        if i == 0 and file is not None:
            kwargs["file"] = file
        await channel.send(**kwargs)


def start_discord_workspace_bot(app_request: Request) -> discord.Client | None:
    """
    Start a Discord client in the background.

    Notes:
    - Uses DM + mention-only defaults to avoid responding in every channel.
    - Launches Harvis Workspace runs (agent_id defaults to 'main' = OpenClaw).
    """
    cfg = load_discord_workspace_config()
    if not cfg.enabled:
        logger.info("Discord workspace bot disabled (DISCORD_WORKSPACE_ENABLED=false)")
        return None
    if not cfg.token:
        logger.info("Discord workspace bot not started (DISCORD_BOT_TOKEN not set)")
        return None

    intents = discord.Intents.default()
    intents.message_content = True
    intents.messages = True
    intents.dm_messages = True

    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    async def _list_ollama_models() -> list[str]:
        """Fetch model names from local Ollama."""
        base = _LOCAL_OLLAMA_URL.rstrip("/")
        tags_url = base.replace("/v1", "") + "/api/tags" if "/v1" in base else f"{base}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                resp = await c.get(tags_url)
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception as e:
            logger.warning("Failed to list Ollama models: %s", e)
        return []

    class ModelSelectMenu(discord.ui.Select):
        def __init__(self, models: list[str], current: str):
            options = []
            for m in models[:25]:  # Discord max 25 options
                options.append(discord.SelectOption(
                    label=m,
                    value=m,
                    default=(m == current),
                ))
            super().__init__(placeholder="Pick a model...", options=options)

        async def callback(self, interaction: discord.Interaction):
            global _model_override
            _model_override = self.values[0]
            logger.info("Discord model switched to: %s", _model_override)
            await interaction.response.edit_message(
                content=f"Switched to **`{_model_override}`**",
                view=None,
            )

    class ModelSelectView(discord.ui.View):
        def __init__(self, models: list[str], current: str):
            super().__init__(timeout=60)
            self.add_item(ModelSelectMenu(models, current))

    @tree.command(name="model", description="Pick which model Harvis runs on")
    async def model_command(interaction: discord.Interaction):
        models = await _list_ollama_models()
        if not models:
            await interaction.response.send_message("No models found — is Ollama running?")
            return
        current = _model_override or _FAST_MODEL or cfg.model_name or "qwen3.5-32k:latest"
        view = ModelSelectView(models, current)
        await interaction.response.send_message(
            f"**Current model:** `{current}`\nPick a new one:",
            view=view,
        )

    @client.event
    async def on_ready():
        await tree.sync()
        logger.info("Discord workspace bot online as %s — slash commands synced", getattr(client.user, "name", "unknown"))

    @client.event
    async def on_message(message: discord.Message):
        try:
            if message.author.bot:
                return

            # Channel allowlist (if configured)
            if cfg.allowed_channel_ids and message.channel and hasattr(message.channel, "id"):
                if int(message.channel.id) not in cfg.allowed_channel_ids and not isinstance(
                    message.channel, discord.DMChannel
                ):
                    return

            # Mention-only behavior (default): allow DMs always
            is_dm = isinstance(message.channel, discord.DMChannel)
            if cfg.mention_only and not is_dm:
                if client.user is None:
                    return
                if client.user not in getattr(message, "mentions", []):
                    return

            content = (message.content or "").strip()
            if not content:
                return

            # Strip the bot mention prefix if present (helps prompt quality)
            if client.user is not None:
                mention_tag = f"<@{client.user.id}>"
                content = content.replace(mention_tag, "").strip()

            if not content:
                return

            pool = getattr(app_request.app.state, "pg_pool", None)
            pref_agent_id = cfg.agent_id
            pref_model_name = cfg.model_name
            if pool and not _model_override:
                db_agent_id, db_model_name = await _get_user_model_preference(pool, cfg.default_user_id)
                pref_agent_id = db_agent_id or cfg.agent_id
                pref_model_name = db_model_name or cfg.model_name

            # ── Quick pre-filter: skip AI classifier for obviously simple messages ──
            # This saves 2-5s of Ollama classification for greetings, short Qs, etc.
            use_fast_path = False
            if _is_obviously_simple(content):
                use_fast_path = True
            else:
                # Dynamic Router: use AI to decide if a workspace is needed
                chat_hist = [{"role": "user", "content": content}]
                suggestion = await detect_workspace_task(chat_hist)
                if not suggestion.should_suggest:
                    use_fast_path = True

            # ── Fast path: simple questions → direct LLM call, no workspace ──
            if use_fast_path:
                fast_model = _model_override or _FAST_MODEL or pref_model_name or "qwen3.5-32k:latest"
                logger.info("Discord fast-path: model=%s msg=%r", fast_model, content[:80])
                async with message.channel.typing():
                    reply = await _fast_llm_reply(content, fast_model)
                if reply:
                    # Split into chunks if longer than Discord's 2000-char limit
                    await _send_long_message(message.channel, reply)
                    return
                # If fast path returned empty (Ollama down, etc.), fall through to workspace
                logger.warning("Discord fast-path returned empty — falling back to workspace")

            # ── Workspace path: complex tasks needing tools/browser/agents ──
            lock = _discord_workspace_lock(message)
            if lock.locked():
                await message.channel.send(
                    "\u23f3 A workspace is already running for you in this channel — "
                    "wait for it to finish, then send your next message."
                )
                return

            async with lock:
                session_id = _discord_openclaw_session_id(message)

                progress_msg = await message.channel.send(
                    f"**Workspace launching\u2026**\n\u23f3 Starting workspace\u2026"
                )

                data = await launch_workspace_internal(
                    request=app_request,
                    user_id=cfg.default_user_id,
                    task_brief=content,
                    chat_history=[],
                    agent_id=pref_agent_id,
                    model_name=_model_override or pref_model_name,
                    session_id=session_id,
                    enable_interactive=cfg.enable_interactive,
                )
                workspace_id = data["workspace_id"]

                status, summary, err = await _wait_with_progress(
                    request=app_request,
                    workspace_id=workspace_id,
                    timeout_s=cfg.max_wait_seconds,
                    progress_msg=progress_msg,
                )

                # Delete the progress message — replace with clean final result
                try:
                    await progress_msg.delete()
                except discord.HTTPException:
                    pass

                if status == "done":
                    msg = await _best_workspace_message(
                        request=app_request,
                        workspace_id=workspace_id,
                        final_summary=summary,
                    )
                    screenshot_abs, screenshot_rel = await _find_latest_screenshot_file(
                        request=app_request,
                        workspace_id=workspace_id,
                    )
                    if screenshot_abs:
                        cleaned_msg = _strip_screenshot_path_lines(msg)
                        if not cleaned_msg:
                            cleaned_msg = "Here's the result:"
                        try:
                            # Send response text + screenshot attachment
                            await _send_long_message(
                                message.channel,
                                cleaned_msg,
                                file=discord.File(screenshot_abs, filename=os.path.basename(screenshot_abs)),
                            )
                        except Exception as send_exc:
                            logger.warning("Discord file upload failed: %s", send_exc)
                            await _send_long_message(message.channel, msg)
                    else:
                        await _send_long_message(message.channel, msg)
                elif status == "cancelled":
                    await message.channel.send(f"Workspace `{workspace_id}` was cancelled.")
                else:
                    await message.channel.send(
                        f"Workspace `{workspace_id}` failed: {((err or 'Unknown error')[:1800])}"
                    )

        except Exception as exc:
            logger.exception("Discord workspace bot error: %s", exc)
            try:
                await message.channel.send(f"Workspace error: {str(exc)[:1800]}")
            except Exception:
                pass

    # Start the bot in the background
    async def _runner():
        await client.start(cfg.token)

    asyncio.create_task(_runner(), name="discord-workspace-bot")
    return client

