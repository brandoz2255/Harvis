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
	(tool && (PHRASES[tool] ?? PHRASES[tool.toLowerCase()] ?? VERBS[tool.toLowerCase()])) ||
	(tool ? `Using ${tool}` : 'Working');

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
	rag_search: 'Searching docs',
	// The CLI engines (claude-code, codex) emit their OWN tool names — capitalized, and
	// nothing like the native runner's. Every one of them used to fall through to the
	// "Using <tool>" escape hatch, which is how a turn that wrote eight files narrated
	// itself as "Using Bash". Lookup is case-insensitive, so these cover both spellings.
	bash: 'Running',
	read: 'Reading',
	write: 'Writing',
	edit: 'Editing',
	multiedit: 'Editing',
	notebookedit: 'Editing',
	glob: 'Finding files',
	grep: 'Searching',
	todowrite: 'Planning',
	task: 'Delegating',
	// Counted off the event log, not guessed: ToolSearch is the third most-called tool in
	// this database (23 calls) and had no entry at all.
	toolsearch: 'Finding tools',
	skill: 'Using skill',
	agent: 'Delegating',
	webfetch: 'Fetching',
	websearch: 'Researching',
	bashoutput: 'Reading command output',
	killshell: 'Stopping a command'
};

// tool → candidate arg keys shown inline (first non-empty wins).
const INLINE_ARG: Record<string, string[]> = {
	exec: ['preview', 'command'],
	'harvis-terminal': ['preview', 'command'],
	run_tests: ['preview', 'command'],
	read_file: ['file_path', 'path', 'file', 'filename'],
	edit_file: ['file_path', 'path', 'file', 'filename'],
	write_file: ['file_path', 'path', 'file', 'filename'],
	str_replace: ['file_path', 'path', 'file', 'filename'],
	apply_patch: ['file_path', 'path', 'file', 'filename'],
	list_files: ['path', 'dir'],
	'browser/navigate': ['url', 'href'],
	web_fetch: ['url', 'href'],
	web_search: ['query', 'q'],
	memory_search: ['query', 'q'],
	memory_search_unified: ['query', 'q'],
	memory_get: ['key', 'name'],
	local_rag: ['query', 'q'],
	rag_search: ['query', 'q'],
	// CLI-engine arg shapes. `file_path` is Claude Code's key for every file tool, and a
	// Bash call carries the literal command — which is the thing worth showing.
	bash: ['command', 'description'],
	read: ['file_path', 'path', 'file', 'filename'],
	write: ['file_path', 'path'],
	edit: ['file_path', 'path'],
	multiedit: ['file_path', 'path'],
	notebookedit: ['notebook_path', 'file_path'],
	glob: ['pattern'],
	grep: ['pattern', 'query'],
	task: ['description'],
	toolsearch: ['query'],
	skill: ['skill'],
	agent: ['description', 'subagent_type'],
	webfetch: ['url'],
	websearch: ['query', 'q']
};

const QUOTED = new Set(['query', 'q', 'pattern']);
const CMD = new Set(['preview', 'command', 'description']);
const basename = (p: string) => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || p;

// The CLI engines report ABSOLUTE paths inside their sandbox (/work/js/game.js). A bare
// basename loses the folder, which is the half that matters once a build writes more than
// one file — "Writing game.js" and "Writing entities/ship.js" are different edits. Strip the
// workspace root and keep the rest; an unrecognized absolute path keeps its last two segments.
const WORKSPACE_ROOT = /^(?:.*\/harvis-vibecode-sessions\/[^/]+|\/work(?:space)?|\/app|\/repo|\/home\/[^/]+)\//;
const relPath = (p: string): string => {
	const clean = p.replace(/[\\/]+$/, '');
	const stripped = clean.replace(WORKSPACE_ROOT, '');
	if (stripped !== clean) return stripped;
	if (!/^[\\/]/.test(clean)) return clean; // already relative — the useful case
	const parts = clean.split(/[\\/]/).filter(Boolean);
	return parts.slice(-2).join('/') || clean;
};
const clip = (s: string, n: number) => (s.length <= n ? s : s.slice(0, n - 1) + '…');

// "Editing hello.txt" / "Running: npm test" / "Researching \"how to…\"".
export const stepLabel = (tool?: string, args?: Record<string, unknown> | null): string => {
	// Case-insensitive: the native runner sends `edit_file`, Claude Code sends `Edit`.
	const key = (tool ?? '').toLowerCase();
	const verb = (tool && (VERBS[tool] ?? VERBS[key])) || (tool ? `Using ${tool}` : 'Working');
	const keys = tool ? (INLINE_ARG[tool] ?? INLINE_ARG[key]) : undefined;
	if (!keys || !args) return verb;
	for (const k of keys) {
		const raw = args[k];
		if (typeof raw !== 'string') continue;
		const v = raw.trim();
		if (!v) continue;
		if (QUOTED.has(k)) return `${verb}: "${clip(v, 60)}"`;
		if (CMD.has(k)) return `${verb}: ${clip(v, 60)}`;
		// path/url: workspace-relative path for files, full URL otherwise.
		const isUrl = /^https?:\/\//i.test(v);
		return `${verb} ${clip(isUrl ? v : relPath(v), 48)}`;
	}
	return verb;
};
