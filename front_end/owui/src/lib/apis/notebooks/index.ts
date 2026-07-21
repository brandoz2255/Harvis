// Open Notebook — RAG notebooks (sources + chat). Backend: notebooks/router.py
// → /api/notebooks (list/create/get, sources, chat). NotebookLM-style.

const BASE = '/api/notebooks';
const authHeaders = () => ({ Authorization: `Bearer ${localStorage.token}` });
const jsonHeaders = () => ({ ...authHeaders(), 'Content-Type': 'application/json' });

export interface Notebook {
	id: string;
	title: string;
	description?: string | null;
	emoji?: string | null;
	created_at?: string;
	updated_at?: string;
	source_count?: number;
	note_count?: number;
}

export interface NotebookSource {
	id: string;
	title?: string;
	source_type?: string;
	status?: string;
	[key: string]: unknown;
}

// Detailed variant: callers that need to distinguish "no notebooks" from "the
// request failed" (auth expired, backend down) use this. `listNotebooks` below
// keeps its swallow-to-[] signature for existing callers.
export const listNotebooksDetailed = async (): Promise<{
	ok: boolean;
	status: number;
	notebooks: Notebook[];
	error?: string;
}> => {
	try {
		const r = await fetch(BASE, { headers: authHeaders(), credentials: 'include' });
		if (!r.ok) return { ok: false, status: r.status, notebooks: [], error: `HTTP ${r.status}` };
		const data = await r.json();
		return { ok: true, status: r.status, notebooks: data?.notebooks ?? [] };
	} catch (e: any) {
		return { ok: false, status: 0, notebooks: [], error: String(e?.message ?? e) };
	}
};

export const listNotebooks = async (): Promise<Notebook[]> => {
	return (await listNotebooksDetailed()).notebooks;
};

export const createNotebook = async (
	title: string,
	description = ''
): Promise<{ ok: boolean; notebook?: Notebook; error?: string }> => {
	try {
		const r = await fetch(BASE, {
			method: 'POST',
			headers: jsonHeaders(),
			credentials: 'include',
			body: JSON.stringify({ title, description: description || null })
		});
		if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
		return { ok: true, notebook: await r.json() };
	} catch (e: any) {
		return { ok: false, error: String(e?.message ?? e) };
	}
};

export const getNotebook = async (id: string): Promise<Notebook | null> => {
	try {
		const r = await fetch(`${BASE}/${id}`, { headers: authHeaders(), credentials: 'include' });
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

export const deleteNotebook = async (id: string): Promise<boolean> => {
	try {
		const r = await fetch(`${BASE}/${id}`, {
			method: 'DELETE',
			headers: authHeaders(),
			credentials: 'include'
		});
		return r.ok;
	} catch (_) {
		return false;
	}
};

export const updateNotebook = async (
	id: string,
	patch: { title?: string; description?: string; emoji?: string }
): Promise<Notebook | null> => {
	try {
		const r = await fetch(`${BASE}/${id}`, {
			method: 'PATCH',
			headers: jsonHeaders(),
			credentials: 'include',
			body: JSON.stringify(patch)
		});
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

// Derive an emoji (+ a title for untitled notebooks) from the notebook's sources via the LLM.
export const autonameNotebook = async (
	id: string
): Promise<{ title?: string; emoji?: string } | null> => {
	try {
		const r = await fetch(`${BASE}/${id}/autoname`, {
			method: 'POST',
			headers: jsonHeaders(),
			credentials: 'include'
		});
		return r.ok ? await r.json() : null;
	} catch (_) {
		return null;
	}
};

export const listSources = async (id: string): Promise<NotebookSource[]> => {
	try {
		const r = await fetch(`${BASE}/${id}/sources`, { headers: authHeaders(), credentials: 'include' });
		if (!r.ok) return [];
		const data = await r.json();
		return Array.isArray(data) ? data : (data?.sources ?? []);
	} catch (_) {
		return [];
	}
};

export const addUrlSource = async (id: string, url: string, title = ''): Promise<boolean> => {
	try {
		const r = await fetch(`${BASE}/${id}/sources/url`, {
			method: 'POST',
			headers: jsonHeaders(),
			credentials: 'include',
			body: JSON.stringify({ url, title: title || undefined })
		});
		return r.ok;
	} catch (_) {
		return false;
	}
};

export const addTextSource = async (id: string, title: string, content: string): Promise<boolean> => {
	try {
		const fd = new FormData();
		fd.append('title', title);
		fd.append('content', content);
		const r = await fetch(`${BASE}/${id}/sources/text`, {
			method: 'POST',
			headers: authHeaders(),
			credentials: 'include',
			body: fd
		});
		return r.ok;
	} catch (_) {
		return false;
	}
};

export const addYoutubeSource = async (id: string, url: string): Promise<boolean> => {
	try {
		const r = await fetch(`${BASE}/${id}/sources/youtube`, {
			method: 'POST',
			headers: jsonHeaders(),
			credentials: 'include',
			body: JSON.stringify({ url })
		});
		return r.ok;
	} catch (_) {
		return false;
	}
};

export const uploadFileSource = async (id: string, file: File): Promise<boolean> => {
	try {
		const fd = new FormData();
		fd.append('file', file);
		fd.append('title', file.name);
		const r = await fetch(`${BASE}/${id}/sources/upload`, {
			method: 'POST',
			headers: authHeaders(),
			credentials: 'include',
			body: fd
		});
		return r.ok;
	} catch (_) {
		return false;
	}
};

export const deleteSource = async (id: string, sourceId: string): Promise<boolean> => {
	try {
		const r = await fetch(`${BASE}/${id}/sources/${sourceId}`, {
			method: 'DELETE',
			headers: authHeaders(),
			credentials: 'include'
		});
		return r.ok;
	} catch (_) {
		return false;
	}
};

export interface NotebookNote {
	id: string;
	title?: string | null;
	content: string;
	note_type?: string;
	type?: string;
	is_pinned?: boolean;
	updated_at?: string;
	created_at?: string;
}

export const listNotes = async (id: string): Promise<NotebookNote[]> => {
	try {
		const r = await fetch(`${BASE}/${id}/notes`, { headers: authHeaders(), credentials: 'include' });
		if (!r.ok) return [];
		const data = await r.json();
		return Array.isArray(data) ? data : (data?.notes ?? []);
	} catch (_) {
		return [];
	}
};

export const createNote = async (
	id: string,
	content: string,
	title = ''
): Promise<boolean> => {
	try {
		const r = await fetch(`${BASE}/${id}/notes`, {
			method: 'POST',
			headers: jsonHeaders(),
			credentials: 'include',
			body: JSON.stringify({ content, title: title || undefined })
		});
		return r.ok;
	} catch (_) {
		return false;
	}
};

export interface NotebookChatAnswer {
	answer: string;
	sources: { title?: string; snippet?: string }[];
}

// RAG chat against the notebook's sources. Backend returns JSON; field names vary,
// so read defensively.
export const chatNotebook = async (
	id: string,
	message: string
): Promise<NotebookChatAnswer> => {
	try {
		const r = await fetch(`${BASE}/${id}/chat`, {
			method: 'POST',
			headers: jsonHeaders(),
			credentials: 'include',
			body: JSON.stringify({ message, query: message })
		});
		if (!r.ok) return { answer: `(error: HTTP ${r.status})`, sources: [] };
		const d = await r.json();
		return {
			answer: d?.answer ?? d?.response ?? d?.content ?? d?.message ?? '(no answer)',
			sources: d?.sources ?? d?.citations ?? []
		};
	} catch (e: any) {
		return { answer: `(error: ${String(e?.message ?? e)})`, sources: [] };
	}
};

// ── Audio Overview (podcast) — Studio ──
export interface Podcast {
	id: string;
	title?: string;
	status?: string; // pending | generating | completed | error
	style?: string;
	audio_path?: string | null;
	transcript?: { speaker?: string; dialogue?: string }[];
	outline?: string | null;
	error_message?: string | null;
	created_at?: string;
	completed_at?: string | null;
}

export const listPodcasts = async (id: string): Promise<Podcast[]> => {
	try {
		const r = await fetch(`${BASE}/${id}/podcasts`, { headers: authHeaders(), credentials: 'include' });
		if (!r.ok) return [];
		const data = await r.json();
		return Array.isArray(data) ? data : (data?.podcasts ?? []);
	} catch (_) {
		return [];
	}
};

export const generatePodcast = async (
	id: string,
	opts: { title?: string; style?: string; speakers?: number; duration_minutes?: number } = {}
): Promise<{ ok: boolean; podcast?: Podcast; error?: string }> => {
	try {
		const r = await fetch(`${BASE}/${id}/podcasts`, {
			method: 'POST',
			headers: jsonHeaders(),
			credentials: 'include',
			body: JSON.stringify({
				title: opts.title || 'Audio Overview',
				style: opts.style || 'conversational',
				speakers: opts.speakers ?? 2,
				duration_minutes: opts.duration_minutes ?? 5
			})
		});
		if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
		return { ok: true, podcast: await r.json() };
	} catch (e: any) {
		return { ok: false, error: String(e?.message ?? e) };
	}
};

// Relative audio URL for an <audio> tag (same-origin cookie carries the session).
export const podcastAudioUrl = (id: string, podcastId: string): string =>
	`${BASE}/${id}/podcasts/${podcastId}/audio`;
