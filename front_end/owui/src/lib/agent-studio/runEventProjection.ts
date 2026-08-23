import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';

export type TerminalRunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface TerminalOutputChunk {
	stream: 'stdout' | 'stderr';
	text: string;
}

export interface TerminalRun {
	id: string;
	laneId: string;
	correlationIds?: string[];
	tool: string;
	command: string;
	cwd: string;
	status: TerminalRunStatus;
	stdout: string;
	stderr: string;
	chunks: TerminalOutputChunk[];
	exitCode: number | null;
	durationMs: number | null;
	truncated: boolean;
}

export type RunActivityStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface RunActivityItem {
	id: string;
	laneId?: string;
	correlationIds?: string[];
	tool: string;
	label: string;
	detail: string;
	status: RunActivityStatus;
}

export interface RunActivity {
	headline: string;
	summary: string;
	items: RunActivityItem[];
	counts: { files: number; searches: number; commands: number; other: number };
}

const TERMINAL_TOOL =
	/^(?:exec|run_code|run_tests|bash|shell|terminal|terminal\.exec|harvis-terminal)$/i;
const FILE_TOOL =
	/^(?:read|file_fetch|repo_read|dir_list|dir_fetch|glob|list_files|edit|write|file_write|apply_patch)$/i;
const FILE_EXPLORE_TOOL =
	/^(?:read|file_fetch|repo_read|dir_list|dir_fetch|glob|list_files)$/i;
const SEARCH_TOOL =
	/^(?:web_search|web_fetch|local_rag|memory_search|search|grep|rg|find_files|repo_search)$/i;

const asRecord = (value: unknown): Record<string, unknown> =>
	value && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};

const asString = (value: unknown): string => (typeof value === 'string' ? value : '');

const asNumber = (value: unknown): number | null => {
	if (value === null || value === undefined || value === '') return null;
	const number = Number(value);
	return Number.isFinite(number) ? number : null;
};

const eventId = (event: WorkspaceEvent): string =>
	asString(
		event.command_id ??
			event.job_id ??
			event.tool_call_id ??
			event.item_id ??
			event.action_id ??
			event.id
	);

const commandOf = (event: WorkspaceEvent): string => {
	const args = asRecord(event.args);
	return asString(args.command ?? args.cmd ?? args.script ?? args.code).trim();
};

const cwdOf = (event: WorkspaceEvent): string => {
	const args = asRecord(event.args);
	return asString(args.cwd ?? args.workdir ?? args.working_directory).trim();
};

const outputTextOf = (event: WorkspaceEvent): string =>
	asString(event.content ?? event.text ?? (typeof event.output === 'string' ? event.output : ''));

const isTerminalTool = (tool: unknown): boolean => TERMINAL_TOOL.test(asString(tool).trim());

const laneIdOf = (event: WorkspaceEvent): string =>
	[asString(event.run_id).trim(), asString(event.lane).trim()]
		.filter((value, index, values) => value && values.indexOf(value) === index)
		.join('/');

const scopedEventId = (
	scope: string,
	kind: 'command' | 'activity',
	explicitId: string,
	laneId: string,
	fallbackIndex: number
): string =>
	explicitId
		? `${scope}:${laneId || 'root'}:${kind}:${explicitId}`
		: `${scope}:${kind}:${fallbackIndex}`;

const findActiveTerminal = (
	runs: TerminalRun[],
	explicitId: string,
	tool: string,
	laneId: string
): TerminalRun | undefined => {
	if (explicitId) {
		const exact = runs.find(
			(run) =>
				(run.correlationIds ?? []).includes(explicitId) &&
				(!laneId || !run.laneId || run.laneId === laneId)
		);
		if (exact) return exact;
	}

	const active = runs.filter(
		(run) =>
			(run.status === 'queued' || run.status === 'running') &&
			(!tool || run.tool === tool || (isTerminalTool(run.tool) && isTerminalTool(tool)))
	);
	let candidates = laneId ? active.filter((run) => run.laneId === laneId) : active;
	if (laneId && candidates.length === 0) {
		candidates = active.filter((run) => !run.laneId);
	}
	if (candidates.length !== 1) return undefined;

	const run = candidates[0];
	run.laneId ||= laneId;
	if (explicitId && !(run.correlationIds ?? []).includes(explicitId)) {
		run.correlationIds ??= [];
		run.correlationIds.push(explicitId);
	}
	return run;
};

export function projectTerminalRuns(
	events: WorkspaceEvent[],
	scope = 'run'
): TerminalRun[] {
	const runs: TerminalRun[] = [];
	let fallbackIndex = 0;

	for (const event of events ?? []) {
		const tool = asString(event.tool).trim();
		const explicitId = eventId(event);
		const laneId = laneIdOf(event);

		if ((event.type === 'tool_queued' || event.type === 'queued') && isTerminalTool(tool)) {
			const id = scopedEventId(scope, 'command', explicitId, laneId, fallbackIndex++);
			if (!runs.some((run) => run.id === id)) {
				runs.push({
					id,
					laneId,
					correlationIds: explicitId ? [explicitId] : [],
					tool,
					command: commandOf(event),
					cwd: cwdOf(event),
					status: 'queued',
					stdout: '',
					stderr: '',
					chunks: [],
					exitCode: null,
					durationMs: null,
					truncated: false
				});
			}
			continue;
		}

		if (event.type === 'tool_call' && isTerminalTool(tool)) {
			const queued = findActiveTerminal(runs, explicitId, tool, laneId);
			if (queued?.status === 'queued') {
				queued.status = 'running';
				queued.command ||= commandOf(event);
				queued.cwd ||= cwdOf(event);
				continue;
			}
			const id = scopedEventId(scope, 'command', explicitId, laneId, fallbackIndex++);
			if (!runs.some((run) => run.id === id)) {
				runs.push({
					id,
					laneId,
					correlationIds: explicitId ? [explicitId] : [],
					tool,
					command: commandOf(event),
					cwd: cwdOf(event),
					status: 'running',
					stdout: '',
					stderr: '',
					chunks: [],
					exitCode: null,
					durationMs: null,
					truncated: false
				});
			}
			continue;
		}

		if (event.type === 'terminal_output') {
			const run = findActiveTerminal(runs, explicitId, tool, laneId);
			const text = outputTextOf(event);
			if (!run || !text) continue;
			const stream = event.stream === 'stderr' ? 'stderr' : 'stdout';
			run[stream] += text;
			run.chunks.push({ stream, text });
			run.truncated ||= event.truncated === true;
			continue;
		}

		if (event.type === 'tool_result') {
			const output = asRecord(event.output);
			const knownExplicitRun = runs.some(
				(run) =>
					!!explicitId &&
					(run.correlationIds ?? []).includes(explicitId) &&
					(!laneId || !run.laneId || run.laneId === laneId)
			);
			const looksTerminal =
				isTerminalTool(tool) ||
				!!commandOf(event) ||
				output.exit_code !== undefined ||
				knownExplicitRun;
			if (!looksTerminal) continue;
			let run = findActiveTerminal(runs, explicitId, tool, laneId);
			if (!run) {
				const hasUnresolvedActiveRun = runs.some(
					(candidate) =>
						candidate.status === 'queued' || candidate.status === 'running'
				);
				// A result with its own ID is safely a distinct final-only command.
				// Without an ID, do not invent a third command when active candidates
				// already exist and the backend has omitted correlation metadata.
				if (!explicitId && hasUnresolvedActiveRun) continue;
				const id = scopedEventId(scope, 'command', explicitId, laneId, fallbackIndex++);
				run = {
					id,
					laneId,
					correlationIds: explicitId ? [explicitId] : [],
					tool: tool || 'terminal',
					command: commandOf(event),
					cwd: cwdOf(event),
					status: 'running',
					stdout: '',
					stderr: '',
					chunks: [],
					exitCode: null,
					durationMs: null,
					truncated: false
				};
				runs.push(run);
			}
			const exitCode = asNumber(event.exit_code ?? output.exit_code);
			const durationMs = asNumber(event.duration_ms ?? output.duration_ms);
			run.exitCode = exitCode;
			run.durationMs = durationMs;
			run.truncated ||= event.truncated === true || output.truncated === true;
			run.status =
				event.success === false || (exitCode !== null && exitCode !== 0)
					? 'failed'
					: 'succeeded';

			// Some lanes emit only a final tool_result. Use its real previews without
			// replacing output that already arrived through terminal_output.
			if (!run.stdout) {
				const stdout = asString(output.stdout ?? output.stdout_preview ?? event.output);
				if (stdout) {
					run.stdout = stdout;
					run.chunks.push({ stream: 'stdout', text: stdout });
				}
			}
			if (!run.stderr) {
				const stderr = asString(output.stderr ?? output.stderr_preview);
				if (stderr) {
					run.stderr = stderr;
					run.chunks.push({ stream: 'stderr', text: stderr });
				}
			}
			continue;
		}

		if (event.type === 'cancelled' || event.type === 'error') {
			for (const run of runs) {
				if (run.status === 'queued' || run.status === 'running') {
					run.status = event.type === 'cancelled' ? 'cancelled' : 'failed';
				}
			}
		}
	}

	return runs;
}

const activityKind = (tool: string): keyof RunActivity['counts'] => {
	if (isTerminalTool(tool)) return 'commands';
	if (SEARCH_TOOL.test(tool)) return 'searches';
	if (FILE_EXPLORE_TOOL.test(tool)) return 'files';
	return 'other';
};

const activityLabel = (tool: string, status: RunActivityStatus): string => {
	const ending =
		status === 'failed' ? 'failed' : status === 'cancelled' ? 'cancelled' : 'completed';
	const active = status === 'running' || status === 'queued';
	if (isTerminalTool(tool)) return active ? 'Running command' : `Command ${ending}`;
	if (SEARCH_TOOL.test(tool)) return active ? 'Searching project' : `Search ${ending}`;
	if (FILE_TOOL.test(tool)) return active ? 'Exploring files' : `File activity ${ending}`;
	return active ? 'Using tool' : `Tool ${ending}`;
};

const activityDetail = (event: WorkspaceEvent): string => {
	const args = asRecord(event.args);
	return asString(
		args.command ??
			args.cmd ??
			args.path ??
			args.file_path ??
			args.query ??
			args.pattern ??
			args.preview
	).trim();
};

const formatActivitySummary = (counts: RunActivity['counts']): string => {
	const parts: string[] = [];
	if (counts.files) parts.push(`Explored ${counts.files} file${counts.files === 1 ? '' : 's'}`);
	if (counts.searches) {
		parts.push(
			counts.files
				? `${counts.searches} search${counts.searches === 1 ? '' : 'es'}`
				: `Completed ${counts.searches} search${counts.searches === 1 ? '' : 'es'}`
		);
	}
	if (counts.commands) {
		parts.push(
			parts.length
				? `ran ${counts.commands} command${counts.commands === 1 ? '' : 's'}`
				: `Ran ${counts.commands} command${counts.commands === 1 ? '' : 's'}`
		);
	}
	if (counts.other) {
		parts.push(
			parts.length
				? `${counts.other} other action${counts.other === 1 ? '' : 's'}`
				: `Completed ${counts.other} action${counts.other === 1 ? '' : 's'}`
		);
	}
	return parts.join(', ') || 'Completed work';
};

const findActiveActivity = (
	items: RunActivityItem[],
	explicitId: string,
	tool: string,
	laneId: string
): RunActivityItem | undefined => {
	if (explicitId) {
		const exact = items.find(
			(item) =>
				(item.correlationIds ?? []).includes(explicitId) &&
				(!laneId || !item.laneId || item.laneId === laneId)
		);
		if (exact) return exact;
	}

	const active = items.filter(
		(item) =>
			(item.status === 'queued' || item.status === 'running') &&
			(!tool || item.tool === tool)
	);
	let candidates = laneId ? active.filter((item) => item.laneId === laneId) : active;
	if (laneId && candidates.length === 0) {
		candidates = active.filter((item) => !item.laneId);
	}
	if (candidates.length !== 1) return undefined;

	const item = candidates[0];
	item.laneId ||= laneId;
	if (explicitId && !(item.correlationIds ?? []).includes(explicitId)) {
		item.correlationIds ??= [];
		item.correlationIds.push(explicitId);
	}
	return item;
};

export function buildRunActivity(
	events: WorkspaceEvent[],
	phase: string,
	scope = 'run'
): RunActivity {
	const items: RunActivityItem[] = [];
	const counts = { files: 0, searches: 0, commands: 0, other: 0 };
	let fallbackIndex = 0;

	for (const event of events ?? []) {
		const tool = asString(event.tool).trim();
		const explicitId = eventId(event);
		const laneId = laneIdOf(event);
		if (event.type === 'tool_call' && tool) {
			const id = scopedEventId(scope, 'activity', explicitId, laneId, fallbackIndex++);
			if (items.some((item) => item.id === id)) continue;
			const kind = activityKind(tool);
			counts[kind] += 1;
			items.push({
				id,
				laneId,
				correlationIds: explicitId ? [explicitId] : [],
				tool,
				label: activityLabel(tool, 'running'),
				detail: activityDetail(event),
				status: 'running'
			});
			continue;
		}
		if (event.type === 'tool_result') {
			const item = findActiveActivity(items, explicitId, tool, laneId);
			if (item) {
				const output = asRecord(event.output);
				const exitCode = asNumber(event.exit_code ?? output.exit_code);
				item.status =
					event.success === false || (exitCode !== null && exitCode !== 0)
						? 'failed'
						: 'succeeded';
				item.label = activityLabel(item.tool, item.status);
			}
			continue;
		}
		if (event.type === 'cancelled' || event.type === 'error') {
			for (const item of items) {
				if (item.status === 'running' || item.status === 'queued') {
					item.status = event.type === 'cancelled' ? 'cancelled' : 'failed';
				}
			}
		}
	}

	const latest = [...items].reverse().find((item) => item.status === 'running') ?? items.at(-1);
	const terminal = phase === 'done' || phase === 'error' || phase === 'cancelled';
	const summary = formatActivitySummary(counts);
	const headline = terminal
		? summary
		: latest?.label || (phase === 'connecting' ? 'Preparing workspace' : 'Working');

	return { headline, summary, items, counts };
}
