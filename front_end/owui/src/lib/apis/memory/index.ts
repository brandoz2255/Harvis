import { WEBUI_BASE_URL } from '$lib/constants';

// Memory client — backed by the existing Harvis backend route `/api/memory`
// (NOT the OWUI `/api/v1` surface). Shapes mirror python_back_end/plugins/memory/routes.py:
//   GET    /api/memory?query=&limit=  → { entries: [{ content, source, metadata, created_at }] }
//   POST   /api/memory  { content, source?, metadata? }  → { ok, entry }
//   DELETE /api/memory  → { ok, deleted }

export interface MemoryEntry {
	content: string;
	source: string;
	metadata: Record<string, any>;
	created_at: string | null;
}

export const getMemories = async (
	token: string,
	query: string | null = null,
	limit = 50
): Promise<MemoryEntry[]> => {
	let error = null;

	const params = new URLSearchParams();
	if (query) params.append('query', query);
	if (limit) params.append('limit', String(limit));
	const qs = params.toString();

	const res = await fetch(`${WEBUI_BASE_URL}/api/memory${qs ? `?${qs}` : ''}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err?.detail ?? err;
			console.error('getMemories', err);
			return null;
		});

	if (error) throw error;
	return res?.entries ?? [];
};

export const addMemory = async (
	token: string,
	content: string,
	source = 'manual',
	metadata: Record<string, any> = {}
) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/memory`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ content, source, metadata })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err?.detail ?? err;
			console.error('addMemory', err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const clearMemories = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/memory`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err?.detail ?? err;
			console.error('clearMemories', err);
			return null;
		});

	if (error) throw error;
	return res;
};
