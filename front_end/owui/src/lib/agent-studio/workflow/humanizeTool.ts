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
