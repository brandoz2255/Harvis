-- 019: Hermes UI bots — a saved, named assistant (persona + model + knowledge)
-- the user starts chats with from the sidebar.
--
-- Like 018 (teammates), this EXTENDS owui_subagents instead of adding a third
-- roster table. A bot and a sub-agent are the same shape — owner, name,
-- description, system prompt, model — and `is_bot` is the only thing that
-- separates them, so one CRUD surface and one ownership check keep working.
-- The teammate columns from 018 (title, avatar) are reused for the bot's
-- display name and picture.
--
-- Every column is defaulted so existing rows keep working, and every statement
-- is IF NOT EXISTS so main.py can apply this on every boot.

ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS is_bot          BOOLEAN NOT NULL DEFAULT FALSE;
-- ["<notebook uuid>", ...] — Harvis notebooks whose passages are pulled into
-- every turn of a chat with this bot. Ownership is re-checked at read time.
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS notebook_ids    JSONB NOT NULL DEFAULT '[]'::jsonb;
-- ["Summarise this paper", ...] — chips shown in an empty bot chat.
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS starter_prompts JSONB NOT NULL DEFAULT '[]'::jsonb;
-- {"web_research": true, "workspace_agent": true} — which Harvis tools a chat
-- with this bot may reach for. Missing keys mean "on".
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS tools           JSONB NOT NULL DEFAULT '{}'::jsonb;
-- Reserved for a later "runs on" target ({"kind": "local"} | {"kind": "vm", ...}).
-- Nothing reads or writes it yet; it exists so the row can carry a placement
-- without another migration.
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS runs_on         JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_owui_subagents_bots
    ON owui_subagents (user_id, updated_at DESC) WHERE is_bot;
