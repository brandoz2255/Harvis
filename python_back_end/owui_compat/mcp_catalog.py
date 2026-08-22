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
    {"id": "files", "label": "Files"},
    {"id": "dev", "label": "Dev"},
    {"id": "search", "label": "Web & search"},
    {"id": "data", "label": "Data"},
    {"id": "productivity", "label": "Productivity"},
    {"id": "custom", "label": "Bring your own"},
]

# ── the Plugins directory ───────────────────────────────────────────────────
# The catalog above is what Harvis can INSTALL AND RUN today. The directory
# below is the browsable storefront: the long list of vendors people actually
# look for. Both render in the same UI, distinguished by `connect`:
#
#   'install'      — Harvis runs the server itself (stdio via npx/uvx). Connecting
#                    writes an mcp_servers row; API-key servers connect 'limited'
#                    under the existing pending_review credential gate.
#   'remote_oauth' — the VENDOR hosts a real MCP endpoint, but reaching it needs an
#                    OAuth 2.1 + PKCE sign-in Harvis cannot perform yet: only token
#                    STORAGE exists (plugins/mcp/token_storage.py) — no authorize
#                    call, no callback route, no client registration. So these are
#                    NOT connectable here. The card shows the published endpoint and
#                    sends the user to the vendor's own page to connect it.
#   'external'     — no MCP server we can point at. A directory entry: the card
#                    links to the official page and nothing else.
#
# Why the split is stated so bluntly: a storefront that renders a Connect button
# it cannot honour is worse than one that says where to go. Every entry below is
# link-out honest. When an OAuth client lands, 'remote_oauth' rows become
# connectable WITHOUT touching this data — only the flow changes.
#
# `homepage` is deliberately a root or near-root URL: deep documentation paths
# rot, and a 404 from our own storefront is the exact failure this section is
# meant to prevent. `docs_url` appears only where the path is a stable entry
# point. `tools` is indicative — the real list comes from the server's
# tools/list on connect, which is why the UI labels it "typical tools".

MCP_SECTIONS: list[dict] = [
    {"id": "featured", "label": "Featured"},
    {"id": "dev_tools", "label": "Developer Tools"},
    {"id": "productivity", "label": "Productivity"},
    {"id": "communication", "label": "Communication"},
    {"id": "data_analytics", "label": "Data & Analytics"},
    {"id": "creativity", "label": "Creativity"},
    {"id": "research", "label": "Education & Research"},
    {"id": "business", "label": "Business & Operations"},
    {"id": "core", "label": "Harvis built-ins"},
    {"id": "byo", "label": "Bring your own"},
]


def _entry(
    id: str,
    name: str,
    vendor: str,
    section: str,
    blurb: str,
    homepage: str,
    *,
    connect: str = "external",
    mcp_url: str | None = None,
    docs_url: str | None = None,
    brand: str | None = None,
    featured: bool = False,
    tools: tuple[str, ...] = (),
    prompts: tuple[str, ...] = (),
) -> dict:
    """One directory card. `brand` defaults to the id — the frontend logo key."""
    return {
        "id": id,
        "name": name,
        "vendor": vendor,
        "section": section,
        "blurb": blurb,
        "homepage": homepage,
        "docs_url": docs_url,
        "connect": connect,
        "mcp_url": mcp_url,
        "brand": brand or id,
        "featured": featured,
        "tools": list(tools),
        "prompts": list(prompts),
    }


MCP_DIRECTORY: list[dict] = [
    # ── Developer Tools ─────────────────────────────────────────────────────
    _entry("sentry", "Sentry", "Sentry", "dev_tools",
           "Read production errors and traces, and triage issues.",
           "https://sentry.io", connect="remote_oauth", mcp_url="https://mcp.sentry.dev/mcp",
           featured=True, tools=("find_errors", "get_issue_details", "search_events"),
           prompts=("What are my top unresolved Sentry issues this week?",)),
    _entry("linear", "Linear", "Linear", "dev_tools",
           "Create, search and update issues, projects and cycles.",
           "https://linear.app", connect="remote_oauth", mcp_url="https://mcp.linear.app/sse",
           featured=True, tools=("create_issue", "update_issue", "list_issues", "search"),
           prompts=("File a Linear bug for the failing login redirect",)),
    _entry("atlassian", "Jira & Confluence", "Atlassian", "dev_tools",
           "Work Jira issues and Confluence pages from the thread.",
           "https://www.atlassian.com", connect="remote_oauth",
           mcp_url="https://mcp.atlassian.com/v1/sse",
           tools=("createJiraIssue", "searchJiraIssues", "getConfluencePage")),
    _entry("vercel", "Vercel", "Vercel", "dev_tools",
           "Inspect deployments, logs and project configuration.",
           "https://vercel.com", connect="remote_oauth", mcp_url="https://mcp.vercel.com",
           tools=("list_deployments", "get_deployment", "get_logs")),
    _entry("supabase", "Supabase", "Supabase", "dev_tools",
           "Query your database, inspect schema and manage projects.",
           "https://supabase.com", connect="remote_oauth", mcp_url="https://mcp.supabase.com/mcp",
           tools=("execute_sql", "list_tables", "get_project")),
    _entry("cloudflare", "Cloudflare", "Cloudflare", "dev_tools",
           "Read docs, Workers, DNS and account configuration.",
           "https://www.cloudflare.com", connect="remote_oauth",
           mcp_url="https://docs.mcp.cloudflare.com/sse",
           tools=("search_docs", "list_workers", "analytics")),
    _entry("figma", "Figma", "Figma", "dev_tools",
           "Pull frames, variables and design context into code.",
           "https://www.figma.com", tools=("get_file", "get_node", "get_variables")),
    _entry("netlify", "Netlify", "Netlify", "dev_tools",
           "Deploys, build logs and site configuration.", "https://www.netlify.com"),
    _entry("postman", "Postman", "Postman", "dev_tools",
           "Collections, environments and API request runs.", "https://www.postman.com"),
    _entry("docker", "Docker", "Docker", "dev_tools",
           "Images, containers and Compose stacks.", "https://www.docker.com"),
    _entry("replit", "Replit", "Replit", "dev_tools",
           "Cloud dev environments and instant app hosting.", "https://replit.com"),
    _entry("circleci", "CircleCI", "CircleCI", "dev_tools",
           "Pipeline status, failures and build logs.", "https://circleci.com"),
    # ── Productivity ────────────────────────────────────────────────────────
    _entry("asana", "Asana", "Asana", "productivity",
           "Tasks, projects and portfolios across your workspace.",
           "https://asana.com", connect="remote_oauth", mcp_url="https://mcp.asana.com/sse",
           featured=True, tools=("create_task", "search_tasks", "update_task")),
    _entry("monday", "monday.com", "monday.com", "productivity",
           "Boards, items and updates in your workspace.",
           "https://monday.com", connect="remote_oauth", mcp_url="https://mcp.monday.com/sse",
           tools=("create_item", "get_board", "update_item")),
    _entry("google-drive", "Google Drive", "Google", "productivity",
           "Search and read documents, sheets and slides.", "https://drive.google.com",
           brand="googledrive", featured=True),
    _entry("google-calendar", "Google Calendar", "Google", "productivity",
           "Read your schedule and draft events.", "https://calendar.google.com",
           brand="googlecalendar"),
    _entry("dropbox", "Dropbox", "Dropbox", "productivity",
           "Search and read files in your Dropbox.", "https://www.dropbox.com"),
    _entry("clickup", "ClickUp", "ClickUp", "productivity",
           "Tasks, docs and sprints.", "https://clickup.com"),
    _entry("trello", "Trello", "Atlassian", "productivity",
           "Boards, lists and cards.", "https://trello.com"),
    _entry("todoist", "Todoist", "Doist", "productivity",
           "Personal tasks, projects and due dates.", "https://todoist.com"),
    _entry("airtable", "Airtable", "Airtable", "productivity",
           "Bases, tables and records as a lightweight database.", "https://airtable.com"),
    _entry("zapier", "Zapier", "Zapier", "productivity",
           "Reach thousands of apps through your own Zapier MCP URL.",
           "https://zapier.com", docs_url="https://zapier.com/mcp"),
    # ── Communication ───────────────────────────────────────────────────────
    _entry("intercom", "Intercom", "Intercom", "communication",
           "Conversations, contacts and help-centre articles.",
           "https://www.intercom.com", connect="remote_oauth",
           mcp_url="https://mcp.intercom.com/sse",
           tools=("search_conversations", "get_contact")),
    _entry("gmail", "Gmail", "Google", "communication",
           "Search threads and draft replies.", "https://mail.google.com", brand="gmail"),
    _entry("outlook", "Outlook", "Microsoft", "communication",
           "Mail and calendar across Microsoft 365.", "https://outlook.com",
           brand="microsoftoutlook"),
    _entry("teams", "Microsoft Teams", "Microsoft", "communication",
           "Channels, chats and meeting notes.", "https://www.microsoft.com/microsoft-teams",
           brand="microsoftteams"),
    _entry("zoom", "Zoom", "Zoom", "communication",
           "Meetings, recordings and transcripts.", "https://zoom.us"),
    _entry("twilio", "Twilio", "Twilio", "communication",
           "Programmable SMS, voice and verification.", "https://www.twilio.com"),
    # ── Data & Analytics ────────────────────────────────────────────────────
    _entry("posthog", "PostHog", "PostHog", "data_analytics",
           "Product analytics, funnels, flags and session insights.",
           "https://posthog.com", connect="remote_oauth", mcp_url="https://mcp.posthog.com/sse",
           tools=("query_insight", "list_feature_flags")),
    _entry("bigquery", "BigQuery", "Google Cloud", "data_analytics",
           "Warehouse-scale SQL over your datasets.",
           "https://cloud.google.com/bigquery", brand="googlebigquery"),
    _entry("snowflake", "Snowflake", "Snowflake", "data_analytics",
           "Warehouse queries and schema exploration.", "https://www.snowflake.com"),
    _entry("mongodb", "MongoDB", "MongoDB", "data_analytics",
           "Collections, documents and aggregation pipelines.", "https://www.mongodb.com"),
    _entry("grafana", "Grafana", "Grafana Labs", "data_analytics",
           "Dashboards, metrics and alert state.", "https://grafana.com"),
    _entry("elasticsearch", "Elasticsearch", "Elastic", "data_analytics",
           "Full-text and vector search over your indices.", "https://www.elastic.co"),
    _entry("mixpanel", "Mixpanel", "Mixpanel", "data_analytics",
           "Event analytics, funnels and retention.", "https://mixpanel.com"),
    _entry("amplitude", "Amplitude", "Amplitude", "data_analytics",
           "Product analytics and behavioural cohorts.", "https://amplitude.com"),
    # ── Creativity ──────────────────────────────────────────────────────────
    _entry("canva", "Canva", "Canva", "creativity",
           "Generate and edit designs, decks and social assets.",
           "https://www.canva.com", connect="remote_oauth", mcp_url="https://mcp.canva.com/mcp",
           featured=True, tools=("create_design", "search_designs", "export_design")),
    _entry("elevenlabs", "ElevenLabs", "ElevenLabs", "creativity",
           "Text-to-speech, dubbing and voice cloning.", "https://elevenlabs.io"),
    _entry("adobe", "Adobe Express", "Adobe", "creativity",
           "Design and edit with Adobe's creative tools.", "https://www.adobe.com"),
    _entry("descript", "Descript", "Descript", "creativity",
           "Edit audio and video by editing the transcript.", "https://www.descript.com"),
    _entry(
        "sentrysearch-video",
        "SentrySearch (video)",
        "ssrajadh / Harvis",
        "creativity",
        "Optional local VIDEO footage search (compose profile sentrysearch). "
        "Not Sentry.io errors — not CVE/OSINT. Default OFF until you confirm video search.",
        "https://github.com/ssrajadh/sentrysearch",
        connect="external",
        tools=("search_video", "trim_clip"),
        prompts=("Find the clip where the garage door opens",),
    ),
    _entry("gamma", "Gamma", "Gamma", "creativity",
           "Generate decks, docs and webpages.", "https://gamma.app"),
    _entry("blender", "Blender", "Blender Foundation", "creativity",
           "Drive 3D modelling, scenes and renders.", "https://www.blender.org"),
    # ── Education & Research ────────────────────────────────────────────────
    _entry("huggingface", "Hugging Face", "Hugging Face", "research",
           "Search models, datasets and Spaces, and run inference.",
           "https://huggingface.co", connect="remote_oauth",
           mcp_url="https://huggingface.co/mcp", featured=True,
           tools=("model_search", "dataset_search", "space_search")),
    _entry("wolframalpha", "Wolfram Alpha", "Wolfram", "research",
           "Computation, maths and curated scientific data.", "https://www.wolframalpha.com"),
    _entry("arxiv", "arXiv", "arXiv", "research",
           "Search and read preprints across the sciences.", "https://arxiv.org"),
    _entry("semanticscholar", "Semantic Scholar", "Allen Institute for AI", "research",
           "Search papers, citations and authors.", "https://www.semanticscholar.org"),
    _entry("pubmed", "PubMed", "NIH / NLM", "research",
           "Biomedical and life-sciences literature.", "https://pubmed.ncbi.nlm.nih.gov",
           brand="pubmed"),
    _entry("wikipedia", "Wikipedia", "Wikimedia Foundation", "research",
           "Look up and cite encyclopedia articles.", "https://www.wikipedia.org"),
    _entry("consensus", "Consensus", "Consensus", "research",
           "Evidence-backed answers drawn from research papers.", "https://consensus.app"),
    # ── Business & Operations ───────────────────────────────────────────────
    _entry("stripe", "Stripe", "Stripe", "business",
           "Customers, payments, subscriptions and invoices.",
           "https://stripe.com", connect="remote_oauth", mcp_url="https://mcp.stripe.com",
           featured=True, tools=("list_customers", "create_payment_link", "list_invoices")),
    _entry("paypal", "PayPal", "PayPal", "business",
           "Orders, invoices, subscriptions and disputes.",
           "https://www.paypal.com", connect="remote_oauth", mcp_url="https://mcp.paypal.com/sse",
           tools=("create_invoice", "list_transactions")),
    _entry("square", "Square", "Block", "business",
           "Payments, catalog, orders and customers.",
           "https://squareup.com", connect="remote_oauth", mcp_url="https://mcp.squareup.com/sse",
           tools=("list_payments", "list_catalog")),
    _entry("hubspot", "HubSpot", "HubSpot", "business",
           "CRM contacts, deals and pipelines.", "https://www.hubspot.com"),
    _entry("salesforce", "Salesforce", "Salesforce", "business",
           "Accounts, opportunities and reports.", "https://www.salesforce.com"),
    _entry("shopify", "Shopify", "Shopify", "business",
           "Products, orders and storefront data.", "https://www.shopify.com"),
    _entry("quickbooks", "QuickBooks", "Intuit", "business",
           "Invoices, expenses and reports.", "https://quickbooks.intuit.com",
           brand="quickbooks"),
    _entry("ramp", "Ramp", "Ramp", "business",
           "Spend, cards and transaction data.", "https://ramp.com"),
]

# Metadata for the installable catalog: the vendor/official-page fields the
# directory cards carry, plus the display `section` and logo `brand` key. Applied
# as a merge instead of editing 13 literals so the wizard-facing shape above
# stays readable and the two halves of the storefront can't drift apart.
_INSTALL_META: dict[str, dict] = {
    "filesystem": {"section": "core", "brand": "folder", "vendor": "MCP reference",
                   "homepage": "https://modelcontextprotocol.io"},
    "memory": {"section": "core", "brand": "brain", "vendor": "MCP reference",
               "homepage": "https://modelcontextprotocol.io"},
    "sequential-thinking": {"section": "core", "brand": "steps", "vendor": "MCP reference",
                            "homepage": "https://modelcontextprotocol.io"},
    "fetch": {"section": "core", "brand": "globe", "vendor": "MCP reference",
              "homepage": "https://modelcontextprotocol.io"},
    "puppeteer": {"section": "core", "brand": "browser", "vendor": "MCP reference",
                  "homepage": "https://modelcontextprotocol.io"},
    "git": {"section": "dev_tools", "brand": "git", "vendor": "MCP reference",
            "homepage": "https://git-scm.com"},
    "github": {"section": "dev_tools", "brand": "github", "vendor": "GitHub",
               "homepage": "https://github.com", "featured": True},
    "postgres": {"section": "data_analytics", "brand": "postgresql", "vendor": "PostgreSQL",
                 "homepage": "https://www.postgresql.org"},
    "sqlite": {"section": "data_analytics", "brand": "sqlite", "vendor": "SQLite",
               "homepage": "https://www.sqlite.org"},
    "slack": {"section": "communication", "brand": "slack", "vendor": "Slack",
              "homepage": "https://slack.com", "featured": True},
    "notion": {"section": "productivity", "brand": "notion", "vendor": "Notion",
               "homepage": "https://www.notion.so", "featured": True},
    "custom-url": {"section": "byo", "brand": "link", "vendor": "You",
                   "homepage": "https://modelcontextprotocol.io"},
    "custom-stdio": {"section": "byo", "brand": "terminal", "vendor": "You",
                     "homepage": "https://modelcontextprotocol.io"},
}

for _e in MCP_CATALOG:
    _e.update(_INSTALL_META.get(_e["id"], {}))
    _e.setdefault("section", "core")
    _e.setdefault("brand", _e.get("icon") or _e["id"])
    _e.setdefault("featured", False)
    _e.setdefault("docs_url", None)
    _e.setdefault("mcp_url", None)
    # Harvis runs these itself — that IS the connect story, so it is not optional.
    _e["connect"] = "install"

# Every storefront card, installable and directory alike, in one list. Order is
# section order then declaration order; the UI groups by `section`.
_SECTION_RANK = {s["id"]: i for i, s in enumerate(MCP_SECTIONS)}
MCP_PLUGINS: list[dict] = sorted(
    [*MCP_CATALOG, *MCP_DIRECTORY],
    key=lambda e: _SECTION_RANK.get(e.get("section", "core"), 99),
)
