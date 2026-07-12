<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { chatId, models } from '$lib/stores';
	import {
		createWorkspaceStream,
		WORKSPACE_TERMINAL,
		type WorkspaceEvent
	} from '$lib/apis/streaming/workspace-stream';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';
	import WorkflowCanvas from './workflow/WorkflowCanvas.svelte';
	import ThoughtStream from './workflow/ThoughtStream.svelte';
	import RunArtifacts from './RunArtifacts.svelte';
	import RunTable from './RunTable.svelte';
	import UsageMeter from './UsageMeter.svelte';
	import HarvisClawMascot from '$lib/components/common/HarvisClawMascot.svelte';
	import { toolLabel } from './workflow/humanizeTool';

	const i18n: any = getContext('i18n');

	// One component, two mounts: 'full' = the run page (side-by-side), 'dock' = a
	// compact, stacked version that lives in the chat right-rail pane (half-screen).
	export let wsId: string = '';
	export let mode: 'full' | 'dock' = 'full';
	// `embedded` = full layout WITHOUT the breadcrumb nav header (the host — e.g. the
	// VibeCode run overlay — provides its own header + close, and we must NOT navigate away).
	export let embedded = false;
	// Optional title (the turn's task) so the dock card names itself immediately instead of
	// falling back to "Workspace run" while the meta fetch is in flight.
	export let title = '';
	// Host override for the dock's '⤢ Full' button — lets embedding pages open their
	// own in-place inspector instead of navigating away (goto stays as the fallback).
	export let onOpenFull: (() => void) | null = null;

	let events: WorkspaceEvent[] = [];
	let phase: 'connecting' | 'running' | 'done' | 'error' | 'cancelled' = 'connecting';
	let taskBrief = '';
	let status = '';
	let controller: AbortController | null = null;
	let activeId = '';

	// Full-page main pane: Preview (the artifact, big) is the default; the agent
	// graph + the table are one tab away.
	let mainTab: 'preview' | 'workflow' | 'table' = 'preview';

	// Run metadata for the context/token meter (from the run record).
	let runModel = '';
	let runPromptTokens = 0;
	let runCompletionTokens = 0;
	let runContextWindow = 0;

	$: running = phase === 'connecting' || phase === 'running';

	// Live token estimate (chars/4) over EVERYTHING the agent streams — token
	// deltas, tool-call args, tool outputs, logs, summaries — so the gauge moves
	// with every AI action. (OpenClaw workspace runs don't attribute per-call
	// token counts to the run record, so without this the meter would sit at 0.)
	$: liveEstimate = (() => {
		let chars = 0;
		for (const e of events) {
			const a: any = e;
			if (a.content) chars += String(a.content).length;
			if (a.args) chars += (typeof a.args === 'string' ? a.args : JSON.stringify(a.args)).length;
			if (a.output) chars += String(a.output).length;
			if (a.message) chars += String(a.message).length;
			if (a.summary) chars += String(a.summary).length;
		}
		return Math.ceil(chars / 4);
	})();

	// Meter inputs: read the run's model from the catalog ($models) for the
	// context window + price, then combine with the run's token totals + live tick.
	$: meterEntry = ($models || []).find((m: any) => m?.id === runModel);
	$: meterMeta = (meterEntry?.info?.meta as any) || {};
	$: priceIn = Number(meterMeta.price_in || 0);
	$: priceOut = Number(meterMeta.price_out || 0);
	$: isFreeModel = priceIn === 0 && priceOut === 0;
	$: ctxWindow = Number(meterMeta.context_length || runContextWindow || 24576);
	// Use the persisted record totals when present (native/cloud runs); otherwise
	// the live estimate (so OpenClaw/Discord runs still show a moving gauge).
	$: ctxUsed = Math.max(runPromptTokens || 0, liveEstimate);
	$: sessionTokens = Math.max((runPromptTokens || 0) + (runCompletionTokens || 0), liveEstimate);
	$: costUsd = (ctxUsed * priceIn + (runCompletionTokens || 0) * priceOut) / 1e6;
	$: isSubscriptionModel = /\(subscription\)/i.test(runModel) || /subscription/i.test(meterEntry?.name || '');

	// A friendly "the agent is talking" status line, derived from the live event stream:
	// orchestrated → "Spawned 3 agents · readme-content is writing a file…" / "2/3 agents
	// done…"; single-agent → the current tool phrase. Sub-agents are events whose run_id
	// differs from the parent ws id.
	$: liveStatus = (() => {
		if (!running) return '';
		const subStarts = new Set<string>();
		const subEnds = new Set<string>();
		let sawPlan = false;
		let lastTool = '';
		let lastAgent = '';
		for (const e of events) {
			const rid = e.run_id as string | undefined;
			if (rid && rid !== wsId) {
				if (e.type === 'agent_start') subStarts.add(rid);
				else if (e.type === 'agent_end') subEnds.add(rid);
			}
			if (e.type === 'plan') sawPlan = true;
			else if (e.type === 'tool_call') {
				lastTool = (e.tool as string) || lastTool;
				lastAgent = (e.agent_label as string) || lastAgent;
			}
		}
		const n = subStarts.size;
		const done = subEnds.size;
		const tool = lastTool ? toolLabel(lastTool).toLowerCase() : '';
		if (n > 0) {
			const base =
				done >= n
					? 'Wrapping up'
					: done > 0
						? `${done}/${n} agents done`
						: `Spawned ${n} agent${n > 1 ? 's' : ''}`;
			return lastAgent && tool ? `${base} · ${lastAgent} ${tool}…` : `${base}…`;
		}
		if (tool) return `${toolLabel(lastTool)}…`;
		if (sawPlan) return 'Planning the work…';
		return 'Working…';
	})();

	const loadMeta = async (id: string) => {
		try {
			const res = await fetch(`${WEBUI_BASE_URL}/api/workspace/history`, {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
			if (res.ok) {
				const data = await res.json();
				const run = (data?.runs ?? []).find((r: any) => r.id === id);
				if (run) {
					taskBrief = run.task_brief || '';
					status = run.status || '';
					runModel = run.model_name || run.model || '';
					runPromptTokens = Number(run.prompt_tokens || 0);
					runCompletionTokens = Number(run.completion_tokens || 0);
					runContextWindow = Number(run.context_window || 0);
				}
			}
		} catch (e) {
			console.error('run meta', e);
		}
	};

	const consume = async (id: string) => {
		controller = new AbortController();
		let failed = 0;
		// Resume across dropped SSE connections: the backend replays the full DB
		// history on each (re)connect, so the view PERSISTS instead of dying when
		// the stream drops mid-run. A clean `stream_end` stops the loop.
		while (activeId === id && !['done', 'error', 'cancelled'].includes(phase)) {
			let cleanEnd = false;
			let gotAny = false;
			try {
				for await (const evt of createWorkspaceStream(id, localStorage.token, controller.signal)) {
					if (evt.type === 'stream_end') {
						cleanEnd = true;
						break;
					}
					gotAny = true;
					events = [...events, evt];
					if (evt.type === 'done') phase = 'done';
					else if (evt.type === 'error') phase = 'error';
					else if (evt.type === 'cancelled') phase = 'cancelled';
					else if (phase === 'connecting') phase = 'running';
					if (WORKSPACE_TERMINAL.has(evt.type)) break;
				}
			} catch (e: any) {
				if (e?.name === 'AbortError') return;
			}
			if (cleanEnd || ['done', 'error', 'cancelled'].includes(phase) || activeId !== id) break;
			failed = gotAny ? 0 : failed + 1;
			if (failed > 20) break;
			// Reconnect: replay rebuilds the full state, so clear to avoid dupes.
			events = [];
			phase = 'connecting';
			await new Promise((r) => setTimeout(r, 1500));
		}
	};

	// (Re)start whenever the target run changes — lets the SAME instance (the dock)
	// switch runs without a remount.
	const start = (id: string) => {
		controller?.abort();
		events = [];
		phase = 'connecting';
		taskBrief = '';
		status = '';
		activeId = id;
		if (id) {
			loadMeta(id);
			consume(id);
		} else {
			phase = 'error';
		}
	};
	$: if (wsId !== activeId) start(wsId);

	onDestroy(() => controller?.abort());

	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');
	const goStudio = () => goto('/harvis/agent-studio');
	const openFull = () => (onOpenFull ? onOpenFull() : goto(`/harvis/agent-studio/run/${wsId}`));

	const statusDot = (s: string, p: string) => {
		if (p === 'done' || s === 'done') return 'bg-blue-500';
		if (p === 'error' || s === 'error') return 'bg-red-500';
		if (p === 'cancelled' || s === 'cancelled') return 'bg-amber-500';
		return 'bg-blue-500 animate-pulse';
	};
</script>

<div class="w-full h-full flex flex-col">
	{#if mode === 'full'}
		{#if !embedded}
			<!-- full-page header (breadcrumb) -->
			<div
				class="flex items-center gap-2 px-4 py-2 border-b border-gray-100 dark:border-gray-850 shrink-0"
			>
			<HarvisClawMascot
				size={44}
				state={running ? 'working' : phase === 'error' ? 'angry' : 'idle'}
				className="shrink-0 -my-1"
			/>
			<div class="min-w-0 flex-1 flex flex-col leading-tight">
				<nav class="flex items-center gap-1 text-[11px] text-gray-400 shrink-0">
					<button class="hover:text-gray-600 dark:hover:text-gray-200" on:click={backToChat}
						>{$i18n.t('Chat')}</button
					>
					<span>›</span>
					<button class="hover:text-gray-600 dark:hover:text-gray-200" on:click={goStudio}
						>{$i18n.t('Agent Studio')}</button
					>
					<span>›</span>
					<span class="text-gray-600 dark:text-gray-300">{$i18n.t('Run')}</span>
				</nav>
				<div class="flex items-center gap-2 min-w-0">
					<span class="size-2 rounded-full shrink-0 {statusDot(status, phase)}"></span>
					<span class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
						{taskBrief || $i18n.t('Workspace run')}
					</span>
				</div>
			</div>
			<div class="ml-auto flex items-center gap-3 shrink-0">
				<UsageMeter
					{ctxUsed}
					{ctxWindow}
					{sessionTokens}
					{costUsd}
					modelName={runModel}
					isFree={isFreeModel}
					live={running}
					atApiRates={isSubscriptionModel}
				/>
				<span class="text-[11px] text-gray-400 tabular-nums">{wsId}</span>
			</div>
			</div>
		{/if}
		<div class="flex-1 min-h-0 flex flex-col lg:flex-row">
			<!-- Left rail: live activity feed + the changes/diff list (compact). -->
			<div
				class="lg:w-80 max-h-56 lg:max-h-none lg:h-full overflow-y-auto border-b lg:border-b-0 lg:border-r border-gray-100 dark:border-gray-850 px-3 py-3 shrink-0 space-y-3"
			>
				<ThoughtStream {events} {running} />
				<RunArtifacts {wsId} done={!running} mode="changes" bare />
			</div>
			<!-- Main: a LARGE preview pane (default) with the agent graph + table as tabs. -->
			<div class="flex-1 min-h-0 min-w-0 flex flex-col">
				<div
					class="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-gray-100 dark:border-gray-850 shrink-0"
				>
					<div
						class="inline-flex items-center gap-0.5 text-[11px] rounded-md bg-gray-100 dark:bg-gray-850 p-0.5"
					>
						<button
							type="button"
							class="px-2.5 py-0.5 rounded transition {mainTab === 'preview'
								? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
								: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
							on:click={() => (mainTab = 'preview')}>{$i18n.t('Preview')}</button
						>
						<button
							type="button"
							class="px-2.5 py-0.5 rounded transition {mainTab === 'workflow'
								? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
								: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
							on:click={() => (mainTab = 'workflow')}>{$i18n.t('Workflow')}</button
						>
						<button
							type="button"
							class="px-2.5 py-0.5 rounded transition {mainTab === 'table'
								? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
								: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
							on:click={() => (mainTab = 'table')}>{$i18n.t('Table')}</button
						>
					</div>
					{#if running && liveStatus}
						<span class="text-[11px] text-blue-500/90 dark:text-blue-400/90 truncate"
							>{liveStatus}</span
						>
					{/if}
				</div>
				{#if mainTab === 'preview'}
					<div class="flex-1 min-h-0 min-w-0 flex flex-col p-3">
						<RunArtifacts {wsId} done={!running} mode="preview" bare fill />
					</div>
				{:else if mainTab === 'workflow'}
					<div class="flex-1 min-h-0 min-w-0">
						<WorkflowCanvas {events} />
					</div>
				{:else}
					<div class="flex-1 min-h-0 overflow-y-auto px-4 py-3">
						<RunTable {wsId} live={running} />
					</div>
				{/if}
			</div>
		</div>
	{:else}
		<!-- compact dock: a stacked, half-screen version (stream capped over canvas) -->
		<div
			class="flex items-center gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-850 shrink-0"
		>
			<span class="size-2 rounded-full shrink-0 {statusDot(status, phase)}"></span>
			<div class="min-w-0 flex-1">
				<div class="text-xs font-medium text-gray-700 dark:text-gray-200 truncate">
					{title || taskBrief || $i18n.t('Workspace run')}
				</div>
				{#if running && liveStatus}
					<div class="mt-0.5 flex items-center gap-1.5 text-[11px] text-blue-500/90 dark:text-blue-400/90 truncate">
						<span class="inline-block size-1.5 rounded-full bg-blue-500 dark:bg-blue-400 animate-pulse shrink-0"></span>
						<span class="truncate">{liveStatus}</span>
					</div>
				{/if}
			</div>
			<button
				class="ml-auto text-[11px] text-gray-400 hover:text-blue-500 transition shrink-0"
				on:click={openFull}
				title={$i18n.t('Open full')}>⤢ {$i18n.t('Full')}</button
			>
		</div>
		<!-- Artifact preview + diffs — auto-popped when an orchestrated run finishes.
		     Renders nothing until artifacts exist, so it's invisible while running. -->
		<div class="shrink-0 max-h-[55%] overflow-y-auto px-3">
			<RunArtifacts {wsId} done={!running} />
		</div>
		<!-- Resizable split: drag the handle to push the thought stream up/down. -->
		<PaneGroup direction="vertical" class="flex-1 min-h-0">
			<Pane defaultSize={38} minSize={10} class="min-h-0">
				<div class="h-full overflow-y-auto px-3 py-2">
					<ThoughtStream {events} {running} />
				</div>
			</Pane>
			<PaneResizer
				class="relative h-2 flex items-center justify-center cursor-row-resize group bg-transparent"
			>
				<div
					class="absolute inset-x-0 h-px bg-gray-100 dark:bg-gray-850 group-hover:bg-blue-500/40 transition"
				></div>
				<div
					class="relative h-1 w-8 rounded-full bg-gray-200 dark:bg-gray-700 group-hover:bg-blue-500 transition"
				></div>
			</PaneResizer>
			<Pane defaultSize={62} minSize={20} class="min-h-0 min-w-0">
				<div class="h-full min-w-0">
					<WorkflowCanvas {events} />
				</div>
			</Pane>
		</PaneGroup>
	{/if}
</div>
