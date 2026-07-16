// Humanize raw tool names → readable phrases. Mirrors the PHRASES map in
// WorkspaceRunCard.svelte (kept local there to avoid touching the working card;
// this is the shared source for the Agent Studio workflow surfaces).

const PHRASES: Record<string, string> = {
	exec: 'Running a command',
	run_code: 'Running code',
	read: 'Reading a file',
	file_fetch: 'Reading a file',
	write: 'Writing a file',
	file_write: 'Writing a file',
	edit: 'Editing a file',
	dir_list: 'Scanning the project',
	dir_fetch: 'Scanning the project',
	web_search: 'Searching the web',
	web_fetch: 'Reading a web page',
	browser: 'Browsing',
	local_rag: 'Searching knowledge',
	memory_search: 'Recalling memory'
};

// No-ellipsis label — for static node titles.
export const toolLabel = (tool?: string): string =>
	(tool && PHRASES[tool]) || (tool ? `Using ${tool}` : 'Working');

// With trailing ellipsis — for in-progress stream lines (matches WorkspaceRunCard).
export const phrase = (tool?: string): string => `${toolLabel(tool)}…`;

// ── Filename-aware step labels ──────────────────────────────────────────────
// Mirrors the Discord _TOOL_LABELS / _TOOLS_WITH_INLINE_ARG maps so the web
// line-by-line progress reads identically to #harvis-code: "Editing hello.txt",
// "Running: npm test", "Reading src/app.py", "Researching \"query\"" — a Cursor-
// style step lineup instead of a bare "Working…". Superset of the runner + engine
// tool names (native str_replace/apply_patch/edit_file, OpenClaw read/write, etc.).
const VERBS: Record<string, string> = {
	exec: 'Running',
	'harvis-terminal': 'Running',
	run_tests: 'Running tests',
	run_code: 'Running code',
	read: 'Reading',
	read_file: 'Reading',
	file_fetch: 'Reading',
	list_files: 'Listing',
	dir_list: 'Scanning',
	dir_fetch: 'Scanning',
	write: 'Writing',
	write_file: 'Writing',
	file_write: 'Writing',
	edit_file: 'Writing',
	edit: 'Editing',
	str_replace: 'Editing',
	apply_patch: 'Editing',
	git_commit: 'Committing',
	'browser/session': 'Opening browser',
	'browser/navigate': 'Navigating to',
	'browser/screenshot': 'Taking screenshot',
	'browser/act': 'Interacting with page',
	'browser/close': 'Closing browser',
	browser: 'Browsing',
	web_search: 'Researching',
	web_fetch: 'Fetching',
	memory_search: 'Searching memory',
	memory_search_unified: 'Searching memory',
	memory_store: 'Saving memory',
	memory_get: 'Recalling memory',
	local_rag: 'Searching docs',
	rag_search: 'Searching docs'
};

// tool → candidate arg keys shown inline (first non-empty wins).
const INLINE_ARG: Record<string, string[]> = {
	exec: ['preview', 'command'],
	'harvis-terminal': ['preview', 'command'],
	run_tests: ['preview', 'command'],
	read_file: ['path', 'file', 'filename'],
	read: ['path', 'file', 'filename'],
	edit_file: ['path', 'file', 'filename'],
	write: ['path', 'file', 'filename'],
	write_file: ['path', 'file', 'filename'],
	str_replace: ['path', 'file', 'filename'],
	apply_patch: ['path', 'file', 'filename'],
	list_files: ['path', 'dir'],
	'browser/navigate': ['url', 'href'],
	web_fetch: ['url', 'href'],
	web_search: ['query', 'q'],
	memory_search: ['query', 'q'],
	memory_search_unified: ['query', 'q'],
	memory_get: ['key', 'name'],
	local_rag: ['query', 'q'],
	rag_search: ['query', 'q']
};

const QUOTED = new Set(['query', 'q']);
const CMD = new Set(['preview', 'command']);
const basename = (p: string) => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || p;
const clip = (s: string, n: number) => (s.length <= n ? s : s.slice(0, n - 1) + '…');

// "Editing hello.txt" / "Running: npm test" / "Researching \"how to…\"".
export const stepLabel = (tool?: string, args?: Record<string, unknown> | null): string => {
	const verb = (tool && VERBS[tool]) || (tool ? `Using ${tool}` : 'Working');
	const keys = tool ? INLINE_ARG[tool] : undefined;
	if (!keys || !args) return verb;
	for (const k of keys) {
		const raw = args[k];
		if (typeof raw !== 'string') continue;
		const v = raw.trim();
		if (!v) continue;
		if (QUOTED.has(k)) return `${verb}: "${clip(v, 60)}"`;
		if (CMD.has(k)) return `${verb}: ${clip(v, 60)}`;
		// path/url: show the basename for file paths (Cursor-style), full URL otherwise.
		const isUrl = /^https?:\/\//i.test(v);
		return `${verb} ${clip(isUrl ? v : basename(v), 48)}`;
	}
	return verb;
};
