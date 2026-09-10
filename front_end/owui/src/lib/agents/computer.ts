import { WEBUI_BASE_URL } from '$lib/constants';

/**
 * The teammate's computer, as the pane sees it. `vncPath` is the only thing the
 * browser needs — a relative websockify path carrying the session's token — and
 * it is turned into a noVNC URL here, on the same origin the app is served from,
 * so the pane works on localhost:9000, a LAN hostname, or behind TLS unchanged.
 */
export type ComputerSession = {
	sessionId: string;
	agentId: string | null;
	profile: string;
	vncPath: string;
	display: string | null;
	width: number | null;
	height: number | null;
	takenOver: boolean;
	createdAt: number;
	url?: string;
	title?: string;
};

export type ComputerHealth = {
	ok: boolean;
	headedAvailable: boolean;
	sessions?: number;
	maxSessions?: number;
	reason?: string;
};

const NOVNC_PAGE = '/agents/vnc/vnc.html';

/** noVNC page for one session. `path` is URL-encoded because it carries its own `?token=`. */
export const vncUrl = (vncPath: string, base: string = WEBUI_BASE_URL): string =>
	`${base}${NOVNC_PAGE}?autoconnect=true&resize=scale&reconnect=true&path=${encodeURIComponent(vncPath)}`;

const headers = (token: string) => ({
	Authorization: `Bearer ${token}`,
	'Content-Type': 'application/json'
});

const call = async <T>(token: string, path: string, init: RequestInit = {}): Promise<T> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/agents/computer${path}`, {
		credentials: 'include',
		...init,
		headers: { ...headers(token), ...(init.headers ?? {}) }
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

export const computerHealth = (token: string) => call<ComputerHealth>(token, '/health');

export const listComputerSessions = async (token: string) =>
	(await call<{ items: ComputerSession[] }>(token, '/sessions')).items;

export const startComputerSession = (
	token: string,
	opts: { agentId?: string | null; url?: string } = {}
) =>
	call<ComputerSession>(token, '/sessions', {
		method: 'POST',
		body: JSON.stringify({ agent_id: opts.agentId ?? null, url: opts.url ?? null })
	});

export const getComputerSession = (token: string, sessionId: string) =>
	call<ComputerSession>(token, `/sessions/${sessionId}`);

export const navigateComputer = (token: string, sessionId: string, url: string) =>
	call<{ ok: boolean; url: string }>(token, `/sessions/${sessionId}/navigate`, {
		method: 'POST',
		body: JSON.stringify({ url })
	});

export const setComputerTakeover = (token: string, sessionId: string, taken: boolean) =>
	call<ComputerSession>(token, `/sessions/${sessionId}/takeover`, {
		method: 'POST',
		body: JSON.stringify({ taken })
	});

export const closeComputerSession = (token: string, sessionId: string) =>
	call<{ closed: boolean }>(token, `/sessions/${sessionId}`, { method: 'DELETE' });
