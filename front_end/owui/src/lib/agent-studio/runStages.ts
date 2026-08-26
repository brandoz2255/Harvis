// Pure stage machine for the RunProgressCard.
//
// Turns a workspace run's raw event stream + status into a digestible, HUMAN-READABLE
// progress timeline — so the user always knows which of these is happening:
//   Harvis is preparing · the model is thinking · the agent is writing ·
//   Harvis is collecting results · the run is done · something failed.
//
// The headline (the one always-visible line) is phrased as an ongoing action and weaves
// in the real engine + model names ("Starting OpenClaw…", "Waiting for gemma4:12b…",
// "Writing a file…") — never vague "Working…/Connecting…" or raw backend terms.
//
// It is TOLERANT: not every lane emits every event. A token-only lane (web-search answer,
// Kimi) never writes files, so those stages are marked `skipped` and the timeline still
// completes cleanly — the card must never look "stuck" on a stage a lane can't reach.
//
// It is also PURE over the event array, so a card reloaded from chat history (whose stream
// replays all persisted events) reconstructs the exact same final timeline.

import { phrase } from './workflow/humanizeTool';

export type StageStatus = 'pending' | 'active' | 'done' | 'error' | 'skipped';

export interface StageState {
	key: string;
	label: string; // human-readable, status-aware (ongoing phrasing while active)
	detail: string; // optional sub-line: file count, error message, cold-load hint…
	status: StageStatus;
}

// A structural subset of WorkspaceEvent so any host can pass its raw event array unchanged.
export interface RunEventLike {
	type: string;
	tool?: string;
	message?: string;
	content?: string;
	summary?: string;
	changed_files?: string[];
	agent_label?: string;
}

export interface StageOpts {
	phase: string; // awaiting|connecting|thinking|executing|running|done|error|cancelled
	engineLabel?: string; // "OpenClaw" / "Claude" / "Orchestrator" …
	modelLabel?: string; // "gemma4:12b" / "claude-sonnet-4-6" — the model doing the work
	errorMessage?: string;
	artifactCount?: number | null; // file-output count once checked (null = not yet checked)
	elapsedMs?: number; // run wall-clock, for cold-load hints
}

const TERMINAL = new Set(['done', 'error', 'cancelled']);
const FILE_TOOLS = /^(write|file_write|create_file|edit|apply_patch|patch|str_replace|multi_edit)/i;
const CONNECT_LOG =
	/(connected to|launching|starting (?:task|the)|auto-selected|streaming model|vibecode turn|workspace tools active|routing to)/i;
// After this long waiting on a model with no output yet, hint that it may be cold-loading.
const COLD_LOAD_MS = 9000;

function pick(key: string, label: string, detail: string, status: StageStatus): StageState {
	return { key, label, detail, status };
}

// Trim a provider prefix for display: "anthropic/claude-sonnet-4-6" → "claude-sonnet-4-6".
function shortModel(m?: string): string {
	const s = (m || '').trim();
	if (!s) return '';
	return s.includes('/') ? s.split('/').pop() || s : s;
}

export function computeStages(events: RunEventLike[], opts: StageOpts): StageState[] {
	const phase = opts.phase || 'connecting';
	const terminal = TERMINAL.has(phase);
	const isError = phase === 'error';
	const isCancelled = phase === 'cancelled';
	const isDone = phase === 'done';
	const evts = events || [];

	const sawAny = evts.length > 0;
	const sawAgentStart = evts.some((e) => e.type === 'agent_start');
	const sawConnect = evts.some((e) => e.type === 'log' && CONNECT_LOG.test(e.message || ''));
	const toolCalls = evts.filter((e) => e.type === 'tool_call');
	const toolCount = toolCalls.length;
	const lastTool = toolCount ? toolCalls[toolCount - 1].tool : '';
	const sawWorking =
		evts.some((e) => e.type === 'token' || e.type === 'terminal_output') || toolCount > 0;
	const fileActivity = toolCalls.some((e) => FILE_TOOLS.test(e.tool || ''));
	const doneEvt = evts.find((e) => e.type === 'done');
	const changedCount = (doneEvt?.changed_files || []).length;
	const artChecked = opts.artifactCount !== null && opts.artifactCount !== undefined;
	const artCount = opts.artifactCount || 0;

	const eng = (opts.engineLabel || '').trim();
	const model = shortModel(opts.modelLabel);
	// Cloud runs never cold-load a model — a provider-prefixed model id ("anthropic/…",
	// "openai/…", "kimi-code/…") or a cloud engine label means the wait is on the
	// provider's side, so the "local models" hint would be a lie there.
	const cloud = /\//.test((opts.modelLabel || '').trim()) || /^(claude|kimi|codex|gpt|openai)/i.test(eng);
	const agentReached = sawAgentStart || sawConnect || sawWorking || terminal;
	const slow = !terminal && !sawWorking && (opts.elapsedMs || 0) > COLD_LOAD_MS;

	const out: StageState[] = [];

	// 1 — Request received (instant feedback so the card is never blank)
	out.push(pick('received', 'Request received', '', 'done'));

	// 2 — Selecting / starting the engine
	const engineReached = !!eng || sawAny;
	out.push(
		pick(
			'engine',
			engineReached ? (eng ? `Engine: ${eng}` : 'Engine selected') : eng ? `Starting ${eng}` : 'Selecting engine',
			'',
			engineReached ? 'done' : 'active'
		)
	);

	// 3 — Preparing the workspace
	const workspaceDone = sawAny || terminal;
	out.push(
		pick('workspace', workspaceDone ? 'Workspace ready' : 'Preparing workspace', '', workspaceDone ? 'done' : engineReached ? 'active' : 'pending')
	);

	// 4 — Starting the agent
	out.push(pick('agent', agentReached ? 'Agent started' : 'Starting agent', '', agentReached ? 'done' : sawAny ? 'active' : 'pending'));

	// 5 — Waiting for the model (agent up, no output yet — the "is it stuck?" moment)
	let waitStatus: StageStatus;
	let waitLabel: string;
	let waitDetail = '';
	if (terminal || sawWorking) {
		waitStatus = 'done';
		waitLabel = 'Model responded';
	} else if (agentReached) {
		waitStatus = 'active';
		if (slow && cloud) {
			waitLabel = model ? `Waiting for ${model}` : 'Waiting for the model';
			waitDetail = eng ? `${eng} is thinking — long tasks can take a while` : 'long tasks can take a while';
		} else if (slow) {
			waitLabel = model ? `${model} may be loading` : 'The model may be loading';
			waitDetail = 'local models can take a minute';
		} else {
			waitLabel = model ? `Waiting for ${model}` : 'Waiting for the model';
		}
	} else {
		waitStatus = 'pending';
		waitLabel = 'Waiting for the model';
	}
	out.push(pick('waiting', waitLabel, waitDetail, waitStatus));

	// 6 — Agent working (tokens / tools flowing)
	let workStatus: StageStatus;
	let workLabel: string;
	if (terminal) {
		workStatus = 'done';
		workLabel = 'Agent finished';
	} else if (sawWorking) {
		workStatus = 'active';
		// A live tool wins (it's the most specific thing happening); else "<model> is working".
		workLabel = lastTool ? phrase(lastTool) : model ? `${model} is working` : 'Agent is working';
	} else {
		workStatus = 'pending';
		workLabel = 'Agent works';
	}
	out.push(pick('working', workLabel, '', workStatus));

	// 7 — Writing files (skipped for token-only lanes that never touch the tree)
	let filesStatus: StageStatus;
	let filesLabel: string;
	let filesDetail = '';
	if (fileActivity || changedCount > 0) {
		filesStatus = terminal ? 'done' : 'active';
		filesLabel = terminal ? 'Files written' : 'Writing files';
		filesDetail = changedCount ? `${changedCount} file${changedCount === 1 ? '' : 's'} changed` : '';
	} else if (terminal) {
		filesStatus = 'skipped';
		filesLabel = 'No files changed';
	} else {
		filesStatus = 'pending';
		filesLabel = 'Writing files';
	}
	out.push(pick('files', filesLabel, filesDetail, filesStatus));

	// 8 — Collecting / saving outputs (artifacts persist BEFORE `done`, so terminal = collected)
	let collectStatus: StageStatus;
	let collectLabel: string;
	if (isError || isCancelled) {
		collectStatus = 'skipped';
		collectLabel = 'Outputs skipped';
	} else if (!terminal) {
		collectStatus = 'pending';
		collectLabel = 'Collecting artifacts';
	} else {
		collectStatus = 'done';
		collectLabel = 'Outputs collected';
	}
	out.push(pick('collect', collectLabel, '', collectStatus));

	// 9 — Output ready / No output (never a stuck spinner; infer from events when no count)
	const producedOutput = artChecked ? artCount > 0 : fileActivity || changedCount > 0;
	let readyStatus: StageStatus;
	let readyLabel = 'Output';
	let readyDetail = '';
	if (isError || isCancelled) {
		readyStatus = 'skipped';
		readyLabel = 'No output';
	} else if (!terminal) {
		readyStatus = 'pending';
		readyLabel = 'Checking for output';
	} else if (producedOutput) {
		readyStatus = 'done';
		readyLabel = 'Output ready';
		readyDetail = artChecked ? `${artCount} file${artCount === 1 ? '' : 's'}` : '';
	} else {
		readyStatus = 'skipped';
		readyLabel = 'No file output';
	}
	out.push(pick('ready', readyLabel, readyDetail, readyStatus));

	// 10 — Done / Error / Stopped
	let doneStatus: StageStatus;
	let doneLabel: string;
	let doneDetail = '';
	if (isError) {
		doneStatus = 'error';
		doneLabel = 'Error';
		doneDetail = (opts.errorMessage || '').slice(0, 200);
	} else if (isCancelled) {
		doneStatus = 'skipped';
		doneLabel = 'Stopped';
	} else if (isDone) {
		doneStatus = 'done';
		doneLabel = 'Done';
	} else {
		doneStatus = 'pending';
		doneLabel = 'Finalizing';
	}
	out.push(pick('done', doneLabel, doneDetail, doneStatus));

	return out;
}

// The stage to surface in the always-visible one-line summary: the first active stage,
// else any error, else the last completed/skipped one, else the first.
export function activeStage(stages: StageState[]): StageState {
	return (
		stages.find((s) => s.status === 'active') ||
		stages.find((s) => s.status === 'error') ||
		[...stages].reverse().find((s) => s.status === 'done' || s.status === 'skipped') ||
		stages[0]
	);
}
