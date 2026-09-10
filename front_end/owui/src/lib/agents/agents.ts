import { WEBUI_BASE_URL } from '$lib/constants';

/** A teammate as `/api/agents` returns it (plugins/agents/store.agent_to_dict). */
export type Teammate = {
	id: string;
	name: string;
	title?: string | null;
	job?: string | null;
	avatar?: { mascot?: string; tint?: string } | null;
	is_default_assistant?: boolean;
	enabled?: boolean;
	/** The model its runs use. Empty/absent means "auto" — see plugins/agents/models.py. */
	model?: string | null;
};

/** The chat model id a teammate answers to (owui_compat/agent_bridge.model_id_for). */
export const teammateModelId = (agentId: string) => `agent:${agentId}`;

const call = async <T>(token: string, path: string, init: RequestInit = {}): Promise<T> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/agents${path}`, {
		credentials: 'include',
		...init,
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json',
			...(init.headers ?? {})
		}
	});
	if (!res.ok) {
		let detail = `HTTP ${res.status}`;
		try {
			detail = (await res.json())?.detail ?? detail;
		} catch {
			/* not json */
		}
		throw new Error(detail);
	}
	return (await res.json()) as T;
};

export const listTeammates = async (token: string) =>
	(await call<{ items: Teammate[] }>(token, '')).items;

/** The teammate Work mode talks to — found, promoted, or created on first use. */
export const ensureDefaultTeammate = (token: string) =>
	call<Teammate>(token, '/ensure-default', { method: 'POST' });

export const getTeammate = (token: string, agentId: string) =>
	call<Teammate>(token, `/${agentId}`);

/**
 * Partial update — the backend only touches the keys actually sent, so
 * `{ model }` leaves the rest of the teammate alone. `model: ''` means auto.
 */
export const updateTeammate = (token: string, agentId: string, patch: Partial<Teammate>) =>
	call<Teammate>(token, `/${agentId}`, { method: 'POST', body: JSON.stringify(patch) });
