"""Harvis MCP catalog — the single source of truth for the MCP marketplace
("shop") AND the guided wizard templates.

Every entry keeps the EXACT dict shape mcp_wizard.py's templates always had
(id/name/icon/description/transport/command_template/fields/credentials/tools)
so existing wizard callers keep working, extended with shop metadata:

- ``category``     — 'files' | 'dev' | 'search' | 'productivity' | 'data' | 'custom'
- ``blurb``        — one-line card copy for the shop grid
- ``needs_secret`` — True when the server only becomes fully useful with an API
  key/token. The shop attaches these as 'limited': the mcp_servers row is
  written WITHOUT any secret (the pending_review credential hard gate from
  mcp_wizard.py stands — we never collect or store the key here).

Commands are the real reference servers: the TypeScript ones ship as
``@modelcontextprotocol/server-*`` npm packages (npx), the Python ones as
``mcp-server-*`` PyPI packages (uvx). Pure static data — no secrets, no I/O.
"""

from __future__ import annotations

MCP_CATALOG: list[dict] = [
    # ── files ───────────────────────────────────────────────────────────────
    {
        "id": "filesystem",
        "publisher": "reference",
        "name": "Filesystem",
        "icon": "folder",
        "category": "files",
        "blurb": "Read, search and edit files under one folder you choose.",
        "description": "Read, search and edit files under one directory you choose.",
        "transport": "stdio",
        "needs_secret": False,
        "command_template": "npx -y @modelcontextprotocol/server-filesystem {root}",
        "fields": [
            {
                "key": "root", "label": "Root directory", "type": "text",
                "placeholder": "/data/workspace", "required": True, "secret": False,
                "help": "The server can only see files under this path.",
            }
        ],
        "credentials": [],
        "tools": [
            {"name": "read_file", "desc": "Read a file's contents."},
            {"name": "write_file", "desc": "Create or overwrite a file."},
            {"name": "edit_file", "desc": "Make targeted line edits."},
            {"name": "list_directory", "desc": "List a directory."},
            {"name": "search_files", "desc": "Search files by pattern."},
            {"name": "get_file_info", "desc": "Read file metadata."},
        ],
    },
    # ── dev ─────────────────────────────────────────────────────────────────
    {
        "id": "git",
        "publisher": "reference",
        "name": "Git",
        "icon": "git",
        "category": "dev",
        "blurb": "Status, diff, log and commit against one local repository.",
        "description": "Work a local git repository — status, diffs, history and commits.",
        "transport": "stdio",
        "needs_secret": False,
        "command_template": "uvx mcp-server-git --repository {repo}",
        "fields": [
            {
                "key": "repo", "label": "Repository path", "type": "text",
                "placeholder": "/data/workspace/my-repo", "required": True, "secret": False,
                "help": "Path to an existing git repository the server may operate on.",
            }
        ],
        "credentials": [],
        "tools": [
            {"name": "git_status", "desc": "Show the working-tree status."},
            {"name": "git_diff", "desc": "Diff changes or revisions."},
            {"name": "git_log", "desc": "Read commit history."},
            {"name": "git_add", "desc": "Stage files."},
            {"name": "git_commit", "desc": "Record a commit."},
        ],
    },
    {
        "id": "github",
        "publisher": "reference",
        "name": "GitHub",
        "icon": "github",
        "category": "dev",
        "blurb": "Repos, issues and pull requests via the GitHub API.",
        "description": "Repos, issues and pull requests through the official GitHub MCP server.",
        "transport": "stdio",
        "needs_secret": True,
        "command_template": "npx -y @modelcontextprotocol/server-github",
        "fields": [],
        "credentials": [
            {
                "key": "GITHUB_PERSONAL_ACCESS_TOKEN",
                "label": "Personal access token",
                "secret": True,
                "status": "pending_review",
            }
        ],
        "tools": [
            {"name": "search_repositories", "desc": "Search GitHub repositories."},
            {"name": "get_file_contents", "desc": "Read a file from a repo."},
            {"name": "create_issue", "desc": "Open an issue."},
            {"name": "create_pull_request", "desc": "Open a pull request."},
            {"name": "list_commits", "desc": "List branch commits."},
        ],
    },
    # ── search / web ────────────────────────────────────────────────────────
    {
        "id": "fetch",
        "publisher": "reference",
        "name": "Fetch (web)",
        "icon": "globe",
        "category": "search",
        "blurb": "Fetch a URL and convert the page to model-friendly markdown.",
        "description": "Fetch web pages and convert them to markdown for the model.",
        "transport": "stdio",
        "needs_secret": False,
        "command_template": "uvx mcp-server-fetch",
        "fields": [],
        "credentials": [],
        "tools": [
            {"name": "fetch", "desc": "Fetch a URL and extract its content as markdown."},
        ],
    },
    {
        "id": "puppeteer",
        "publisher": "reference",
        "name": "Puppeteer (browser)",
        "icon": "browser",
        "category": "search",
        "blurb": "Drive a real headless browser — navigate, click, screenshot.",
        "description": "Browser automation via headless Chrome — navigate, click, fill and screenshot pages.",
        "transport": "stdio",
        "needs_secret": False,
        "command_template": "npx -y @modelcontextprotocol/server-puppeteer",
        "fields": [],
        "credentials": [],
        "tools": [
            {"name": "puppeteer_navigate", "desc": "Open a URL."},
            {"name": "puppeteer_screenshot", "desc": "Screenshot the page or an element."},
            {"name": "puppeteer_click", "desc": "Click an element."},
            {"name": "puppeteer_fill", "desc": "Fill an input field."},
            {"name": "puppeteer_evaluate", "desc": "Run JavaScript on the page."},
        ],
    },
    # ── data ────────────────────────────────────────────────────────────────
    {
        "id": "postgres",
        "publisher": "reference",
        "name": "PostgreSQL",
        "icon": "database",
        "category": "data",
        "blurb": "Read-only SQL and schema inspection over one Postgres database.",
        "description": "Read-only queries and schema inspection against a PostgreSQL database.",
        "transport": "stdio",
        "needs_secret": False,
        "command_template": "npx -y @modelcontextprotocol/server-postgres {connection_string}",
        "fields": [
            {
                "key": "connection_string", "label": "Connection string", "type": "text",
                "placeholder": "postgresql://user@host:5432/db", "required": True, "secret": False,
                "help": "Prefer an internal or passwordless DSN — the string is stored as-is "
                        "with the connection, so avoid embedding real passwords.",
            }
        ],
        "credentials": [],
        "tools": [
            {"name": "query", "desc": "Run a read-only SQL query."},
        ],
    },
    {
        "id": "sqlite",
        "publisher": "reference",
        "name": "SQLite",
        "icon": "database",
        "category": "data",
        "blurb": "Query and update one local SQLite database file.",
        "description": "Query, update and inspect a local SQLite database file.",
        "transport": "stdio",
        "needs_secret": False,
        "command_template": "uvx mcp-server-sqlite --db-path {db_path}",
        "fields": [
            {
                "key": "db_path", "label": "Database file", "type": "text",
                "placeholder": "/data/workspace/app.db", "required": True, "secret": False,
                "help": "Path to the .db file the server may open.",
            }
        ],
        "credentials": [],
        "tools": [
            {"name": "read_query", "desc": "Run a SELECT query."},
            {"name": "write_query", "desc": "Run an INSERT/UPDATE/DELETE."},
            {"name": "list_tables", "desc": "List tables."},
            {"name": "describe_table", "desc": "Show a table's schema."},
        ],
    },
    {
        "id": "memory",
        "publisher": "reference",
        "name": "Memory (knowledge graph)",
        "icon": "brain",
        "category": "data",
        "blurb": "A persistent knowledge-graph memory the agent reads and writes.",
        "description": "A persistent knowledge-graph memory the agent can read and write.",
        "transport": "stdio",
        "needs_secret": False,
        "command_template": "npx -y @modelcontextprotocol/server-memory",
        "fields": [],
        "credentials": [],
        "tools": [
            {"name": "create_entities", "desc": "Add entities to the graph."},
            {"name": "create_relations", "desc": "Link entities together."},
            {"name": "add_observations", "desc": "Attach facts to entities."},
            {"name": "search_nodes", "desc": "Search the graph."},
            {"name": "read_graph", "desc": "Read the whole graph."},
        ],
    },
    # ── productivity ────────────────────────────────────────────────────────
    {
        "id": "slack",
        "publisher": "reference",
        "name": "Slack",
        "icon": "slack",
        "category": "productivity",
        "blurb": "Read channels and post messages in your Slack workspace.",
        "description": "List channels, read history and post messages through a Slack bot.",
        "transport": "stdio",
        "needs_secret": True,
        "command_template": "npx -y @modelcontextprotocol/server-slack",
        "fields": [],
        "credentials": [
            {
                "key": "SLACK_BOT_TOKEN",
                "label": "Bot token",
                "secret": True,
                "status": "pending_review",
            },
            {
                "key": "SLACK_TEAM_ID",
                "label": "Team ID",
                "secret": True,
                "status": "pending_review",
            },
        ],
        "tools": [
            {"name": "slack_list_channels", "desc": "List workspace channels."},
            {"name": "slack_get_channel_history", "desc": "Read recent messages."},
            {"name": "slack_post_message", "desc": "Post a message."},
            {"name": "slack_reply_to_thread", "desc": "Reply in a thread."},
        ],
    },
    {
        "id": "notion",
        "publisher": "partner",
        "name": "Notion",
        "icon": "notion",
        "category": "productivity",
        "blurb": "Search, read and edit pages and databases in Notion.",
        "description": "Search, read and edit your Notion pages and databases.",
        "transport": "stdio",
        "needs_secret": True,
        "command_template": "npx -y @notionhq/notion-mcp-server",
        "fields": [],
        "credentials": [
            {
                "key": "NOTION_TOKEN",
                "label": "Internal integration token",
                "secret": True,
                "status": "pending_review",
            }
        ],
        "tools": [
            {"name": "search", "desc": "Search pages and databases."},
            {"name": "fetch", "desc": "Read a page or database."},
            {"name": "create-pages", "desc": "Create pages."},
            {"name": "update-page", "desc": "Update page content."},
        ],
    },
    {
        "id": "sequential-thinking",
        "publisher": "reference",
        "name": "Sequential Thinking",
        "icon": "steps",
        "category": "productivity",
        "blurb": "A structured step-by-step reasoning scratchpad for the agent.",
        "description": "Gives the agent a structured, revisable chain-of-thought scratchpad.",
        "transport": "stdio",
        "needs_secret": False,
        "command_template": "npx -y @modelcontextprotocol/server-sequential-thinking",
        "fields": [],
        "credentials": [],
        "tools": [
            {"name": "sequentialthinking", "desc": "Record and revise reasoning steps."},
        ],
    },
    # ── custom / BYO ────────────────────────────────────────────────────────
    {
        "id": "custom-url",
        "publisher": "byo",
        "name": "Custom server (URL)",
        "icon": "link",
        "category": "custom",
        "blurb": "Bring your own — any remote MCP server over SSE or HTTP.",
        "description": "Connect any remote MCP server over SSE or streamable HTTP.",
        "transport": "sse",
        "transports": ["sse", "streamable-http"],
        "needs_secret": False,
        "command_template": None,
        "fields": [
            {
                "key": "url", "label": "Server URL", "type": "url",
                "placeholder": "https://host/sse", "required": True, "secret": False,
                "help": "Public hosts only — private/loopback addresses are blocked.",
            }
        ],
        "credentials": [],
        "tools": [],
        "tools_note": "Tools are discovered from the server when the agent connects.",
    },
    {
        "id": "custom-stdio",
        "publisher": "byo",
        "name": "Custom server (command)",
        "icon": "terminal",
        "category": "custom",
        "blurb": "Bring your own — run any MCP server as a local process.",
        "description": "Run any MCP server as a local process (stdio transport).",
        "transport": "stdio",
        "needs_secret": False,
        "command_template": "{command}",
        "fields": [
            {
                "key": "command", "label": "Command", "type": "text",
                "placeholder": "npx -y my-mcp-server --flag", "required": True, "secret": False,
                "help": "Exact command line the runtime should execute.",
            }
        ],
        "credentials": [],
        "tools": [],
        "tools_note": "Tools are discovered from the server when the agent connects.",
    },
]

MCP_CATEGORIES: list[dict] = [
    {"id": "files",
        "publisher": "reference", "label": "Files"},
    {"id": "dev",
        "publisher": "reference", "label": "Dev"},
    {"id": "search",
        "publisher": "reference", "label": "Web & search"},
    {"id": "data",
        "publisher": "reference", "label": "Data"},
    {"id": "productivity",
        "publisher": "reference", "label": "Productivity"},
    {"id": "custom",
        "publisher": "reference", "label": "Bring your own"},
]
