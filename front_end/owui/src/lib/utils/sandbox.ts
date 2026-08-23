// Files the assistant wrote inside the chat sandbox (a container volume — never the user's
// own machine). A path on its own is useless to them: they cannot cd to it, cannot open it,
// cannot see what is in it. Everything here exists to turn a path into something viewable.
import { writable } from 'svelte/store';
import { showArtifacts, showControls, showEmbeds } from '$lib/stores';

// Deliberately root-agnostic. The backend owns the real root (HARVIS_CHAT_SANDBOX_ROOT) and
// re-checks ownership on every read, so matching the `/harvis-chat/u<id>/` segment is both
// sufficient and immune to the volume moving again — which is exactly what broke this once
// already, when the sandbox went from /tmp to /data/artifacts and this regex did not.
export const SANDBOX_PATH_RE = /(?:\/[\w.@+-]+)*\/harvis-chat\/u\d+\/[^\s`<>"')]+\.[a-z0-9]+/gi;

export const isSandboxPath = (s: string) => {
	SANDBOX_PATH_RE.lastIndex = 0;
	return SANDBOX_PATH_RE.test((s || '').trim());
};

const EXT_LANG: Record<string, string> = {
	py: 'python',
	js: 'javascript',
	mjs: 'javascript',
	ts: 'typescript',
	jsx: 'jsx',
	tsx: 'tsx',
	sh: 'bash',
	bash: 'bash',
	json: 'json',
	yml: 'yaml',
	yaml: 'yaml',
	md: 'markdown',
	markdown: 'markdown',
	sql: 'sql',
	css: 'css',
	html: 'html',
	htm: 'html',
	xml: 'xml',
	csv: 'csv',
	txt: ''
};

export const sandboxLang = (name: string) =>
	EXT_LANG[(name || '').split('.').pop()?.toLowerCase() ?? ''] ?? '';

export const fetchSandboxFile = async (path: string) => {
	const res = await fetch(`/api/owui/chat-file?path=${encodeURIComponent(path)}`, {
		headers: { Authorization: `Bearer ${localStorage.token}` }
	});
	if (!res.ok) {
		const j = await res.json().catch(() => ({}));
		throw new Error(j?.detail || `HTTP ${res.status}`);
	}
	return await res.json();
};

// What the right-hand panel should show for this file. A script is shown AS a script —
// highlighted, in the app's own theme. It used to be dumped into a white plaintext iframe,
// which is a worse way to read code than the chat bubble it came from.
export const buildSandboxArtifact = (data: any) => {
	const name = String(data?.name || '');
	const isSvg = /\.svg$/i.test(name) || String(data?.mime).includes('svg');
	const isHtml = /\.html?$/i.test(name) || String(data?.mime).includes('html');
	if (data?.is_binary) {
		return {
			type: 'iframe',
			name,
			content: `<!doctype html><html><body style="margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#fff"><img src="${data.data_url}" alt="preview" style="max-width:100%;height:auto"/></body></html>`
		};
	}
	if (isSvg) return { type: 'svg', name, content: data.content };
	if (isHtml) return { type: 'iframe', name, content: data.content };
	return { type: 'code', name, lang: sandboxLang(name), content: String(data?.content ?? '') };
};

// Scaffolding — Harvis's own seed docs and the doc names a model habitually drops beside
// them. The backend filters these out of the preview footer too; this is the second fence,
// because a path can also reach the panel by being mentioned in prose.
const NOISE_NAMES = new Set([
	'sandbox.md',
	'readme.md',
	'readme',
	'notes.md',
	'harvis-check.sh',
	'about',
	'about.md',
	'about.txt',
	'index',
	'index.md',
	'index.txt'
]);

export const sandboxBasename = (path: string) => (path || '').split('/').pop() ?? '';

export const isNoiseSandboxPath = (path: string) => {
	const name = sandboxBasename(path).toLowerCase();
	if (!name || name.startsWith('.')) return true;
	if (NOISE_NAMES.has(name)) return true;
	return /(^|\/)(__pycache__|node_modules|\.git)(\/|$)/.test(path || '');
};

// Every sandbox path this chat has mentioned — from the `sandbox_files` card the backend
// emits at the end of a run, and from bare paths written in prose.
export const extractSandboxPaths = (content: string): string[] => {
	const out: string[] = [];
	const text = typeof content === 'string' ? content : '';
	if (!text) return out;

	const cardRe = /<details\b[^>]*\btype="sandbox_files"[^>]*\bpaths="([^"]*)"/g;
	let m: RegExpExecArray | null;
	while ((m = cardRe.exec(text)) !== null) {
		const raw = m[1]
			.replace(/&quot;/g, '"')
			.replace(/&#39;/g, "'")
			.replace(/&lt;/g, '<')
			.replace(/&gt;/g, '>')
			.replace(/&amp;/g, '&');
		try {
			const parsed = JSON.parse(raw);
			if (Array.isArray(parsed)) for (const p of parsed) if (typeof p === 'string') out.push(p);
		} catch (_) {
			// a half-streamed card — skip it, the finished one arrives moments later
		}
	}

	SANDBOX_PATH_RE.lastIndex = 0;
	for (const p of text.match(SANDBOX_PATH_RE) ?? []) out.push(p);

	return out;
};

// The panel's view of the sandbox: every file this chat produced, in the order it was
// produced, each one already fetched and ready to render. It is a store rather than a
// one-shot fetch because the artifact list is rebuilt from scratch on every history
// change — a script opened by hand used to be wiped by the very next token.
export const sandboxArtifacts = writable<
	Array<{ path: string; type: string; name: string; lang?: string; content: string }>
>([]);
export const sandboxArtifactsLoading = writable(false);
// A request for the panel to select one specific file. Set here, consumed (and cleared)
// by Artifacts.svelte once the merged artifact list actually contains it — the merge is
// asynchronous, so selecting by index at call time would race.
export const sandboxSelectPath = writable<string | null>(null);

const MAX_TRACKED = 24;
const order: string[] = [];
const cache = new Map<string, any>();
const failed = new Set<string>();
const inflight = new Set<string>();

const publish = () => {
	sandboxArtifacts.set(order.filter((p) => cache.has(p)).map((p) => cache.get(p)));
};

const remember = (path: string, artifact: any) => {
	if (!order.includes(path)) {
		order.push(path);
		while (order.length > MAX_TRACKED) {
			const dropped = order.shift();
			if (dropped) {
				cache.delete(dropped);
				failed.delete(dropped);
			}
		}
	}
	cache.set(path, artifact);
	failed.delete(path);
};

// Fetch anything named here that we do not already hold. Safe to call on every history
// change: a path is fetched once, a path that 404s is not retried, and nothing blocks.
export const ensureSandboxArtifacts = async (paths: string[]) => {
	const wanted: string[] = [];
	for (const p of paths ?? []) {
		if (!p || isNoiseSandboxPath(p) || wanted.includes(p)) continue;
		wanted.push(p);
	}
	if (!wanted.length) return;

	let changed = false;
	for (const p of wanted) {
		if (!order.includes(p)) {
			order.push(p);
			changed = true;
		}
	}
	while (order.length > MAX_TRACKED) {
		const dropped = order.shift();
		if (dropped) {
			cache.delete(dropped);
			failed.delete(dropped);
		}
	}

	const todo = wanted.filter(
		(p) => order.includes(p) && !cache.has(p) && !failed.has(p) && !inflight.has(p)
	);
	if (!todo.length) {
		if (changed) publish();
		return;
	}

	todo.forEach((p) => inflight.add(p));
	sandboxArtifactsLoading.set(true);
	await Promise.all(
		todo.map(async (p) => {
			try {
				const data = await fetchSandboxFile(p);
				if (order.includes(p)) cache.set(p, { ...buildSandboxArtifact(data), path: p });
			} catch (_) {
				failed.add(p);
			} finally {
				inflight.delete(p);
			}
		})
	);
	sandboxArtifactsLoading.set(inflight.size > 0);
	publish();
};

// An artifact that came down inside the message itself (a fenced block lifted out of the
// prose) rather than from the sandbox. It has no file on disk, so it gets a synthetic key
// instead of a path — everything downstream only cares that the key is stable and unique,
// which is what lets a second click re-select the same entry instead of duplicating it.
export const openInlineArtifact = (a: {
	key: string;
	name: string;
	lang?: string;
	code: string;
	/** How the panel should render it. Defaults to source-with-highlighting. */
	type?: string;
	/** Skip focusing the panel — used when a card seeds the rail without stealing it. */
	select?: boolean;
}) => {
	if (a.select !== false) {
		showControls.set(true);
		showArtifacts.set(true);
		showEmbeds.set(false);
	}
	remember(a.key, {
		type: a.type ?? 'code',
		name: a.name,
		lang: a.lang ?? '',
		content: a.code ?? '',
		path: a.key
	});
	publish();
	if (a.select !== false) sandboxSelectPath.set(a.key);
};

// Open a sandbox file in the right-side panel. Returns false if it could not be fetched, so
// the caller can fall back to its own modal rather than failing silently. The file joins the
// artifact list rather than replacing it — the rest of the session's work stays reachable.
export const openSandboxFile = async (path: string) => {
	// Loading is flagged BEFORE the panel opens, so the panel mounts already knowing a file
	// is on its way and shows the skeleton instead of closing itself as empty.
	sandboxArtifactsLoading.set(true);
	showControls.set(true);
	showArtifacts.set(true);
	showEmbeds.set(false);
	try {
		const data = await fetchSandboxFile(path);
		remember(path, { ...buildSandboxArtifact(data), path });
		publish();
		sandboxSelectPath.set(path);
		return true;
	} catch (_) {
		return false;
	} finally {
		sandboxArtifactsLoading.set(inflight.size > 0);
	}
};
