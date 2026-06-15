<script lang="ts">
	import { onMount, onDestroy, getContext, afterUpdate } from 'svelte';
	import { goto } from '$app/navigation';
	import { showControls, workspaceControlsTab, dockedRunId } from '$lib/stores';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import {
		createWorkspaceStream,
		WORKSPACE_TERMINAL,
		type WorkspaceEvent
	} from '$lib/apis/streaming/workspace-stream';
	import Markdown from './Markdown.svelte';
	import HarvisClawMascot from '$lib/components/common/HarvisClawMascot.svelte';
	import RunArtifacts from '$lib/agent-studio/RunArtifacts.svelte';

	const i18n: any = getContext('i18n');

	// Props come from the marked `<details type="workspace_run" …>` token.
	export let id = '';
	export let attributes: Record<string, string> = {};
	export let className = 'w-full';

	$: workspaceId = attributes?.workspaceid ?? '';
	$: taskLabel = attributes?.tasklabel ?? 'Workspace task';
	$: taskBrief = attributes?.taskbrief ?? '';
	// Opt-in approval gate (P1.5): the marker carries needsapproval="1" when the
	// run is parked pending Approve. Read once — the marker doesn't change.
	const needsApproval = attributes?.needsapproval === '1';

	type Phase =
		| 'awaiting'
		| 'connecting'
		| 'thinking'
		| 'executing'
		| 'done'
		| 'error'
		| 'cancelled';
	let phase: Phase = needsApproval ? 'awaiting' : 'connecting';
	let currentStep = 'Connecting…';
	let recent: { ok: boolean; text: string }[] = [];
	let toolCount = 0;
	let summary = '';
	let errorMessage = '';
	let fixHint = '';
	let elapsed = 0;
	// Orchestrated completion moment: one entry per sub-agent, collected from its
	// agent_end (label + its OWN finish() summary + ok + runtime). STITCHED, never
	// model-generated. changedFiles drives the inline artifact.
	let agents: { label: string; summary: string; ok: boolean; durationMs: number }[] = [];
	let changedFiles: string[] = [];

	// ── Live thought stream: a chronological feed of what the agent is doing. ──
	// think = the model's streamed reasoning/output (token events, accumulated);
	// tool  = a tool call (running → ok/fail, with args + output);
	// log   = a narrative line ("💬 …" the model emitted before acting).
	type Step =
		| { kind: 'think'; text: string }
		| { kind: 'log'; text: string }
		| { kind: 'tool'; tool: string; args: string; status: 'running' | 'ok' | 'fail'; output: string };
	let steps: Step[] = [];
	let executor = ''; // "OpenClaw" — proves who's actually executing the task
	let execModel = ''; // the model behind it
	let feedEl: HTMLElement | null = null;

	let controller: AbortController | null = null;
	let timer: ReturnType<typeof setInterval> | null = null;
	// Persist the run's start so the elapsed timer stays consistent when the card
	// remounts (you click off the running workspace and come back).
	const _startKey = `harvis.ws-start.${attributes?.workspaceid ?? ''}`;
	let startedAt = (() => {
		try {
			const s = parseInt(localStorage.getItem(_startKey) || '');
			if (s) return s;
		} catch (e) {
			/* ignore */
		}
		const now = Date.now();
		try {
			localStorage.setItem(_startKey, String(now));
		} catch (e) {
			/* ignore */
		}
		return now;
	})();

	$: running = phase === 'connecting' || phase === 'thinking' || phase === 'executing';
	// Orchestrated runs are the ones whose sub-agents emit a parent_run_id-tagged
	// agent_end → that's the gate for the rich completion block (single-agent runs
	// never populate `agents`, so they keep the plain summary path).
	$: isOrchestrated = agents.length > 0;
	// Live wall-clock (elapsed); on a reloaded finished run elapsed is 0, so fall
	// back to the longest sub-agent runtime (replay-safe, from agent_end).
	$: doneDuration = elapsed > 0 ? elapsed : Math.max(0, ...agents.map((a) => a.durationMs));

	// Map raw tool names → human phrases (mirrors chat_bridge._humanize_tool_call).
	const PHRASES: Record<string, string> = {
		exec: 'Running a command…',
		run_code: 'Running code…',
		read: 'Reading a file…',
		file_fetch: 'Reading a file…',
		write: 'Writing a file…',
		file_write: 'Writing a file…',
		edit: 'Editing a file…',
		dir_list: 'Scanning the project…',
		dir_fetch: 'Scanning the project…',
		web_search: 'Searching the web…',
		web_fetch: 'Reading a web page…',
		browser: 'Browsing…',
		local_rag: 'Searching knowledge…',
		memory_search: 'Recalling memory…'
	};
	const phrase = (tool?: string) =>
		(tool && PHRASES[tool]) || (tool ? `Using ${tool}…` : 'Working…');

	const fmt = (ms: number) => {
		const s = Math.floor(ms / 1000);
		return s < 60 ? `${s}s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	};

	// Attach clean text to the most recent tool step's output.
	const attachToolOutput = (text: string) => {
		for (let i = steps.length - 1; i >= 0; i--) {
			const s = steps[i];
			if (s.kind === 'tool') {
				s.output = (s.output ? s.output + '\n' + text : text).trim().slice(0, 400);
				steps = steps;
				return true;
			}
		}
		return false;
	};

	// Parse executor/model from system logs, surface narrative, skip the noise.
	const noteLog = (msg: string) => {
		if (/Connected to OpenClaw gateway/i.test(msg)) {
			executor = 'OpenClaw'; // shown as the chip — verifies who's running it
			return;
		}
		const lm = msg.match(/(?:local model|Auto-selected[^:]*model):\s*(.+)/i);
		if (lm) {
			if (!executor) executor = 'local model';
			execModel = lm[1].trim();
			return;
		}
		// "[exec] <output>" carries the CLEAN tool output → attach it to the tool step
		// (the raw tool_result envelope is uglier, so we prefer this).
		const toolOut = msg.match(/^\[[a-z_]+\]\s*([\s\S]+)$/i);
		if (toolOut) {
			attachToolOutput(toolOut[1]);
			return;
		}
		if (/model loading|Agent started|Task dispatched|Agent finished/i.test(msg)) {
			return;
		}
		steps = [...steps, { kind: 'log', text: msg.replace(/^💬\s*/, '').slice(0, 200) }];
	};

	const handle = (evt: WorkspaceEvent) => {
		if (evt.model) execModel = evt.model;
		switch (evt.type) {
			case 'agent_start':
				if (phase === 'connecting' || phase === 'thinking') phase = 'thinking';
				break;
			case 'token': {
				// Accumulate streamed reasoning/output into the live "thinking" bubble.
				const c = evt.content ?? '';
				if (!c) break;
				if (phase === 'connecting') phase = 'thinking';
				const last = steps[steps.length - 1];
				if (last && last.kind === 'think') {
					last.text += c;
					steps = steps;
				} else {
					steps = [...steps, { kind: 'think', text: c }];
				}
				break;
			}
			case 'log':
				if (evt.message) noteLog(String(evt.message));
				break;
			case 'tool_call':
				phase = 'executing';
				toolCount += 1;
				steps = [
					...steps,
					{
						kind: 'tool',
						tool: evt.tool ?? '',
						args: evt.args ? JSON.stringify(evt.args).replace(/^[{]|[}]$/g, '').slice(0, 120) : '',
						status: 'running',
						output: ''
					}
				];
				break;
			case 'tool_result':
				// Mark the most recent running tool step done + attach its output.
				for (let i = steps.length - 1; i >= 0; i--) {
					const s = steps[i];
					if (s.kind === 'tool' && s.status === 'running') {
						s.status = evt.success === false ? 'fail' : 'ok';
						// Prefer the clean "[exec] …" log output; fall back to the raw envelope.
						if (!s.output && evt.output) s.output = String(evt.output).trim().slice(0, 240);
						steps = steps;
						break;
					}
				}
				break;
			case 'agent_end': {
				// Only orchestrated sub-agents (the native runner) carry parent_run_id
				// AND their own finish() summary; OpenClaw's root agent_end has neither,
				// so single-agent runs fall through to the plain summary path.
				if (!evt.parent_run_id) break;
				agents = [
					...agents,
					{
						label: evt.agent_label || evt.label || $i18n.t('Agent'),
						summary: (evt.summary || 'Done.').trim(),
						ok: evt.success !== false,
						durationMs: Number(evt.duration_ms) || 0
					}
				];
				break;
			}
			case 'done':
				phase = 'done';
				summary = evt.summary ?? '';
				if (Array.isArray(evt.changed_files)) changedFiles = evt.changed_files;
				// Orchestrated runs emit changed_files — auto-open the Artifacts tab
				// (the Preview) on finish (gate: orchestrated + ≥1 file). Once per run
				// per tab so a reload of a finished chat doesn't re-pop the dock.
				if (Array.isArray(evt.changed_files) && evt.changed_files.length > 0) {
					try {
						const k = `harvis-autopop-${workspaceId}`;
						if (!sessionStorage.getItem(k)) {
							sessionStorage.setItem(k, '1');
							dockedRunId.set(workspaceId);
							workspaceControlsTab.set('activity');
							showControls.set(true);
						}
					} catch (_) {
						// sessionStorage unavailable — skip auto-pop, no harm.
					}
				}
				break;
			case 'error':
				phase = 'error';
				errorMessage = evt.message ?? 'Workspace error';
				fixHint = evt.fix_hint ?? '';
				break;
			case 'cancelled':
				phase = 'cancelled';
				break;
		}
	};

	const consume = async () => {
		if (!workspaceId) {
			phase = 'error';
			errorMessage = 'Missing workspace id.';
			return;
		}
		controller = new AbortController();
		try {
			for await (const evt of createWorkspaceStream(
				workspaceId,
				localStorage.token,
				controller.signal
			)) {
				handle(evt);
				if (WORKSPACE_TERMINAL.has(evt.type)) break;
			}
		} catch (e: any) {
			if (e?.name !== 'AbortError' && phase !== 'done') {
				phase = 'error';
				errorMessage = String(e?.message ?? e);
			}
		} finally {
			if (timer) {
				clearInterval(timer);
				timer = null;
			}
		}
	};

	const stop = async () => {
		if (!workspaceId) return;
		// Instant feedback: stop listening locally + flip the card to cancelled
		// right away, THEN tell the backend to abort the agent + model server-side.
		controller?.abort();
		if (running) {
			phase = 'cancelled';
			currentStep = 'Cancelling…';
		}
		try {
			await fetch(`${WEBUI_BASE_URL}/api/workspace/cancel/${workspaceId}`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
		} catch (e) {
			console.error('workspace cancel failed', e);
		}
	};

	const openStudio = () => goto(`/harvis/agent-studio/run/${workspaceId}`);
	// Dock THIS run's live workspace (Processes / Map / Changes) into the Overview
	// tab of the right-rail pane. Resize the pane to taste.
	const dockRun = () => {
		dockedRunId.set(workspaceId);
		workspaceControlsTab.set('overview');
		showControls.set(true);
	};

	const startTimerAndStream = () => {
		// startedAt is the persisted run start (above) — do NOT reset it here, or
		// re-entering a running workspace restarts the counter from 0.
		timer = setInterval(() => {
			if (running) elapsed = Date.now() - startedAt;
		}, 1000);
		consume();
	};

	const approve = async () => {
		phase = 'connecting';
		currentStep = 'Starting…';
		try {
			const r = await fetch(`${WEBUI_BASE_URL}/api/owui/workspace/${workspaceId}/approve`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
			if (!r.ok) throw new Error(`HTTP ${r.status}`);
			startTimerAndStream();
		} catch (e: any) {
			phase = 'error';
			errorMessage = `Couldn't start the task: ${e?.message ?? e}`;
		}
	};

	const deny = async () => {
		try {
			await fetch(`${WEBUI_BASE_URL}/api/owui/workspace/${workspaceId}/deny`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
		} catch (e) {
			console.error('workspace deny failed', e);
		}
		phase = 'cancelled';
	};

	onMount(() => {
		// A parked (approval-gated) run waits for Approve before streaming;
		// otherwise (default) stream immediately, exactly as before.
		if (needsApproval) return;
		startTimerAndStream();
	});

	onDestroy(() => {
		controller?.abort();
		if (timer) clearInterval(timer);
	});

	// Keep the live feed pinned to the newest line while the task runs.
	afterUpdate(() => {
		if (running && feedEl) feedEl.scrollTop = feedEl.scrollHeight;
	});
</script>

<div
	class="{className} relative my-2 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 px-3.5 py-3 text-sm"
>
	{#if running}
		<!-- "alive" pulse — a running task must not look identical to a finished/dead one -->
		<div
			class="pointer-events-none absolute inset-0 rounded-2xl ring-2 ring-blue-400/60 animate-pulse"
		></div>
	{/if}
	<div class="flex items-center gap-2">
		<HarvisClawMascot
			size={40}
			state={running ? 'working' : phase === 'error' ? 'angry' : 'idle'}
			className="shrink-0 -my-1.5"
		/>
		{#if running}
			<span class="relative flex size-2.5">
				<span
					class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-60"
				></span>
				<span class="relative inline-flex rounded-full size-2.5 bg-blue-500"></span>
			</span>
		{:else if phase === 'done'}
			<span class="text-blue-500 font-semibold">✓</span>
		{:else if phase === 'error'}
			<span class="text-red-500 font-semibold">!</span>
		{:else}
			<span class="text-amber-500">■</span>
		{/if}

		<span class="font-medium text-gray-700 dark:text-gray-200">
			{#if phase === 'done'}{$i18n.t('Workspace complete')}
			{:else if phase === 'error'}{$i18n.t('Workspace error')}
			{:else if phase === 'cancelled'}{$i18n.t('Workspace cancelled')}
			{:else if phase === 'awaiting'}{$i18n.t('Approval needed')}
			{:else}{taskLabel}{/if}
		</span>

		{#if phase !== 'awaiting'}
			<div class="ml-auto flex items-center gap-2 min-w-0">
				{#if executor}
					<span
						class="shrink-0 max-w-[170px] truncate text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-300 font-medium"
						title={executor + (execModel ? ' · ' + execModel : '')}
					>
						{executor}{#if execModel} · {execModel}{/if}
					</span>
				{/if}
				<span class="shrink-0 text-xs text-gray-400 tabular-nums">
					{fmt(elapsed)}{#if toolCount > 0} · {toolCount}
						{toolCount === 1 ? $i18n.t('tool') : $i18n.t('tools')}{/if}
				</span>
			</div>
		{/if}
	</div>

	{#if phase === 'error'}
		<div class="mt-1.5 text-red-600 dark:text-red-400">{errorMessage}</div>
		{#if fixHint}<div class="mt-1 text-xs text-gray-500">{fixHint}</div>{/if}
	{:else if phase === 'cancelled'}
		<div class="mt-1.5 text-gray-500">{$i18n.t('Cancelled.')}</div>
	{:else if phase === 'awaiting'}
		<div class="mt-1.5 text-gray-600 dark:text-gray-300">
			{$i18n.t('Harvis wants to run an agent task:')}
		</div>
		{#if taskBrief}
			<div class="mt-1 text-xs text-gray-500 line-clamp-3">{taskBrief}</div>
		{/if}
	{:else}
		<!-- LIVE THOUGHT STREAM (running) — stays visible on done so you can audit the work -->
		{#if steps.length}
			<div bind:this={feedEl} class="mt-2 max-h-72 overflow-y-auto space-y-1 pr-1 -mr-1">
				{#each steps as s}
					{#if s.kind === 'think'}
						<div class="text-xs text-gray-500 dark:text-gray-400 whitespace-pre-wrap leading-relaxed">{s.text}</div>
					{:else if s.kind === 'log'}
						<div class="flex items-start gap-1.5 text-xs text-gray-500 dark:text-gray-400">
							<span class="text-gray-400 shrink-0">·</span><span>{s.text}</span>
						</div>
					{:else if s.kind === 'tool'}
						<div class="rounded-lg bg-gray-100/70 dark:bg-gray-850/50 px-2 py-1">
							<div class="flex items-center gap-1.5 text-xs">
								{#if s.status === 'running'}
									<span class="inline-block size-3 rounded-full border-2 border-blue-500/40 border-t-blue-500 animate-spin shrink-0"></span>
								{:else if s.status === 'ok'}
									<span class="text-blue-500 shrink-0">✓</span>
								{:else}
									<span class="text-red-500 shrink-0">✗</span>
								{/if}
								<span class="font-medium text-gray-700 dark:text-gray-200 shrink-0">{phrase(s.tool)}</span>
								{#if s.args}<span class="text-gray-400 truncate font-mono text-[10px]">{s.args}</span>{/if}
							</div>
							{#if s.output}
								<div class="mt-0.5 text-[11px] text-gray-500 dark:text-gray-400 font-mono whitespace-pre-wrap line-clamp-4">{s.output}</div>
							{/if}
						</div>
					{/if}
				{/each}
			</div>
		{:else if running}
			<div class="mt-1.5 text-gray-600 dark:text-gray-300">{currentStep}</div>
		{/if}

		{#if phase === 'done' && isOrchestrated}
			<!-- Completion moment (orchestrated): deterministic stats + STITCHED per-agent
			     finish() summaries + the primary artifact rendered inline. Nothing generated. -->
			<div class="mt-2 pt-2 border-t border-gray-100 dark:border-gray-850 space-y-2">
				<div class="text-xs font-medium text-gray-600 dark:text-gray-300 tabular-nums">
					{$i18n.t('Done')} · {agents.length}
					{agents.length === 1 ? $i18n.t('agent') : $i18n.t('agents')} · {toolCount}
					{toolCount === 1 ? $i18n.t('tool call') : $i18n.t('tool calls')}{#if doneDuration > 0} ·
						{fmt(doneDuration)}{/if}
				</div>
				<div class="space-y-0.5">
					{#each agents as a}
						<div class="flex items-start gap-1.5 text-xs leading-relaxed">
							<span class="shrink-0 mt-px {a.ok ? 'text-blue-500' : 'text-red-500'}"
								>{a.ok ? '✓' : '✗'}</span
							>
							<span class="font-medium text-gray-700 dark:text-gray-200 shrink-0">{a.label}:</span>
							<span class="text-gray-500 dark:text-gray-400 break-words min-w-0">{a.summary}</span>
						</div>
					{/each}
				</div>
				{#if changedFiles.length}
					<RunArtifacts wsId={workspaceId} mode="all" />
				{/if}
			</div>
		{:else if phase === 'done' && summary}
			<div class="mt-2 pt-2 border-t border-gray-100 dark:border-gray-850 markdown-prose markdown-prose-sm text-sm text-gray-700 dark:text-gray-200">
				<Markdown id={`ws-summary-${workspaceId}`} content={summary} />
			</div>
		{/if}
	{/if}

	<div class="mt-2.5 flex items-center gap-2">
		{#if phase === 'awaiting'}
			<button
				class="text-xs px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition"
				on:click={approve}>{$i18n.t('Approve')}</button
			>
			<button
				class="text-xs px-3 py-1 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950 transition"
				on:click={deny}>{$i18n.t('Deny')}</button
			>
		{:else if running}
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={dockRun}>{$i18n.t('View')}</button
			>
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={openStudio}>{$i18n.t('Open Studio')}</button
			>
			<button
				class="text-xs px-2 py-1 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950 transition ml-auto"
				on:click={stop}>{$i18n.t('Stop')}</button
			>
		{:else}
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={dockRun}>{$i18n.t('View')}</button
			>
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={openStudio}>{$i18n.t('Open Studio')}</button
			>
		{/if}
	</div>
</div>
