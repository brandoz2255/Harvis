import { WEBUI_BASE_URL } from '$lib/constants';
import type { LiveStatus } from '$lib/integrations/catalog';

// Light read-only detection for the Integrations catalog — service reachability +
// installed Ollama models. Returns null on any failure (page falls back to static).
export const getIntegrationsStatus = async (token: string): Promise<LiveStatus | null> => {
	try {
		const res = await fetch(`${WEBUI_BASE_URL}/api/owui/integrations/status`, {
			headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
		});
		if (!res.ok) return null;
		const d = await res.json();
		return { services: d?.services ?? {}, installedModels: d?.installedModels ?? [] };
	} catch (_) {
		return null;
	}
};

// ── Phase B (connections) — thin wrappers over EXISTING encrypted endpoints. ──
// Relative paths + Bearer from localStorage.token, matching lib/apis/agent-runs.
const hdr = () => ({ 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.token}` });

export interface OpenclawConfig {
	mode: 'bundled' | 'byo';
	byo_url: string | null;
	byo_verified_at: string | null;
	byo_last_error: string | null;
	byo_token_saved: boolean;
}

// OpenClaw BYO gateway config (NOT the provider config at /api/user/openclaw-config).
// GET never returns the token — only `byo_token_saved` boolean.
export const getOpenclawConfig = async (): Promise<OpenclawConfig | null> => {
	try {
		const r = await fetch('/api/workspace/config/openclaw', { headers: hdr(), credentials: 'include' });
		if (!r.ok) return null;
		return await r.json();
	} catch (_) {
		return null;
	}
};

// Verify = "connect + enable routing": on success the backend sets mode='byo',
// byo_verified_at, and encrypts the token. The resolver only routes to BYO once verified.
export const verifyOpenclawByo = async (
	url: string,
	token?: string
): Promise<{ ok: boolean; error?: string; hint?: string }> => {
	try {
		const r = await fetch('/api/workspace/config/byo/verify', {
			method: 'POST',
			headers: hdr(),
			credentials: 'include',
			body: JSON.stringify({ url, token: token || undefined })
		});
		const d = await r.json().catch(() => ({}));
		if (!r.ok) return { ok: false, error: d?.detail || d?.error || `HTTP ${r.status}` };
		return { ok: !!d?.ok, error: d?.error, hint: d?.hint };
	} catch (e: any) {
		return { ok: false, error: `${e?.message ?? e}` };
	}
};

// Save = persist mode/url/token WITHOUT (re-)verifying. Routing stays bundled until verified.
export const saveOpenclawConfig = async (body: {
	mode: 'bundled' | 'byo';
	byo_url?: string;
	byo_token?: string;
}): Promise<{ ok: boolean; error?: string }> => {
	try {
		const r = await fetch('/api/workspace/config/openclaw', {
			method: 'POST',
			headers: hdr(),
			credentials: 'include',
			body: JSON.stringify(body)
		});
		const d = await r.json().catch(() => ({}));
		if (!r.ok) return { ok: false, error: d?.detail || `HTTP ${r.status}` };
		return { ok: true };
	} catch (e: any) {
		return { ok: false, error: `${e?.message ?? e}` };
	}
};

// MCP server connections — count/state only (CRUD stays in Agent Studio → Customize).
// null = the request failed; callers must not render that as "0 servers connected".
export const getMcpConnections = async (): Promise<any[] | null> => {
	try {
		const r = await fetch('/api/owui/mcp/connections', { headers: hdr(), credentials: 'include' });
		if (!r.ok) return null;
		const d = await r.json();
		return d?.items ?? [];
	} catch (_) {
		return null;
	}
};

// Phase E2: per-user cloud-engine credentials (engine ∈ {codex, claude-code}). Write-only —
// the GET returns only {api_key_saved, verified_at, last_error}, never the key.
export type EngineAuthStatus = {
	engine: string;
	api_key_saved: boolean;
	auth_mode?: string; // E4B: 'api_key' | 'oauth_token' (Claude subscription)
	supports_oauth?: boolean; // true for claude-code (subscription token mode)
	verified_at: string | null;
	last_error: string | null;
};

export const getEngineAuth = async (engine: string): Promise<EngineAuthStatus | null> => {
	try {
		const r = await fetch(`/api/owui/engine-auth/${engine}`, { headers: hdr(), credentials: 'include' });
		if (!r.ok) return null;
		return await r.json();
	} catch (_) {
		return null;
	}
};

export const saveEngineKey = async (
	engine: string,
	credential: string,
	authMode: string = 'api_key'
): Promise<{ ok: boolean }> => {
	try {
		const r = await fetch(`/api/owui/engine-auth/${engine}`, {
			method: 'POST', headers: hdr(), credentials: 'include',
			body: JSON.stringify({ credential, auth_mode: authMode })
		});
		return { ok: r.ok };
	} catch (_) {
		return { ok: false };
	}
};

export const verifyEngineKey = async (
	engine: string,
	credential?: string,
	authMode?: string
): Promise<{ ok: boolean; error?: string }> => {
	try {
		const body: Record<string, string> = {};
		if (credential) body.credential = credential;
		if (authMode) body.auth_mode = authMode;
		const r = await fetch(`/api/owui/engine-auth/${engine}/verify`, {
			method: 'POST', headers: hdr(), credentials: 'include',
			body: JSON.stringify(body)
		});
		const d = await r.json().catch(() => ({}));
		return { ok: !!d?.ok, error: d?.error };
	} catch (_) {
		return { ok: false, error: 'request failed' };
	}
};

export const disconnectEngine = async (engine: string): Promise<{ ok: boolean }> => {
	try {
		const r = await fetch(`/api/owui/engine-auth/${engine}/disconnect`, {
			method: 'POST', headers: hdr(), credentials: 'include'
		});
		return { ok: r.ok };
	} catch (_) {
		return { ok: false };
	}
};
