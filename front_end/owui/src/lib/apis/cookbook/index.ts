import { WEBUI_BASE_URL } from '$lib/constants';

// Cookbook client — backed by the Harvis backend `/api/cookbook/*` (per-node
// llmfit-serve proxy + Ollama download). See python_back_end/cookbook/router.py.

const headers = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

export interface CookbookNode {
	name: string;
	role?: string; // 'main' (the host running compose) | 'subhost'
	llmfit_url: string;
	ollama_url: string;
	alive: boolean;
	latency_ms: number | null;
	error?: string;
}

export interface CookbookModel {
	name: string;
	params_b?: number;
	parameter_count?: string;
	best_quant?: string;
	context_length?: number;
	estimated_tps?: number;
	fit_label?: string;
	fit_level?: string;
	score?: number;
	runtime?: string;
	is_moe?: boolean;
	memory_required_gb?: number;
	downloadable?: boolean;
	serving?: string; // 'local' (Ollama/GGUF) | 'server' (vLLM — GPU server/cloud)
	reason?: string;
	[k: string]: any;
}

export const getNodes = async (token: string): Promise<CookbookNode[]> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/cookbook/nodes`, { headers: headers(token) }).then(
		async (r) => {
			if (!r.ok) throw await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
			return r.json();
		}
	);
	return res?.nodes ?? [];
};

// Register another machine running `llmfit serve` as an inference node (admin-only).
// The backend probes the llmfit URL for reachability before saving, so a bad URL
// throws here with a helpful `detail`. Returns the saved node (with liveness).
export const addNode = async (
	token: string,
	body: { name: string; llmfit_url: string; ollama_url?: string }
): Promise<CookbookNode> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/cookbook/nodes`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(body)
	});
	if (!res.ok) throw await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
	return res.json();
};

// Remove a user-added node (admin-only). Built-in nodes (e.g. main-host) are protected.
export const removeNode = async (token: string, name: string): Promise<void> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/cookbook/nodes/${encodeURIComponent(name)}`, {
		method: 'DELETE',
		headers: headers(token)
	});
	if (!res.ok) throw await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
};

export const getSystem = async (token: string, node: string): Promise<any> => {
	return fetch(`${WEBUI_BASE_URL}/api/cookbook/system?node=${encodeURIComponent(node)}`, {
		headers: headers(token)
	}).then(async (r) => {
		if (!r.ok) throw await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
		return r.json();
	});
};

export const recommend = async (
	token: string,
	node: string,
	opts: { use_case?: string; min_fit?: string; limit?: number; runtime?: string } = {}
): Promise<{ models: CookbookModel[]; total_models?: number; system?: any }> => {
	const p = new URLSearchParams({ node });
	for (const [k, v] of Object.entries(opts)) if (v != null && v !== '') p.append(k, String(v));
	return fetch(`${WEBUI_BASE_URL}/api/cookbook/recommend?${p}`, { headers: headers(token) }).then(
		async (r) => {
			if (!r.ok) throw await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
			return r.json();
		}
	);
};

// Search / browse the FULL fit list (not just top picks) — backed by llmfit's
// whole model DB (thousands of models), still fit-ranked for the node's hardware.
export const searchModels = async (
	token: string,
	node: string,
	opts: { search?: string; use_case?: string; runtime?: string; min_fit?: string; limit?: number } = {}
): Promise<{ models: CookbookModel[]; total_models?: number }> => {
	const p = new URLSearchParams({ node });
	for (const [k, v] of Object.entries(opts)) if (v != null && v !== '') p.append(k, String(v));
	return fetch(`${WEBUI_BASE_URL}/api/cookbook/models?${p}`, { headers: headers(token) }).then(
		async (r) => {
			if (!r.ok) throw await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
			return r.json();
		}
	);
};

// Models actually pulled into a node's Ollama — what you can swap to. Backed by
// /api/cookbook/installed (proxies that node's Ollama /api/tags).
export interface InstalledModel {
	name: string;
	model?: string;
	size?: number;
	modified_at?: string;
	digest?: string;
	details?: {
		family?: string;
		families?: string[];
		parameter_size?: string;
		quantization_level?: string;
		format?: string;
	};
}
export const getInstalled = async (
	token: string,
	node: string
): Promise<{ models: InstalledModel[]; ollama_url?: string; error?: string }> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/cookbook/installed?node=${encodeURIComponent(node)}`, {
		headers: headers(token)
	});
	if (!res.ok) throw await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
	return res.json();
};

// Download streams Ollama pull progress as SSE; `onEvent` receives each parsed object
// (e.g. {status, completed, total} from Ollama, or {error} / {status:'done'}).
export const downloadModel = async (
	token: string,
	body: { node: string; repo?: string; quant?: string; ollama_tag?: string },
	onEvent: (e: any) => void,
	signal?: AbortSignal
): Promise<void> => {
	const res = await fetch(`${WEBUI_BASE_URL}/api/cookbook/download`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(body),
		signal
	});
	if (!res.ok || !res.body) {
		let detail = `HTTP ${res.status}`;
		try {
			detail = (await res.json())?.detail ?? detail;
		} catch (_) {
			// ignore
		}
		throw new Error(detail);
	}
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
				// ignore malformed
			}
		}
	}
};
