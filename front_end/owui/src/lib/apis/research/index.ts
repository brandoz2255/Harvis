import { WEBUI_BASE_URL } from '$lib/constants';

// Deep Research client — backed by the Harvis backend `/api/research/*`
// (ported Odysseus DeepResearcher). See python_back_end/deep_research/router.py.

const headers = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

export const startResearch = async (
	token: string,
	body: { query: string; model?: string; max_rounds?: number; max_time?: number; category?: string }
): Promise<{ session_id: string; status: string; query: string; model?: string }> => {
	return fetch(`${WEBUI_BASE_URL}/api/research/start`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(body)
	}).then(async (r) => {
		if (!r.ok) throw await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
		return r.json();
	});
};

// SSE progress stream. onEvent receives {phase, round, queries, total_sources, status, final?, error?}.
export const streamResearch = async (
	token: string,
	sessionId: string,
	onEvent: (e: any) => void,
	signal?: AbortSignal
): Promise<void> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/research/stream/${sessionId}`, {
		headers: headers(token),
		signal
	});
	if (!res.ok || !res.body) throw new Error(`stream HTTP ${res.status}`);
	const reader = res.body.getReader();
	const dec = new TextDecoder();
	let buf = '';
	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		buf += dec.decode(value, { stream: true });
		const parts = buf.split('\n\n');
		buf = parts.pop() || '';
		for (const part of parts) {
			const line = part.split('\n').find((l) => l.startsWith('data:'));
			if (!line) continue;
			try {
				onEvent(JSON.parse(line.slice(5).trim()));
			} catch (_) {
				// ignore
			}
		}
	}
};

// Which of this user's research runs are still going. In-memory on the backend, so a
// restart simply reports none — which reads as "finished" to the sidebar poller, and
// that is the honest answer: nothing is running any more.
export const fetchActiveResearch = async (
	token: string
): Promise<{ active: { session_id: string; query: string; status: string }[] }> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/research/active`, { headers: headers(token) });
	if (!res.ok) throw new Error(`active HTTP ${res.status}`);
	return res.json();
};

export const peekResult = async (
	token: string,
	sessionId: string
): Promise<{ result: string; sources: any[]; raw_findings: any[]; category?: string }> => {
	return fetch(`${WEBUI_BASE_URL}/api/research/result-peek/${sessionId}`, {
		method: 'POST',
		headers: headers(token)
	}).then(async (r) => {
		if (!r.ok) throw await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
		return r.json();
	});
};

export const cancelResearch = async (token: string, sessionId: string): Promise<any> => {
	return fetch(`${WEBUI_BASE_URL}/api/research/cancel/${sessionId}`, {
		method: 'POST',
		headers: headers(token)
	}).then((r) => r.json().catch(() => ({})));
};

// List the user's research reports (owner-scoped, all sessions). The Artifacts dock
// filters this to the current chat's research ids; the full-page surface shows all.
export type ResearchLibraryItem = {
	id: string;
	query: string;
	category: string;
	source_count: number;
	status: string;
	completed_at: number;
	archived: boolean;
};
export const fetchLibrary = async (
	token: string
): Promise<{ research: ResearchLibraryItem[]; total: number }> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/research/library`, {
		headers: headers(token)
	});
	if (!res.ok) throw new Error(`library HTTP ${res.status}`);
	return res.json();
};

// Fetch the visual HTML report (Bearer-authed) as a string. Open via doc.write so
// the token never lands in a URL.
export const fetchReportHtml = async (token: string, sessionId: string): Promise<string> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/research/report/${sessionId}`, {
		headers: { authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error(`report HTTP ${res.status}`);
	return res.text();
};

export const openReportInNewTab = async (token: string, sessionId: string): Promise<void> => {
	const html = await fetchReportHtml(token, sessionId);
	const w = window.open('', '_blank');
	if (w) {
		w.document.open();
		w.document.write(html);
		w.document.close();
	}
};
