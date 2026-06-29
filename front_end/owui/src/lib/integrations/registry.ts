// Phase C capability-registry client. Reads GET /api/owui/capabilities (per-user
// readiness + connection + preferences) and persists a single preference.
// Fail-soft: null on any failure (consumers no-op). Preferences are written
// localStorage-first (offline cache) then synced to the server.
import { WEBUI_BASE_URL } from '$lib/constants';
import type { IntegrationCapability } from './capabilities';

export interface CapabilityProvider {
	id: string;
	status: string;
	ready: boolean;
	source: string;
	detail: string | null;
	preferred: boolean;
	connection: string | null; // openclaw only: 'byo_verified' | 'bundled'
}

export interface CapabilityEntry {
	preferred: string | null;
	providers: CapabilityProvider[];
}

export interface CapabilityRegistry {
	capabilities: Partial<Record<IntegrationCapability, CapabilityEntry>>;
	preferences: Record<string, string>;
	default_model: string | null;
	generated_at: number;
	// Phase E1/E2/E4(B): per-engine Build readiness (opencode/codex/claude-code/hermes-agent/
	// hermes-native → {ready, reason?}). The VibeCode engine selector reads this.
	engine_readiness: Record<string, { ready: boolean; reason?: string }>;
	// H1: installed Ollama tags (for the Hermes Agent model dropdown) + the Hermes runtime's
	// RESOLVED model + the raw per-user preference (null = following env/recommended/first).
	installed_models: string[];
	hermes_agent_model: string | null;
	hermes_agent_model_pref: string | null;
}

const PREF_KEY = (cap: string) => `harvis.integrations.preferences.${cap}`;

export const getCapabilityRegistry = async (token: string): Promise<CapabilityRegistry | null> => {
	try {
		const res = await fetch(`${WEBUI_BASE_URL}/api/owui/capabilities`, {
			headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
		});
		if (!res.ok) return null;
		const d = await res.json();
		return {
			capabilities: d?.capabilities ?? {},
			preferences: d?.preferences ?? {},
			default_model: d?.default_model ?? null,
			generated_at: d?.generated_at ?? 0,
			engine_readiness: d?.engine_readiness ?? {},
			installed_models: Array.isArray(d?.installed_models) ? d.installed_models : [],
			hermes_agent_model: d?.hermes_agent_model ?? null,
			hermes_agent_model_pref: d?.hermes_agent_model_pref ?? null
		};
	} catch (_) {
		return null;
	}
};

// A concrete default model (Phase C2) — pre-fills new Chat/Code sessions. Write-through:
// localStorage FIRST (both the canonical cache + the legacy VibeCode seam) then POST.
export const saveDefaultModel = async (
	model: string | null
): Promise<{ ok: boolean; synced: boolean }> => {
	try {
		if (model) localStorage.setItem('harvis.integrations.default_model', model);
		else localStorage.removeItem('harvis.integrations.default_model');
	} catch (_) {}
	try {
		const res = await fetch(`${WEBUI_BASE_URL}/api/owui/capabilities/default-model`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				authorization: `Bearer ${localStorage.token}`
			},
			body: JSON.stringify({ model })
		});
		return { ok: true, synced: res.ok };
	} catch (_) {
		return { ok: true, synced: false };
	}
};

// H1: the Hermes Agent runtime's underlying Ollama model (NOT the user's chat model).
// Server-only (no localStorage seam — it's a backend-resolved runtime setting). Returns the
// freshly-resolved model so the caller can reflect it immediately.
export const saveHermesModel = async (
	model: string | null
): Promise<{ ok: boolean; resolved: string | null }> => {
	try {
		const res = await fetch(`${WEBUI_BASE_URL}/api/owui/integrations/hermes-model`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				authorization: `Bearer ${localStorage.token}`
			},
			body: JSON.stringify({ model })
		});
		if (!res.ok) return { ok: false, resolved: null };
		const d = await res.json();
		return { ok: true, resolved: d?.hermes_agent_model ?? null };
	} catch (_) {
		return { ok: false, resolved: null };
	}
};

// Write-through: localStorage FIRST (instant, offline-safe) then POST. `synced`
// reflects whether the server accepted it; the caller can toast accordingly.
export const saveCapabilityPreference = async (
	capability: string,
	providerId: string | null
): Promise<{ ok: boolean; synced: boolean }> => {
	try {
		if (providerId) localStorage.setItem(PREF_KEY(capability), providerId);
		else localStorage.removeItem(PREF_KEY(capability));
	} catch (_) {}
	try {
		const res = await fetch(`${WEBUI_BASE_URL}/api/owui/capabilities/preference`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				authorization: `Bearer ${localStorage.token}`
			},
			body: JSON.stringify({ capability, provider_id: providerId })
		});
		return { ok: true, synced: res.ok };
	} catch (_) {
		return { ok: true, synced: false };
	}
};

// Phase E1: pick the default Build engine from the registry. NOT "first ready" —
// `code_engine_candidate` lists BOTH openclaw + opencode, so first-ready would always
// pick openclaw. Returns 'opencode' ONLY when the user preferred it AND it's ready;
// everything else (preferred openclaw, stale/absent pref, opencode not ready) → 'native'.
export const preferredEngineForVibecode = (reg: CapabilityRegistry | null): 'native' | 'opencode' => {
	if (!reg) return 'native';
	if ((reg.preferences?.code_engine_candidate ?? '') !== 'opencode') return 'native';
	const cand = reg.capabilities?.code_engine_candidate?.providers ?? [];
	const oc = cand.find((p) => p.id === 'opencode');
	return oc?.ready ? 'opencode' : 'native';
};
