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

// A single tile can front more than one way to connect the SAME vendor — Kimi is the case that
// forced this: a Kimi Code membership key drives the Claude Code sidecar's tool loop, while a
// Moonshot platform key is pay-as-you-go cloud chat. Same brand, same tile, two credentials.
// A variant supplies the connect flow and the credential target; the detail drawer renders a
// toggle and hands the chosen variant's overrides to ConnectionPanel.
export interface IntegrationVariant {
	key: string; // stable, used as the toggle value
	label: string; // toggle button text
	tagline: string; // one line: which key, and which console it comes from
	connect: NonNullable<IntegrationDefinition['connect']>;
	providerKey?: string; // connect:'user_api_key' — the /api/user/api-keys provider_name
	engineAuthKey?: string; // connect:'engine_api_key' — the engine-auth row (owui_compat/engine_auth.py)
	runtimeNote?: string;
	// An EMPTY array is meaningful, not missing: this mode grants nothing, so the section hides.
	// (A cloud key that only answers in the thread must not advertise shell + repo access.)
	permissions?: string[];
	auth?: IntegrationDefinition['auth'];
	engine?: IntegrationDefinition['engine'];
	links?: { docs?: string; homepage?: string };
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
	variants?: IntegrationVariant[]; // >1 way to connect the same vendor (see IntegrationVariant); [0] is the default
	// For connect:'engine_api_key' — the `user_engine_auth.engine` id this card's key is stored
	// under (the {engine} path segment of /api/owui/engine-auth/{engine}). Authored per card
	// instead of inferred, so adding a provider is a catalog row and nothing more. A multi-mode
	// tile overrides this per-variant via IntegrationVariant.engineAuthKey, which still wins.
	authEngine?: string;
	keyConsoleUrl?: string; // where the user creates that key (rendered as a link, never auto-opened)
	keyHelp?: string; // one honest line under the key field: what this key is used for
	// The vendor's free allowance, stated plainly. Its PRESENCE is the signal that this provider
	// costs nothing to try — the Engines tab reads it to build the free-key guide.
	freeTier?: string;
	// The same allowance broken into the two or three numbers a user actually compares before
	// picking one. Rendered as chips next to `freeTier`. Separate from the prose because "1M
	// tokens/day" is a fact you scan, not a sentence you read.
	freeLimits?: string[];
	// What the vendor demands before it will issue the key — the thing that makes someone
	// abandon a signup halfway. Stated up front so nobody discovers it on the vendor's site.
	signupRequires?: string;
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
		// ONE Kimi tile, TWO ways in (see `variants`). These are genuinely different products that
		// happen to share a brand:
		//   · membership — a Kimi Code Console key (kimi.com/coding). Anthropic-compatible, so Harvis
		//     drives it through the Claude Code sidecar: full tool loop, clone + diff. Membership quota.
		//   · platform   — a Moonshot developer-platform key (platform.moonshot.ai). Cloud chat and
		//     reasoning in the thread, no clone/diff runner. Pay-as-you-go balance.
		// Different console, different key namespace, different bill — pasting one into the other
		// authenticates against the wrong service and 401s, which is why each variant's tagline names
		// the console its key comes from instead of just saying "API key". They were two tiles until
		// 2026-07-29; users read them as duplicates, so the toggle now carries the distinction.
		id: 'kimi',
		name: 'Kimi (Moonshot)',
		category: 'application',
		description: 'Moonshot’s Kimi — membership coding engine or pay-as-you-go cloud models.',
		longDescription:
			'Moonshot AI’s Kimi, connected either way you buy it. Pick “Kimi Code (membership)” and Harvis runs Kimi inside the Claude Code sidecar — the full agentic loop, reading files, editing code, running commands and streaming the diff back — billed against your membership allowance. Pick “Moonshot platform” and the Kimi models (K3, K2.6, K2.5) become a cloud chat provider and Build engine that reasons and responds in the thread, billed pay-as-you-go. Either key is stored encrypted per-user, never shown, and injected only at run time.',
		brandKey: 'kimi',
		status: 'available',
		provider: 'Moonshot AI',
		capabilities: ['coding', 'reasoning', 'tool_use', 'files', 'shell', 'long_context'],
		provides: ['code_engine_candidate'],
		usedBy: ['chat', 'code'],
		// Baseline = variants[0] (membership), same reason as `connect` below. Each variant overrides it:
		// only the membership mode runs a tool loop, so only it asks for shell + repo.
		permissions: ['Runs shell commands', 'Reads / writes repo files'],
		// Baseline flow = variants[0]. Kept in sync so the `def.connect` gates (which decide whether
		// ConnectionPanel renders at all) still hold for callers that don't know about variants.
		connect: 'engine_api_key',
		runtimeNote:
			'Two connect modes below — membership runs the full tool loop in the Claude Code sidecar; the Moonshot platform key is cloud chat/reasoning with no clone or diff.',
		auth: {
			required: true,
			modes: ['api_key'],
			notes: 'One API key, from whichever console matches the mode you pick below. Stored encrypted per-user, never shown.'
		},
		engine: {
			support: 'supported',
			notes: 'Both modes are selectable Build engines — kimi-code/* (membership) and moonshot/kimi-* (platform).'
		},
		links: { docs: 'https://www.kimi.com/coding', homepage: 'https://www.moonshot.ai' },
		variants: [
			{
				key: 'membership',
				label: 'Kimi Code (membership)',
				tagline: 'A subscription key from the Kimi Code Console — kimi.com/coding.',
				connect: 'engine_api_key',
				engineAuthKey: 'kimi-code',
				runtimeNote:
					'Runs in the Claude Code sidecar with the endpoint pointed at Kimi Code — full tool loop, clone + diff, zero GPU. Billed to your Kimi membership.',
				permissions: ['Runs shell commands', 'Reads / writes repo files'],
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
				key: 'platform',
				label: 'Moonshot platform',
				tagline: 'A pay-as-you-go developer key from platform.moonshot.ai (or .cn).',
				connect: 'user_api_key',
				providerKey: 'moonshot',
				runtimeNote:
					'Cloud engine — reasons and responds in the thread (Moonshot). No clone or diff. ~5× the cost of local models on K3.',
				permissions: [], // no runner: the key only calls the Kimi API, so nothing to grant
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
			}
		]
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

	// ── Free-tier cloud model providers ──────────────────────────────────────────────────
	// Six endpoints that publish a real free tier and speak OpenAI Chat Completions, so Harvis
	// calls them DIRECTLY with the user's own key — no shared key pool, ever. Five are the
	// vendor's own API; OpenRouter is an aggregator, which is a difference the user is told
	// about on its card rather than one hidden here. Each `id` pairs with a row in
	// python_back_end/owui_compat/free_providers.py; `authEngine` MUST equal that row's
	// `engine` or the key lands where nothing reads it.
	//
	// No `detect.serviceKey`: there is no service to probe. Status comes from whether this user
	// has a verified key, which integrations_status.py reports per provider.
	//
	// Model lists are deliberately absent. These vendors rotate models constantly and the
	// backend discovers them from the live key, so a list here would be a lie with a shelf life.
	{
		id: 'groq-api',
		name: 'Groq',
		category: 'model',
		description: 'Free, very fast inference on Llama and GPT-OSS models.',
		longDescription:
			'Groq runs open models on its own LPU silicon, which makes it the fastest of the free providers by a wide margin — tokens arrive faster than most local hardware can manage. The free tier covers a high number of requests per day at no cost and needs no card. Create a key in the Groq Console, paste it below, and Groq models appear in the chat model picker.',
		brandKey: 'groq',
		status: 'available',
		provider: 'Groq',
		capabilities: ['chat', 'reasoning', 'fast'],
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'groq',
		detect: { serviceKey: 'groq' },
		keyConsoleUrl: 'https://console.groq.com/keys',
		keyHelp:
			'Your Groq API key. Stored encrypted per-user, never shown, and sent only to api.groq.com when you pick a Groq model.',
		freeTier: 'Free: high daily request limits on Llama and GPT-OSS models. No card required.',
		freeLimits: ['~1k requests/day', '30 requests/min', 'No card'],
		signupRequires: 'Email, Google, or GitHub sign-in',
		runtimeNote: 'Cloud chat provider — answers in the thread. No clone, diff, or shell.',
		auth: { required: true, modes: ['api_key'] },
		engine: { support: 'none' },
		links: { docs: 'https://console.groq.com/docs', homepage: 'https://groq.com' }
	},
	{
		id: 'cerebras-api',
		name: 'Cerebras',
		category: 'model',
		description: 'Free daily token allowance with the quickest first token.',
		longDescription:
			'Cerebras serves open models from wafer-scale hardware. Its free tier is measured in tokens per day rather than requests, and it has the shortest time-to-first-token of the free providers — the answer starts appearing almost immediately. Create a key in Cerebras Cloud and paste it below.',
		brandKey: 'cerebras',
		status: 'available',
		provider: 'Cerebras',
		capabilities: ['chat', 'fast'],
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'cerebras',
		detect: { serviceKey: 'cerebras' },
		keyConsoleUrl: 'https://cloud.cerebras.ai/',
		keyHelp:
			'Your Cerebras API key. Stored encrypted per-user, never shown, and sent only to api.cerebras.ai when you pick a Cerebras model.',
		freeTier: 'Free: roughly 1M tokens per day, 30 requests per minute.',
		freeLimits: ['~1M tokens/day', '30 requests/min', 'No card'],
		signupRequires: 'Email or Google sign-in',
		runtimeNote: 'Cloud chat provider — answers in the thread. No clone, diff, or shell.',
		auth: { required: true, modes: ['api_key'] },
		engine: { support: 'none' },
		links: { docs: 'https://inference-docs.cerebras.ai', homepage: 'https://cerebras.ai' }
	},
	{
		id: 'gemini-api',
		name: 'Google Gemini',
		category: 'model',
		description: 'Free Gemini Flash models with very long context.',
		longDescription:
			'Google AI Studio hands out a free API key for the Gemini models. The Flash tier is the practical one: generous daily request limits, a very large context window, and image input. Harvis talks to Google’s OpenAI-compatible endpoint, so it behaves like every other provider here. Create a key in AI Studio and paste it below.',
		brandKey: 'gemini',
		status: 'available',
		provider: 'Google',
		capabilities: ['chat', 'vision', 'long_context'],
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'gemini',
		detect: { serviceKey: 'gemini' },
		keyConsoleUrl: 'https://aistudio.google.com/apikey',
		keyHelp:
			'Your Google AI Studio key. Stored encrypted per-user, never shown, and sent only to generativelanguage.googleapis.com when you pick a Gemini model.',
		freeTier: 'Free via AI Studio: generous daily request limits on Flash models, long context.',
		freeLimits: ['1M-token context', 'Image input', 'No card'],
		signupRequires: 'A Google account',
		runtimeNote:
			'Cloud chat provider — answers in the thread. Token counts are not reported on streamed replies (Google’s compatible endpoint omits them).',
		auth: { required: true, modes: ['api_key'] },
		engine: { support: 'none' },
		links: { docs: 'https://ai.google.dev/gemini-api/docs', homepage: 'https://aistudio.google.com' }
	},
	{
		id: 'nvidia-api',
		name: 'NVIDIA NIM',
		category: 'model',
		description: 'Free credits across 70+ hosted open models.',
		longDescription:
			'NVIDIA build.nvidia.com hosts a large catalog of open models — Llama, Qwen, DeepSeek, Mistral and more — behind one OpenAI-compatible endpoint, and gives new accounts a block of free inference credits. It is the widest catalog of the five, which makes it the one to reach for when you want to try a specific open model without downloading it. Create a key at build.nvidia.com and paste it below.',
		brandKey: 'nvidia',
		status: 'available',
		provider: 'NVIDIA',
		capabilities: ['chat', 'reasoning', 'coding'],
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'nvidia',
		detect: { serviceKey: 'nvidia' },
		keyConsoleUrl: 'https://build.nvidia.com/',
		keyHelp:
			'Your NVIDIA NIM key. Stored encrypted per-user, never shown, and sent only to integrate.api.nvidia.com when you pick an NVIDIA model.',
		freeTier: 'Free: a block of inference credits across 70+ hosted open models.',
		freeLimits: ['70+ models', 'Credits, not a daily reset', 'No card'],
		signupRequires: 'An NVIDIA developer account (work email preferred)',
		runtimeNote: 'Cloud chat provider — answers in the thread. Credits are a one-time block, not a daily allowance — once spent the models stop appearing.',
		auth: { required: true, modes: ['api_key'] },
		engine: { support: 'none' },
		links: { docs: 'https://docs.api.nvidia.com', homepage: 'https://build.nvidia.com' }
	},
	{
		id: 'openrouter-api',
		name: 'OpenRouter',
		category: 'model',
		description: 'One key, ~20 free models from many vendors.',
		longDescription:
			'OpenRouter is an aggregator rather than a vendor: a single key reaches models from Google, NVIDIA, Z.ai and others through one API. Harvis lists only the models OpenRouter prices at zero — about twenty of its several hundred — so a free key never offers you something it will refuse to answer. Several carry very large context windows. Create a key on the Keys page and paste it below.',
		brandKey: 'openrouter',
		status: 'available',
		provider: 'OpenRouter',
		capabilities: ['chat'],
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'openrouter',
		detect: { serviceKey: 'openrouter' },
		keyConsoleUrl: 'https://openrouter.ai/keys',
		keyHelp:
			'Your OpenRouter API key. Stored encrypted per-user, never shown, and sent only to openrouter.ai when you pick an OpenRouter model.',
		freeTier: 'Free: the zero-priced slice of the catalogue, capped by requests per day.',
		freeLimits: ['~20 free models', 'Daily request cap', 'No card'],
		signupRequires: 'Email, Google or GitHub sign-in',
		runtimeNote:
			'Cloud chat provider — answers in the thread. Only zero-priced models are listed; funding the account does not add paid ones to the picker.',
		auth: { required: true, modes: ['api_key'] },
		engine: { support: 'none' },
		links: { docs: 'https://openrouter.ai/docs', homepage: 'https://openrouter.ai' }
	},
	{
		id: 'mistral-api',
		name: 'Mistral',
		category: 'model',
		description: 'Free “Experiment” tier — needs phone verification.',
		longDescription:
			'Mistral’s free Experiment tier gives a large monthly token allowance on their own models, including the Codestral coding models. It is the only provider of the five that requires phone verification before it will issue a key. Create one in the Mistral console and paste it below.',
		brandKey: 'mistral',
		status: 'available',
		provider: 'Mistral AI',
		capabilities: ['chat', 'coding', 'reasoning'],
		provides: ['model_provider'],
		usedBy: ['chat'],
		connect: 'engine_api_key',
		authEngine: 'mistral',
		detect: { serviceKey: 'mistral' },
		keyConsoleUrl: 'https://console.mistral.ai/api-keys/',
		keyHelp:
			'Your Mistral API key. Stored encrypted per-user, never shown, and sent only to api.mistral.ai when you pick a Mistral model.',
		freeTier: 'Free “Experiment” tier: large monthly token allowance. Requires phone verification.',
		freeLimits: ['1 request/sec', 'Monthly token cap', 'Codestral included'],
		signupRequires: 'Phone verification — the only one of the five that does',
		runtimeNote: 'Cloud chat provider — answers in the thread. No clone, diff, or shell.',
		auth: { required: true, modes: ['api_key'] },
		engine: { support: 'none' },
		links: { docs: 'https://docs.mistral.ai', homepage: 'https://mistral.ai' }
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
	// Free providers now carry their real marks (BrandGlyph, currentColor), so `icon` is the
	// colour the logo is actually painted in — approximated to each vendor's own brand hue with
	// a Tailwind step light enough to hold contrast on the dark tile. Groq (#F55036) and Cerebras
	// (#F15A29) are near-identical oranges in real life; cerebras is nudged to amber so the two
	// stay tellable apart in a vertical list. Mistral's mark is a yellow→red gradient we can't
	// reproduce in one colour — rose takes the red end.
	groq: { icon: 'text-orange-400', tile: 'bg-orange-500/10 border-orange-500/25' },
	cerebras: { icon: 'text-amber-400', tile: 'bg-amber-500/10 border-amber-500/25' },
	gemini: { icon: 'text-sky-400', tile: 'bg-sky-500/10 border-sky-500/25' },
	nvidia: { icon: 'text-lime-400', tile: 'bg-lime-500/10 border-lime-500/25' },
	mistral: { icon: 'text-rose-400', tile: 'bg-rose-500/10 border-rose-500/25' },
	openrouter: { icon: 'text-violet-400', tile: 'bg-violet-500/10 border-violet-500/25' },
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
