// Harvis Integrations — the plug-and-play catalog (data model + helpers).
// Pure data + pure functions (no fetch). The static `status` is the baseline; live
// detection (GET /api/owui/integrations/status) overrides it via mergeLiveStatus().
//
// Framing: Models = brains · Applications = engines · Services = connections ·
// Packs = recipes · Harvis = the control plane. Integrations belong to Harvis GLOBALLY;
// surfaces consume them by capability (`provides`/`usedBy`). `brandKey` resolves to
// BrandGlyph.svelte. NOTE: union TYPES come from ./capabilities via `import type` (erased) —
// so catalog.ts has NO runtime dependency on capabilities.ts (capabilities.ts depends on us).

import type { IntegrationCapability, HarvisSurface } from './capabilities';

export type IntegrationCategory = 'application' | 'model' | 'service' | 'pack';

// green=ready/connected · blue=running · amber=needs-setup · gray=available · slate=coming-soon · red=error
export type IntegrationStatus =
	| 'available'
	| 'ready'
	| 'running'
	| 'needs_setup'
	| 'coming_soon'
	| 'error';

// How close an application is to being a swappable Code-mode engine (no execution built).
export type EngineSupport = 'none' | 'planned' | 'candidate' | 'supported';

export type AuthMode = 'none' | 'api_key' | 'local_auth' | 'oauth' | 'config_file' | 'ollama' | 'custom';

export interface CommandSpec {
	install?: string;
	pull?: string;
	launch?: string;
	check?: string; // human-facing check — NEVER executed by us
}

export type ActionKind = 'copy' | 'save_preference' | 'link' | 'detail';

export interface IntegrationAction {
	id: string;
	label: string;
	kind: ActionKind;
	command?: keyof CommandSpec; // for kind:'copy'
	href?: string; // for kind:'link' — internal route only
	primary?: boolean;
	title?: string; // tooltip
}

export interface IntegrationDefinition {
	id: string;
	name: string;
	category: IntegrationCategory;
	description: string;
	longDescription?: string;
	brandKey: string;
	status: IntegrationStatus; // static baseline
	provider?: string;
	recommended?: boolean;
	commands?: CommandSpec;
	capabilities?: string[]; // free-form feature tags (modal "Feature tags")
	provides?: IntegrationCapability[]; // typed capability contract (capability-first)
	usedBy?: HarvisSurface[]; // Harvis surfaces that consume it
	runtimeNote?: string; // honest runtime caveat (e.g. "wiring planned", "not runnable yet")
	connect?: 'openclaw_byo' | 'github_oauth' | 'mcp_link' | 'engine_api_key' | 'hermes_agent' | 'user_api_key'; // Phase B/E2/F: which in-modal connect flow
	providerKey?: string; // for connect:'user_api_key' — the /api/user/api-keys provider_name (e.g. 'moonshot')
	// For connect:'engine_api_key' — the `user_engine_auth.engine` id this card's key is stored
	// under (the {engine} path segment of /api/owui/engine-auth/{engine}). Authored per card
	// instead of inferred, so adding a provider never means editing a ternary in ConnectionPanel.
	authEngine?: string;
	keyConsoleUrl?: string; // where the user creates that key (shown as a link, never auto-opened)
	keyHelp?: string; // one honest line under the key field — what the key is used for
	permissions?: string[];
	auth?: { required: boolean; modes: AuthMode[]; configured?: boolean; notes?: string };
	engine?: { support: EngineSupport; adapterId?: string; notes?: string };
	model?: { supported?: string[]; preferred?: string };
	links?: { docs?: string; homepage?: string };
	href?: string; // a "Manage/Connect" internal route
	detect?: { serviceKey?: string }; // 'ollama'|'openclaw'|'github'|'mcp'|'discord'
	// runtime-only (set by mergeLiveStatus, not authored):
	detail?: string;
}

export interface LiveStatus {
	services: Record<string, { status: IntegrationStatus; detail?: string }>;
	installedModels?: string[]; // returned by the backend; unused while Models are unrendered
}

// ───────────────────────────────────────────────────────────── catalog data

export const CATALOG: IntegrationDefinition[] = [
	// ── Applications (coding engines / work surfaces) ──
	{
		id: 'claude-code',
		name: 'Claude Code',
		category: 'application',
		description: 'Anthropic’s terminal coding agent for local developer workflows.',
		longDescription:
			'Anthropic’s terminal-native coding agent. Harvis drives it as an external Build engine on your own auth — it edits an isolated clone of your repo, runs the task, and streams the diff back into Vibe Code. Connect with an Anthropic API key OR a Claude subscription token (Pro/Max/Team/Enterprise) — so subscribers don’t need API credits.',
		brandKey: 'claude',
		status: 'available',
		provider: 'Anthropic',
		capabilities: ['coding', 'tool_use', 'planning', 'files', 'shell'],
		provides: ['code_engine_candidate'],
		usedBy: ['code'],
		permissions: ['Runs shell commands', 'Reads / writes repo files'],
		connect: 'engine_api_key',
		runtimeNote: 'Runs as a Harvis Build engine when enabled — connect an Anthropic API key or a Claude subscription token (no API credits needed).',
		commands: { install: 'curl -fsSL https://claude.ai/install.sh | bash', launch: 'claude', check: 'claude --version' },
		auth: {
			required: true,
			modes: ['api_key', 'oauth_token'],
			notes: 'Connect with an Anthropic API key OR a Claude subscription token (run `claude setup-token`). Stored encrypted, never shown; exactly one is injected at runtime.'
		},
		engine: {
			support: 'supported',
			notes: 'External Build engine via the Claude Code CLI in an isolated sidecar — per-user auth (API key or Claude subscription).'
		},
		links: { docs: 'https://code.claude.com/docs/en/', homepage: 'https://www.anthropic.com' }
	},
	{
		id: 'codex-app',
		name: 'Codex CLI',
		category: 'application',
		description: 'OpenAI’s local terminal coding agent.',
		longDescription:
			'OpenAI Codex CLI is a local coding agent that runs in your terminal. It supports ChatGPT sign-in and API-key based authentication depending on the environment.',
		brandKey: 'openai',
		status: 'available',
		provider: 'OpenAI',
		capabilities: ['coding', 'tool_use', 'files', 'shell'],
		provides: ['code_engine_candidate'],
		usedBy: ['code'],
		permissions: ['Runs shell commands', 'Reads / writes repo files'],
		connect: 'engine_api_key',
		runtimeNote: 'Runs as a Harvis Build engine when enabled — connect your OpenAI API key (cloud GPT/Codex models).',
		commands: { install: 'curl -fsSL https://chatgpt.com/codex/install.sh | sh', launch: 'codex', check: 'codex --version' },
		auth: {
			required: true,
			modes: ['local_auth', 'api_key'],
			notes: 'Supports ChatGPT sign-in or an OpenAI API key. Harvis does not store OpenAI credentials in this release.'
		},
		engine: { support: 'planned' }
	},
	{
		id: 'kimi-api',
		name: 'Kimi (Moonshot)',
		category: 'application',
		description: 'Moonshot’s Kimi models as a cloud Build engine and chat provider.',
		longDescription:
			'Moonshot AI’s Kimi models (K3, K2.6, K2.5) run as a cloud Build engine and a selectable chat model. Kimi reasons and responds directly in the thread — it has no clone/diff runner. Connect your Moonshot API key; it’s stored encrypted per-user, never shown, and injected only at request time.',
		brandKey: 'kimi',
		status: 'available',
		provider: 'Moonshot AI',
		capabilities: ['reasoning', 'chat', 'long_context'],
		provides: ['code_engine_candidate'],
		usedBy: ['chat', 'code'],
		connect: 'user_api_key',
		providerKey: 'moonshot',
		runtimeNote: 'Cloud engine — reasons and responds in the thread (Moonshot). No clone or diff. ~5× the cost of local models on K3.',
		auth: {
			required: true,
			modes: ['api_key'],
			notes: 'Your Moonshot API key (platform.moonshot.ai / .cn). Stored encrypted per-user, never shown; used only to call the Kimi API.'
		},
		engine: {
			support: 'supported',
			notes: 'Cloud reasoning engine — surfaced as moonshot/kimi-* models; picked in Build via the model selector.'
		},
		links: { homepage: 'https://www.moonshot.ai' }
	},
	{
		// SEPARATE PRODUCT from 'kimi-api' above, deliberately its own tile: that one is a
		// Moonshot developer-platform key on a pay-as-you-go balance; this one is a Kimi Code
		// membership key. Different console, different key namespace, different bill — pasting
		// one into the other authenticates against the wrong service and 401s.
		id: 'kimi-code',
		name: 'Kimi Code (Membership)',
		category: 'application',
		description: 'Your Kimi Code subscription driving the Claude Code tool loop.',
		longDescription:
			'Kimi Code is Moonshot’s subscription coding product. It serves an Anthropic-compatible API, so Harvis runs it through the same Claude Code sidecar and the same agentic loop — reading files, editing code, running commands, and streaming the diff back — with Kimi supplying the reasoning. Usage draws on your membership allowance, not pay-as-you-go credits. Use the key from the Kimi Code Console (kimi.com/coding); a Moonshot developer-platform key will not work here.',
		brandKey: 'kimi',
		status: 'available',
		provider: 'Moonshot AI',
		capabilities: ['coding', 'tool_use', 'files', 'shell', 'long_context'],
		provides: ['code_engine_candidate'],
		usedBy: ['chat', 'code'],
		permissions: ['Runs shell commands', 'Reads / writes repo files'],
		connect: 'engine_api_key',
		runtimeNote:
			'Runs in the Claude Code sidecar with the endpoint pointed at Kimi Code — full tool loop, clone + diff, zero GPU. Billed to your Kimi membership.',
		auth: {
			required: true,
			modes: ['api_key'],
			notes:
				'The API key created in the Kimi Code Console (kimi.com/coding). Uses your Kimi membership quota. Stored encrypted per-user, never shown; injected only at run time.'
		},
		engine: {
			support: 'supported',
			notes: 'External Build engine — surfaced as kimi-code/* models; picked in Build via the model selector.'
		},
		links: { docs: 'https://www.kimi.com/coding', homepage: 'https://www.kimi.com' }
	},
	{
		id: 'openclaw',
		name: 'OpenClaw',
		category: 'application',
		description: 'Harvis’s isolated agent runtime for file, shell, and repo workflows.',
		longDescription:
			'The internal Harvis agent runtime. It executes multi-step tool-calling tasks through the OpenClaw gateway in an isolated workspace pod — file edits, shell, git, and repo work.',
		brandKey: 'openclaw',
		status: 'available',
		provider: 'Open source',
		recommended: true,
		capabilities: ['coding', 'tool_use', 'multi-step'],
		provides: ['agent_runtime', 'tool_runtime', 'code_engine_candidate'],
		usedBy: ['chat', 'code', 'agent_studio'],
		runtimeNote: 'Live runtime — primary Harvis workspace agent.',
		connect: 'openclaw_byo',
		permissions: ['Runs shell in a sandbox pod', 'Reads / writes repo files'],
		commands: { check: 'curl http://openclaw:18789/health' },
		auth: { required: false, modes: ['config_file'], notes: 'Managed by the Harvis backend through OPENCLAW_URL and OPENCLAW_GATEWAY_TOKEN.' },
		engine: { support: 'supported', notes: 'Primary Harvis workspace runtime.' },
		detect: { serviceKey: 'openclaw' }
	},
	{
		id: 'hermes-agent',
		name: 'Hermes Agent',
		category: 'service',
		description: 'Full Hermes Agent runtime for Build & Chat — isolated sidecar, local Ollama, no credentials.',
		longDescription:
			'Hermes Agent is the full Nous Research agent runtime running inside Harvis — it uses its own tools, memory, skills and profile system, while Harvis keeps control of workspace safety, RunView, Stop and diff capture. It runs in an isolated sidecar on local Ollama, with no cloud credentials. (A lighter experimental "Hermes Native" in-process engine is also available under its own flag.)',
		brandKey: 'hermes',
		status: 'available',
		provider: 'Nous Research (Hermes Agent, MIT)',
		capabilities: ['agent_runtime', 'local_models', 'build_engine'],
		provides: ['model_provider', 'agent_runtime'],
		usedBy: ['chat', 'code'],
		runtimeNote: 'Runs the real Hermes Agent app as a Harvis Build engine (isolated sidecar, local Ollama, no credentials) when enabled.',
		auth: { required: false, modes: ['ollama'] },
		connect: 'hermes_agent',
		// Detect on the SIDECAR (engine), not the 'hermes' Ollama-model count — so the card reads
		// "Hermes Agent app ready", not "N models". (E4B: this is the app runtime, not a model.)
		detect: { serviceKey: 'hermes-agent' }
	},
	{
		id: 'opencode',
		name: 'OpenCode',
		category: 'application',
		description: 'Terminal-oriented coding agent for local and repo workflows.',
		longDescription:
			'A terminal-oriented coding agent for local and repo workflows — files, shell, git, and diffs. The leading candidate for the first external Code engine adapter.',
		brandKey: 'opencode',
		status: 'available',
		provider: 'Open source',
		recommended: true,
		capabilities: ['files', 'shell', 'git', 'diff'],
		provides: ['code_engine_candidate'],
		usedBy: ['code'],
		runtimeNote: 'Runs as the Harvis OpenCode engine when enabled (local Ollama models, clone-mode Build sessions).',
		permissions: ['Runs shell commands', 'Reads / writes repo files'],
		commands: { install: 'curl -fsSL https://opencode.ai/install | bash', launch: 'opencode', check: 'opencode --version' },
		auth: { required: false, modes: ['ollama', 'api_key', 'config_file'] },
		engine: { support: 'candidate', notes: 'Good candidate for the first external Code engine adapter.' },
		links: { docs: 'https://opencode.ai/docs/', homepage: 'https://opencode.ai' }
	},

	// ── Cloud APIs (free-tier chat providers, BYO key) ──
	// Every one of these publishes a real free tier and speaks the OpenAI Chat Completions wire
	// format, so Harvis talks to them DIRECTLY with the user's own key — no gateway, no shared
	// credential pool. Model lists are DISCOVERED from the vendor after the key verifies, never
	// hardcoded here: these catalogs rotate monthly and a baked list would start lying. Mirrors
	// python_back_end/owui_compat/free_providers.py — the ids and engines must match that table.
	{
		id: 'groq-api',
		name: 'Groq',
		category: 'model',
		description: 'Free-tier Llama and GPT-OSS models on Groq’s LPU inference.',
		longDescription:
			'Groq serves open models on custom LPU hardware — the fastest token throughput of the free providers. Connect a free API key and Groq’s chat models appear in the Harvis model picker alongside your local ones.',
		brandKey: 'cloud-api',
		status: 'available',
		provider: 'Groq',
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'groq',
		detect: { serviceKey: 'groq' },
		keyConsoleUrl: 'https://console.groq.com/keys',
		keyHelp:
			'Your Groq API key — used only to list and run Groq chat models, stored encrypted, never shown. Free tier: high daily request limits.',
		auth: { required: true, modes: ['api_key'] },
		links: { docs: 'https://console.groq.com/docs', homepage: 'https://groq.com' }
	},
	{
		id: 'cerebras-api',
		name: 'Cerebras',
		category: 'model',
		description: 'Free-tier open models with the fastest time-to-first-token.',
		longDescription:
			'Cerebras runs open models on wafer-scale hardware. The free tier is roughly 1M tokens a day at 30 requests a minute — enough for real interactive use, not just a demo.',
		brandKey: 'cloud-api',
		status: 'available',
		provider: 'Cerebras',
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'cerebras',
		detect: { serviceKey: 'cerebras' },
		keyConsoleUrl: 'https://cloud.cerebras.ai/',
		keyHelp:
			'Your Cerebras API key — used only to list and run Cerebras chat models, stored encrypted, never shown. Free tier: ~1M tokens/day.',
		auth: { required: true, modes: ['api_key'] },
		links: { docs: 'https://inference-docs.cerebras.ai', homepage: 'https://cerebras.ai' }
	},
	{
		id: 'gemini-api',
		name: 'Google Gemini',
		category: 'model',
		description: 'Free-tier Gemini Flash models with long context, via AI Studio.',
		longDescription:
			'Google AI Studio issues a free API key with generous daily limits on the Flash models and a very large context window. Harvis calls Gemini through its OpenAI-compatible endpoint with your own key.',
		brandKey: 'cloud-api',
		status: 'available',
		provider: 'Google',
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'gemini',
		detect: { serviceKey: 'gemini' },
		keyConsoleUrl: 'https://aistudio.google.com/apikey',
		keyHelp:
			'Your Google AI Studio key — used only to list and run Gemini chat models, stored encrypted, never shown. Free tier: generous daily limits on Flash.',
		auth: { required: true, modes: ['api_key'] },
		links: { docs: 'https://ai.google.dev/gemini-api/docs', homepage: 'https://aistudio.google.com' }
	},
	{
		id: 'nvidia-api',
		name: 'NVIDIA NIM',
		category: 'model',
		description: 'Free inference credits across 70+ hosted open models.',
		longDescription:
			'NVIDIA build.nvidia.com hosts a large catalog of open models behind one OpenAI-compatible endpoint, with free inference credits on signup. Useful when you want to try a model you can’t run locally.',
		brandKey: 'cloud-api',
		status: 'available',
		provider: 'NVIDIA',
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'nvidia',
		detect: { serviceKey: 'nvidia' },
		keyConsoleUrl: 'https://build.nvidia.com/',
		keyHelp:
			'Your NVIDIA API key — used only to list and run NIM chat models, stored encrypted, never shown. Free tier: inference credits.',
		auth: { required: true, modes: ['api_key'] },
		links: { docs: 'https://docs.nvidia.com/nim/', homepage: 'https://build.nvidia.com' }
	},
	{
		id: 'mistral-api',
		name: 'Mistral',
		category: 'model',
		description: 'Free “Experiment” tier — large monthly token allowance.',
		longDescription:
			'Mistral’s free Experiment tier gives a large monthly token allowance across their chat and code models. Signup requires phone verification.',
		brandKey: 'cloud-api',
		status: 'available',
		provider: 'Mistral AI',
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'mistral',
		detect: { serviceKey: 'mistral' },
		keyConsoleUrl: 'https://console.mistral.ai/api-keys/',
		keyHelp:
			'Your Mistral API key — used only to list and run Mistral chat models, stored encrypted, never shown. Free tier requires phone verification.',
		auth: { required: true, modes: ['api_key'] },
		links: { docs: 'https://docs.mistral.ai', homepage: 'https://mistral.ai' }
	},

	// ── Services (connections) ──
	{
		id: 'ollama',
		name: 'Ollama',
		category: 'service',
		description: 'Serves local LLMs for chat, agents, and embeddings.',
		longDescription:
			'The local model server. Powers chat, coding agents, and embeddings on your hardware.',
		brandKey: 'ollama',
		status: 'available',
		provider: 'Ollama',
		recommended: true,
		provides: ['model_provider'],
		usedBy: ['chat', 'code', 'notebook', 'agent_studio'],
		commands: { check: 'curl $OLLAMA_URL/api/tags' },
		href: '/harvis/agent-studio/cookbook',
		auth: { required: false, modes: ['ollama'] },
		detect: { serviceKey: 'ollama' },
		links: { docs: 'https://ollama.com/docs', homepage: 'https://ollama.com' }
	},
	{
		id: 'github',
		name: 'GitHub',
		category: 'service',
		description: 'Clone repositories, review diffs, and open pull requests.',
		longDescription:
			'Connect GitHub to clone repos, review diffs, and open pull requests from VibeCode / Code mode.',
		brandKey: 'github',
		status: 'needs_setup',
		provider: 'GitHub',
		provides: ['repo_provider', 'pr_provider'],
		usedBy: ['code', 'automations', 'agent_studio'],
		connect: 'github_oauth',
		href: '/harvis/vibecode',
		auth: { required: true, modes: ['oauth', 'api_key'], notes: 'Connect via GitHub OAuth or a personal access token.' },
		detect: { serviceKey: 'github' },
		links: { docs: 'https://docs.github.com', homepage: 'https://github.com' }
	},
	{
		id: 'mcp',
		name: 'Custom Tool / MCP',
		category: 'service',
		description: 'Connect Model Context Protocol servers and custom tools.',
		longDescription:
			'MCP is an open standard for connecting AI applications to external systems. Use it to add custom tools, data sources, and workflows to Harvis agents.',
		brandKey: 'mcp',
		status: 'available',
		provides: ['tool_provider'],
		usedBy: ['chat', 'agent_studio', 'automations'],
		runtimeNote: 'Registered; agent-runtime wiring planned.',
		connect: 'mcp_link',
		href: '/harvis/agent-studio/customize',
		auth: { required: false, modes: ['config_file'] },
		detect: { serviceKey: 'mcp' },
		links: { docs: 'https://modelcontextprotocol.io/docs/getting-started/intro', homepage: 'https://modelcontextprotocol.io' }
	},
	{
		id: 'discord',
		name: 'Discord',
		category: 'service',
		description: 'The same Harvis agent, reachable from a Discord channel.',
		longDescription: 'Reach the same Harvis agent from a Discord channel.',
		brandKey: 'discord',
		status: 'available',
		provides: ['notification_provider'],
		usedBy: ['automations'],
		runtimeNote: 'Configured at the deploy level (bot token in the server environment).',
		auth: { required: true, modes: ['api_key'], notes: 'Configured via a Discord bot token in the server environment.' },
		detect: { serviceKey: 'discord' },
		links: { docs: 'https://discord.com/developers/docs/intro', homepage: 'https://discord.com/developers/applications' }
	},
	{
		id: 'ssh',
		name: 'SSH',
		category: 'service',
		description: 'Run agents and tools against a remote host over SSH.',
		longDescription:
			'Run agents and tools against a remote host over SSH. (Connection setup is a later phase.)',
		brandKey: 'ssh',
		status: 'coming_soon',
		provides: ['remote_execution_target'],
		usedBy: ['code'],
		commands: { check: 'ssh user@host' },
		auth: { required: true, modes: ['config_file'], notes: 'Host + key reference; a safe key store is a later phase.' }
	},

	// ── Integration Packs (recipes) ──
	{
		id: 'pack-local-coder',
		name: 'Local Coding Setup',
		category: 'pack',
		description: 'OpenCode + Ollama — a ready local coding stack.',
		longDescription:
			'A plug-and-play local coding stack: pair OpenCode with your local models, served by Ollama. Open each piece to set it up.',
		brandKey: 'pack',
		status: 'available',
		capabilities: ['coding', 'files', 'shell', 'git'],
		usedBy: ['code']
	},
	{
		id: 'pack-repo-review',
		name: 'Repo Review',
		category: 'pack',
		description: 'GitHub + OpenClaw — clone, review, and open PRs.',
		longDescription:
			'A repo-review recipe: connect GitHub, run OpenClaw to read the diff and propose changes, then open a PR.',
		brandKey: 'pack',
		status: 'available',
		capabilities: ['git', 'multi-step', 'tool_use'],
		usedBy: ['code', 'agent_studio']
	}
];

// ───────────────────────────────────────────────────────────── helpers

// Models intentionally NOT in the rendered order this pass (kept in the type for later).
const CATEGORY_ORDER: IntegrationCategory[] = ['application', 'service', 'pack'];

export const CATEGORY_LABEL: Record<IntegrationCategory, string> = {
	application: 'Applications',
	model: 'Models',
	service: 'Services',
	pack: 'Integration Packs'
};

export const STATUS_META: Record<IntegrationStatus, { label: string; dot: string; text: string }> = {
	ready: { label: 'Ready', dot: 'bg-green-500', text: 'text-green-600 dark:text-green-400' },
	running: { label: 'Running', dot: 'bg-blue-500', text: 'text-blue-600 dark:text-blue-400' },
	needs_setup: { label: 'Needs setup', dot: 'bg-amber-500', text: 'text-amber-600 dark:text-amber-400' },
	available: { label: 'Available', dot: 'bg-gray-400', text: 'text-gray-500 dark:text-gray-400' },
	coming_soon: { label: 'Coming soon', dot: 'bg-slate-400', text: 'text-slate-500 dark:text-slate-400' },
	error: { label: 'Error', dot: 'bg-red-500', text: 'text-red-600 dark:text-red-400' }
};

// Engine-support display.
export const ENGINE_LABEL: Record<EngineSupport, string> = {
	none: 'Not planned',
	planned: 'Planned',
	candidate: 'Engine candidate',
	supported: 'Supported'
};

export const AUTH_LABEL: Record<AuthMode, string> = {
	none: 'None',
	api_key: 'API key',
	local_auth: 'Local sign-in / session',
	oauth: 'OAuth',
	config_file: 'Config file',
	ollama: 'Ollama',
	custom: 'Custom'
};

// Capabilities a user picks a preferred provider for → drives the "Save preference" button.
// Defined here (not capabilities.ts) so actionsFor can use it without a runtime import cycle.
export const PREFERABLE_CAPABILITIES: IntegrationCapability[] = [
	'model_provider',
	'code_engine_candidate',
	'agent_runtime',
	'tool_runtime',
	'workflow_runtime',
	'research_runtime'
];

// Per-brand color so icons aren't a wall of blue. tile = bg+border classes, icon = text color.
// Brands with a real vendored logo (static/integrations/<key>.svg) sit on a uniform dark
// logo-chip so the white/colored marks read in any theme. Custom-glyph brands keep a
// brand-tinted tile (their inline SVG uses currentColor = the `icon` color).
const LOGO_TILE = 'bg-[#0e1320] border-white/10';
export const BRAND_TONE: Record<string, { icon: string; tile: string }> = {
	claude: { icon: '', tile: LOGO_TILE },
	openai: { icon: '', tile: LOGO_TILE },
	ollama: { icon: '', tile: LOGO_TILE },
	github: { icon: '', tile: LOGO_TILE },
	discord: { icon: '', tile: LOGO_TILE },
	mcp: { icon: '', tile: LOGO_TILE },
	opencode: { icon: '', tile: LOGO_TILE },
	openclaw: { icon: '', tile: LOGO_TILE },
	hermes: { icon: '', tile: LOGO_TILE },
	kimi: { icon: 'text-indigo-400', tile: 'bg-indigo-500/10 border-indigo-500/25' },
	ssh: { icon: 'text-emerald-400', tile: 'bg-emerald-500/10 border-emerald-500/25' },
	harvis: { icon: 'text-blue-400', tile: 'bg-blue-500/15 border-blue-500/30' },
	pack: { icon: 'text-blue-400', tile: 'bg-blue-500/10 border-blue-500/25' }
};
export const toneFor = (brandKey: string) =>
	BRAND_TONE[brandKey] ?? { icon: 'text-blue-400', tile: 'bg-blue-500/10 border-blue-500/25' };

// Substitute the {{model}} token. Pure string replace — NEVER executed. With no model the
// literal {{model}} placeholder is preserved (copy-as-is; the user fills their model).
export function applyTemplate(cmd?: string, model?: string): string {
	if (!cmd) return '';
	return cmd.replace(/\{\{\s*model\s*\}\}/g, model || '{{model}}');
}

export function orderedCategories(): IntegrationCategory[] {
	return [...CATEGORY_ORDER];
}

export function filterCatalog(defs: IntegrationDefinition[], query: string): IntegrationDefinition[] {
	const q = query.trim().toLowerCase();
	if (!q) return defs;
	return defs.filter((d) =>
		[d.name, d.description, d.provider, ...(d.capabilities ?? []), ...(d.provides ?? []), ...(d.usedBy ?? [])]
			.filter(Boolean)
			.join(' ')
			.toLowerCase()
			.includes(q)
	);
}

// Live detection overrides the static baseline. Fail-closed: null `live` keeps the baseline;
// we never invent a 'ready'. Applications / packs keep static (the Phase-2 runner seam).
export function mergeLiveStatus(
	defs: IntegrationDefinition[],
	live: LiveStatus | null
): IntegrationDefinition[] {
	if (!live) return defs.map((d) => ({ ...d }));
	return defs.map((d) => {
		const next = { ...d };
		if (d.detect?.serviceKey && live.services?.[d.detect.serviceKey]) {
			const s = live.services[d.detect.serviceKey];
			next.status = s.status;
			next.detail = s.detail;
		}
		return next;
	});
}

const SAVE_PREFERENCE_TIP =
	'Saves this as your preferred provider for its capabilities. Surfaces will use this later (no effect yet).';

// The action set for a card / row / modal.
export function actionsFor(def: IntegrationDefinition): IntegrationAction[] {
	const a: IntegrationAction[] = [];
	if (def.category === 'application') {
		if (def.commands?.launch) {
			a.push({ id: 'copy_launch', label: 'Copy command', kind: 'copy', command: 'launch', primary: true });
		} else if (def.commands?.install) {
			a.push({ id: 'copy_install', label: 'Copy install', kind: 'copy', command: 'install', primary: true });
		}
	} else if (def.category === 'service') {
		if (def.href) a.push({ id: 'manage', label: 'Manage', kind: 'link', href: def.href, primary: true });
		if (def.commands?.check && !def.href) a.push({ id: 'copy_check', label: 'Copy check', kind: 'copy', command: 'check' });
	} else if (def.category === 'pack') {
		a.push({ id: 'detail', label: 'View details', kind: 'detail', primary: true });
	}
	// Generic, capability-first preference — shown for any preferable-capability provider.
	if ((def.provides ?? []).some((c) => PREFERABLE_CAPABILITIES.includes(c))) {
		a.push({ id: 'save_preference', label: 'Save preference', kind: 'save_preference', title: SAVE_PREFERENCE_TIP });
	}
	return a;
}
