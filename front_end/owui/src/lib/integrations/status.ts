// Control-panel normalization layer for the Integrations tab.
//
// The catalog/registry use a wide internal vocabulary (status: available/ready/running/needs_setup/
// coming_soon/error  ×  source: static/detected/configured  ×  engine_readiness reasons). The UI
// should speak ONE clean status system. This module translates all of that into the 6 normalized
// labels and groups integrations by PURPOSE, plus the Connect-vs-Default helpers.

import type { IntegrationDefinition, IntegrationCapability } from './catalog';
import { PREFERABLE_CAPABILITIES } from './catalog';
import { deriveSource } from './capabilities';

// ── Normalized status (the only labels the UI shows) ────────────────────────────────────
export type NormStatus = 'ready' | 'connected' | 'needs_setup' | 'disabled' | 'unavailable' | 'error';

export const NORM_META: Record<NormStatus, { label: string; dot: string; text: string; ring: string }> = {
	ready: { label: 'Ready', dot: 'bg-green-500', text: 'text-green-600 dark:text-green-400', ring: 'ring-green-500/20' },
	connected: { label: 'Connected', dot: 'bg-blue-500', text: 'text-blue-600 dark:text-blue-400', ring: 'ring-blue-500/20' },
	needs_setup: { label: 'Needs setup', dot: 'bg-amber-500', text: 'text-amber-600 dark:text-amber-400', ring: 'ring-amber-500/20' },
	disabled: { label: 'Disabled', dot: 'bg-slate-400', text: 'text-slate-500 dark:text-slate-400', ring: 'ring-slate-400/20' },
	unavailable: { label: 'Unavailable', dot: 'bg-orange-500', text: 'text-orange-600 dark:text-orange-400', ring: 'ring-orange-500/20' },
	error: { label: 'Error', dot: 'bg-red-500', text: 'text-red-600 dark:text-red-400', ring: 'ring-red-500/20' }
};

// Catalog card id → engine_readiness key (the authoritative state for Build engines).
export const ENGINE_READINESS_KEY: Record<string, string> = {
	'claude-code': 'claude-code',
	'codex-app': 'codex',
	// The merged Kimi tile reads its status from the MEMBERSHIP variant's engine row — that's the
	// one Build actually runs. The platform (Moonshot key) variant has no readiness signal at all
	// today, so a platform-only user sees "Needs setup", exactly as the old separate tile did.
	kimi: 'kimi-code',
	opencode: 'opencode',
	openclaw: 'openclaw',
	'hermes-agent': 'hermes-agent'
};

export type EngineReadiness = Record<string, { ready: boolean; reason?: string; connected?: boolean }>;

/**
 * Translate a (merged) definition + the engine-readiness map into ONE normalized status.
 *   verified key + sidecar running → Ready/Connected · key saved-not-verified / not connected → Needs setup
 *   flag off → Disabled · sidecar down → Unavailable · probe failed → Error
 * A user-supplied connection (github/mcp/byo/cloud key) reads as "Connected"; an auto-detected
 * local system (ollama/openclaw bundled/discord/hermes) reads as "Ready".
 */
export function normalizeStatus(def: IntegrationDefinition, er: EngineReadiness | null | undefined): NormStatus {
	const src = deriveSource(def); // 'static' | 'detected' | 'configured'
	const goodSource: NormStatus = src === 'configured' ? 'connected' : 'ready';

	// 1) Engines are governed by engine_readiness (most authoritative).
	const engKey = ENGINE_READINESS_KEY[def.id];
	const eng = engKey ? er?.[engKey] : undefined;
	if (eng) {
		if (eng.ready) return goodSource;
		// A verified cloud credential makes the provider usable (for chat) even when the Build
		// engine isn't ready — read as "Connected", never a scary "Unavailable".
		if (eng.connected) return 'connected';
		const reason = (eng.reason || '').toLowerCase();
		// A verified user-supplied EXTERNAL provider (e.g. BYO external Hermes) is a configured,
		// working connection — Build simply can't use it (no workspace), which the detail drawer
		// already explains. Read it as "Connected", not the scary "needs setup" the generic 'no_'
		// heuristic below would otherwise return for reasons like "external_no_workspace".
		if (reason.includes('external')) return 'connected';
		if (reason.includes('disabled') || reason.includes('flag')) return 'disabled';
		if (reason.includes('auth') || reason.includes('key') || reason.includes('no_') || reason.includes('model'))
			return 'needs_setup';
		return 'unavailable'; // sidecar down / unknown failure
	}

	// 2) Everything else, from the live-merged status.
	switch (def.status) {
		case 'error':
			return 'error';
		case 'coming_soon':
			return 'disabled';
		case 'needs_setup':
			return 'needs_setup';
		case 'ready':
		case 'running':
			return goodSource;
		case 'available':
		default:
			// A service that SHOULD be auto-detected but isn't → it's down. A connectable that
			// isn't connected → needs setup. Otherwise it's a static catalog item.
			if (def.detect?.serviceKey) return 'unavailable';
			if (def.connect) return 'needs_setup';
			return 'needs_setup';
	}
}

// ── Purpose grouping (replaces the catalog category for display) ─────────────────────────
export type GroupKey = 'engines' | 'models' | 'repos' | 'tools' | 'chat' | 'more';

export const GROUP_LABEL: Record<GroupKey, string> = {
	engines: 'Build Engines',
	models: 'Models',
	repos: 'Repos',
	tools: 'Tools',
	chat: 'Chat & Notifications',
	more: 'More'
};

export const GROUP_ORDER: GroupKey[] = ['engines', 'models', 'repos', 'tools', 'chat', 'more'];

const GROUP_OF: Record<string, GroupKey> = {
	openclaw: 'engines',
	'claude-code': 'engines',
	'codex-app': 'engines',
	kimi: 'engines',
	'hermes-agent': 'engines',
	ollama: 'models',
	'groq-api': 'models',
	'cerebras-api': 'models',
	'gemini-api': 'models',
	'nvidia-api': 'models',
	'openrouter-api': 'models',
	'mistral-api': 'models',
	github: 'repos',
	mcp: 'tools',
	discord: 'chat',
	ssh: 'more',
	'pack-local-coder': 'more',
	'pack-repo-review': 'more'
};

export function groupOf(def: IntegrationDefinition): GroupKey {
	return GROUP_OF[def.id] ?? 'more';
}

export function isPack(def: IntegrationDefinition): boolean {
	return def.category === 'pack';
}

// ── Dashboard sections (Phase 6 refinement) ──────────────────────────────────────────────
// ADDITIVE next to the GROUP_* purpose grouping above (kept intact for compat): the
// Integrations dashboard renders these five named sections. The 6-status contract is
// unchanged — sections only re-home the cards.
export type SectionKey = 'agent_engines' | 'cloud_apis' | 'mcp_servers' | 'ssh_remote' | 'voice_other';

export const SECTION_ORDER: SectionKey[] = [
	'agent_engines',
	'cloud_apis',
	'mcp_servers',
	'ssh_remote',
	'voice_other'
];

export const SECTION_LABEL: Record<SectionKey, string> = {
	agent_engines: 'Agent Engines',
	cloud_apis: 'Cloud APIs',
	mcp_servers: 'MCP Servers',
	ssh_remote: 'SSH / Remote',
	voice_other: 'Voice & Other'
};

// One-line section subtitle shown under the header.
export const SECTION_HINT: Record<SectionKey, string> = {
	agent_engines: 'Runtimes that execute Build & agent tasks',
	cloud_apis: 'Provider credentials that unlock cloud models',
	mcp_servers: 'Model Context Protocol tools & data sources',
	ssh_remote: 'Remote execution targets',
	voice_other: 'Models, repos, messaging and everything else'
};

const SECTION_OF: Record<string, SectionKey> = {
	openclaw: 'agent_engines',
	'claude-code': 'agent_engines',
	'codex-app': 'agent_engines',
	// One Kimi tile, homed with the engines: in membership mode it EXECUTES (the Claude Code
	// sidecar drives its tool loop). The platform-key mode is a cloud credential, but splitting
	// the brand across two sections is what made the two old tiles read as duplicates.
	kimi: 'agent_engines',
	'hermes-agent': 'agent_engines',
	'anthropic-api': 'cloud_apis',
	'openai-api': 'cloud_apis',
	// Free-tier BYO-key chat providers. These ids must stay in sync with free_providers.py —
	// a card whose id drifts from its backend row still renders, but its status never resolves.
	'groq-api': 'cloud_apis',
	'cerebras-api': 'cloud_apis',
	'gemini-api': 'cloud_apis',
	'nvidia-api': 'cloud_apis',
	'openrouter-api': 'cloud_apis',
	'mistral-api': 'cloud_apis',
	mcp: 'mcp_servers',
	ssh: 'ssh_remote'
};

export function sectionOf(def: IntegrationDefinition): SectionKey {
	return SECTION_OF[def.id] ?? 'voice_other';
}

// ── Icon-tile tint (directory look, 2026-07-29) ───────────────────────────────────────────
// Keyed by brandKey, biased toward each vendor's own colour so a row is recognizable before
// the name is read. Every mark on this page takes its colour from the tile's text class:
// inline glyphs paint with currentColor, and the single-colour vendored logos are masked with
// it (see BrandGlyph). Only Claude, Discord and OpenClaw stay fixed-colour images. Kept as
// static class strings so Tailwind's scanner sees them (a template-built `bg-${hue}-50` would
// be purged).
//
// EVERY brandKey the catalog uses needs a row here. The fallback is grey, so a brand that is
// missing does not look broken — it just quietly loses its colour, which is how the five free
// providers ended up as grey tiles in a page that was otherwise fully branded.
export const TILE_TINT: Record<string, string> = {
	claude: 'bg-orange-50 dark:bg-orange-500/10 text-orange-600 dark:text-orange-400',
	openai: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
	kimi: 'bg-purple-50 dark:bg-purple-500/10 text-purple-600 dark:text-purple-400',
	openclaw: 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400',
	hermes: 'bg-violet-50 dark:bg-violet-500/10 text-violet-600 dark:text-violet-400',
	opencode: 'bg-cyan-50 dark:bg-cyan-500/10 text-cyan-600 dark:text-cyan-400',
	ollama: 'bg-slate-100 dark:bg-slate-500/10 text-slate-700 dark:text-slate-300',
	github: 'bg-gray-100 dark:bg-gray-500/10 text-gray-700 dark:text-gray-300',
	mcp: 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400',
	discord: 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400',
	ssh: 'bg-teal-50 dark:bg-teal-500/10 text-teal-600 dark:text-teal-400',
	// Free-tier cloud providers, approximated to each vendor's own hue. Groq (#F55036) and
	// Cerebras (#F15A29) are near-identical oranges in real life, so Cerebras is nudged to amber
	// to stay tellable apart in a vertical list. Mistral's mark is a yellow-to-red gradient that
	// one colour cannot reproduce; rose takes the red end. OpenRouter ships no official mark
	// here, so violet is ours and only has to stay distinct.
	groq: 'bg-orange-50 dark:bg-orange-500/10 text-orange-600 dark:text-orange-400',
	cerebras: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400',
	gemini: 'bg-sky-50 dark:bg-sky-500/10 text-sky-600 dark:text-sky-400',
	nvidia: 'bg-lime-50 dark:bg-lime-500/10 text-lime-700 dark:text-lime-400',
	mistral: 'bg-rose-50 dark:bg-rose-500/10 text-rose-600 dark:text-rose-400',
	openrouter: 'bg-violet-50 dark:bg-violet-500/10 text-violet-600 dark:text-violet-400',
	harvis: 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400',
	pack: 'bg-rose-50 dark:bg-rose-500/10 text-rose-600 dark:text-rose-400'
};

export const TILE_TINT_FALLBACK = 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300';

export function tileTint(def: IntegrationDefinition): string {
	return TILE_TINT[def.brandKey ?? ''] ?? TILE_TINT_FALLBACK;
}

// ── Connect vs Default ───────────────────────────────────────────────────────────────────
// The capability whose default a card's "Set default" controls (the most meaningful one).
const PRIMARY_CAP_ORDER: IntegrationCapability[] = [
	'code_engine_candidate',
	'model_provider',
	'agent_runtime',
	'tool_runtime',
	'workflow_runtime',
	'research_runtime'
];

export function primaryCapabilityOf(def: IntegrationDefinition): IntegrationCapability | null {
	const provides = def.provides ?? [];
	for (const c of PRIMARY_CAP_ORDER) {
		if (provides.includes(c) && PREFERABLE_CAPABILITIES.includes(c)) return c;
	}
	return null;
}

export function preferableCaps(def: IntegrationDefinition): IntegrationCapability[] {
	return (def.provides ?? []).filter((c) => PREFERABLE_CAPABILITIES.includes(c));
}

/** Is this card the saved default for its primary capability? (prefs: capability → provider_id) */
export function isDefault(def: IntegrationDefinition, prefs: Record<string, string> | null | undefined): boolean {
	const cap = primaryCapabilityOf(def);
	if (!cap) return false;
	return (prefs?.[cap] ?? '') === def.id;
}

/** Human label for the "Set default" affordance, by primary capability. */
export function defaultLabelFor(def: IntegrationDefinition): string {
	const cap = primaryCapabilityOf(def);
	if (cap === 'code_engine_candidate') return 'Set as Build default';
	if (cap === 'model_provider') return 'Set as default model';
	if (cap === 'agent_runtime') return 'Set as agent default';
	return 'Set as default';
}

// ── Summary counts ───────────────────────────────────────────────────────────────────────
export function statusCounts(
	defs: IntegrationDefinition[],
	er: EngineReadiness | null | undefined
): Record<NormStatus, number> {
	const out: Record<NormStatus, number> = {
		ready: 0,
		connected: 0,
		needs_setup: 0,
		disabled: 0,
		unavailable: 0,
		error: 0
	};
	for (const d of defs) {
		if (isPack(d)) continue;
		out[normalizeStatus(d, er)]++;
	}
	return out;
}
