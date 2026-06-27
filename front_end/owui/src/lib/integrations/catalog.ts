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
	connect?: 'openclaw_byo' | 'github_oauth' | 'mcp_link'; // Phase B: which in-modal connect flow
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
			'Anthropic’s terminal-native coding agent. In a future release Harvis can drive an installed, user-authenticated Claude Code as an external Code engine — reading the repo, running tasks, and streaming diffs back into Vibe Code.',
		brandKey: 'claude',
		status: 'available',
		provider: 'Anthropic',
		capabilities: ['coding', 'tool_use', 'planning', 'files', 'shell'],
		provides: ['code_engine_candidate'],
		usedBy: ['code'],
		permissions: ['Runs shell commands', 'Reads / writes repo files'],
		runtimeNote: 'External CLI — install on your machine; Harvis can’t launch it from Build yet.',
		commands: { install: 'curl -fsSL https://claude.ai/install.sh | bash', launch: 'claude', check: 'claude --version' },
		auth: {
			required: true,
			modes: ['local_auth', 'api_key'],
			notes: 'Uses your local Claude Code sign-in/session or Anthropic credentials. Harvis does not store Claude credentials in this release.'
		},
		engine: {
			support: 'planned',
			notes: 'Future external engine via an installed + authenticated Claude Code CLI / SDK.'
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
		runtimeNote: 'External CLI — install on your machine; Harvis can’t launch it from Build yet.',
		commands: { install: 'curl -fsSL https://chatgpt.com/codex/install.sh | sh', launch: 'codex', check: 'codex --version' },
		auth: {
			required: true,
			modes: ['local_auth', 'api_key'],
			notes: 'Supports ChatGPT sign-in or an OpenAI API key. Harvis does not store OpenAI credentials in this release.'
		},
		engine: { support: 'planned' }
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
		name: 'Hermes',
		category: 'service',
		description: 'Model router / local model family used by Harvis routing.',
		longDescription:
			'Hermes is treated as a routing/model integration in Harvis. The live status is ready when a Hermes model is available through Ollama.',
		brandKey: 'hermes',
		status: 'available',
		provider: 'Nous Research / local models',
		capabilities: ['model_routing', 'local_models'],
		provides: ['model_provider'],
		usedBy: ['chat', 'code', 'notebook', 'agent_studio'],
		runtimeNote: 'Models served via Ollama, not a separate daemon.',
		auth: { required: false, modes: ['ollama'] },
		detect: { serviceKey: 'hermes' }
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
