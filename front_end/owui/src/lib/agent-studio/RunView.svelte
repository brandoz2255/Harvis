<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { chatId, models } from '$lib/stores';
	import { type WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';
	import { subscribeRun } from '$lib/apis/streaming/runStream';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';
	import WorkflowCanvas from './workflow/WorkflowCanvas.svelte';
	import ThoughtStream from './workflow/ThoughtStream.svelte';
	import RunArtifacts from './RunArtifacts.svelte';
	import RunTable from './RunTable.svelte';
	import UsageMeter from './UsageMeter.svelte';
	import HarvisClawMascot from '$lib/components/common/HarvisClawMascot.svelte';
	import { toolLabel, stepLabel } from './workflow/humanizeTool';

	const i18n: any = getContext('i18n');

	// One component, three mounts: 'full' = the run page (side-by-side), 'dock' = a
	// compact stacked version (stream over canvas) for the right-rail pane, 'stream' =
	// a lean Cursor-style step lineup only (no canvas) for the live turn INLINE in chat.
	export let wsId: string = '';
	export let mode: 'full' | 'dock' | 'stream' = 'full';
	// `embedded` = full layout WITHOUT the breadcrumb nav header (the host — e.g. the
	// VibeCode run overlay — provides its own header + close, and we must NOT navigate away).
	export let embedded = false;
	// Optional title (the turn's task) so the dock card names itself immediately instead of
	// falling back to "Workspace run" while the meta fetch is in flight.
	export let title = '';
	// Host override for the dock's '⤢ Full' button — lets embedding pages open their
	// own in-place inspector instead of navigating away (goto stays as the fallback).
	export let onOpenFull: (() => void) | null = null;
	// Which artifact cards this view renders. The Build thread passes 'changes' so the
	// preview isn't duplicated inline — it belongs in the workspace dock, big.
	export let artifactsMode: 'all' | 'preview' | 'changes' = 'all';

	let events: WorkspaceEvent[] = [];
	let phase: 'connecting' | 'running' | 'done' | 'error' | 'cancelled' = 'connecting';
	let taskBrief = '';
	let status = '';
	let _sub: ReturnType<typeof subscribeRun> | null = null;
	let _unsubStore: (() => void) | null = null;
	let activeId = '';

	// Full-page main pane: Preview (the artifact, big) is the default; the agent
	// graph + the table are one tab away.
	let mainTab: 'preview' | 'workflow' | 'table' = 'preview';

	// Run metadata for the context/token meter (from the run record).
	let runModel = '';
	let runPromptTokens = 0;
	let runCompletionTokens = 0;
	let runContextWindow = 0;

	// The run record's status is authoritative — the stream is only a live hint. A view
	// mounted on an ALREADY-FINISHED run starts at phase 'connecting' and, if the replay
	// closes without a terminal event, never leaves it: that's what kept a pulsing dot and
	// "Working…" pinned over a task that had finished minutes earlier.
	const TERMINAL_STATUS = ['done', 'completed', 'error', 'failed', 'cancelled', 'canceled'];
	$: finishedOnServer = TERMINAL_STATUS.includes((status || '').toLowerCase());
	$: running = !finishedOnServer && (phase === 'connecting' || phase === 'running');

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
		let lastArgs: any = null;
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
				// Reset to this call's own args (or none) — never carry the PREVIOUS tool's path,
				// or "Writing" after a "read_file{path:a}" would mislabel as "Writing a".
				lastArgs = (e as any).args ?? null;
				lastAgent = (e.agent_label as string) || lastAgent;
			}
		}
		const n = subStarts.size;
		const done = subEnds.size;
		// filename-aware: "Editing hello.txt" not "Using edit_file", matching the lineup rows.
		const tool = lastTool ? stepLabel(lastTool, lastArgs).toLowerCase() : '';
		if (n > 0) {
			const base =
				done >= n
					? 'Wrapping up'
					: done > 0
						? `${done}/${n} agents done`
						: `Spawned ${n} agent${n > 1 ? 's' : ''}`;
			return lastAgent && tool ? `${base} · ${lastAgent} ${tool}…` : `${base}…`;
		}
		if (tool) return `${stepLabel(lastTool, lastArgs)}…`;
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

	// (Re)start whenever the target run changes — lets the SAME instance (the dock) switch runs
	// without a remount. Consumes via the SHARED, throttled per-run stream store (one connection
	// + one batched pipeline across every view of the run), instead of opening its own.
	const start = (id: string) => {
		_unsubStore?.();
		_unsubStore = null;
		_sub?.unsubscribe();
		_sub = null;
		events = [];
		phase = 'connecting';
		taskBrief = '';
		status = '';
		activeId = id;
		if (id) {
			loadMeta(id);
			_sub = subscribeRun(id);
			_unsubStore = _sub.store.subscribe((s) => {
				events = s.events;
				phase = s.phase;
			});
		} else {
			phase = 'error';
		}
	};
	$: if (wsId !== activeId) start(wsId);

	// The shared store lands on phase 'error' in TWO cases: a real backend `error` event
	// (the run failed — the turn surfaces that), or the reconnect breaker giving up on a
	// severed stream. Only the latter is a DISCONNECT: say so honestly + offer a retry.
	$: streamBroken = phase === 'error' && !events.some((e) => e.type === 'error');
	const retryStream = () => {
		const id = activeId;
		if (!id) return;
		// Re-subscribe: if this view held the last ref, the errored entry is torn down and
		// a fresh connection opens. (Other live subscribers keep the shared entry alive —
		// their own retry does the same.)
		activeId = '';
		start(id);
	};

	onDestroy(() => {
		_unsubStore?.();
		_sub?.unsubscribe();
	});

	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');
	const goStudio = () => goto('/harvis/agent-studio');
	const openFull = () => (onOpenFull ? onOpenFull() : goto(`/harvis/agent-studio/run/${wsId}`));

	// Unified cockpit status palette: running=blue(pulse) · done=emerald · failed=red ·
	// cancelled=gray (inert — amber is reserved for "needs YOU", i.e. awaiting approval).
	// Takes two inputs (phase + status) so it can't just call the shared statusDot directly.
	const statusDot = (s: string, p: string) => {
		if (p === 'done' || s === 'done') return 'bg-emerald-500';
		if (p === 'error' || s === 'error') return 'bg-red-500';
		if (p === 'cancelled' || s === 'cancelled') return 'bg-gray-400 dark:bg-gray-600';
		return 'bg-blue-500 animate-pulse';
	};
</script>

<div class="w-full h-full flex flex-col">
	{#if streamBroken}
		<!-- honest degraded state: the live stream dropped and reconnects gave up -->
		<div
			class="shrink-0 flex items-center gap-2 px-3 py-1.5 text-[11px] text-red-500 dark:text-red-400 bg-red-500/5 border-b border-red-500/15"
		>
			<span class="truncate">{$i18n.t('Live stream disconnected — events may be incomplete.')}</span>
			<button class="ml-auto shrink-0 underline hover:no-underline" on:click={retryStream}
				>{$i18n.t('Retry')}</button
			>
		</div>
	{/if}
	{#if mode === 'full'}
		{#if !embedded}
			<!-- full-page header (breadcrumb) -->
			<div
				class="flex items-center gap-2 px-4 py-2 border-b border-gray-100 dark:border-gray-850 shrink-0"
			>
			<HarvisClawMascot
				size={44}
				state={running ? 'working' : phase === 'error' ? 'angry' : 'idle'}
				idleCycle={running}
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
				<ThoughtStream {events} {running} onRetry={retryStream} />
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
	{:else if mode === 'stream'}
		<!-- lean live lineup: the Cursor-style step feed ONLY (no canvas), for the running
		     turn inline in the Build chat + the review mirror. Full run (canvas/table) is a
		     click away via ⤢ Full. -->
		<div
			class="flex items-center gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-850 shrink-0"
		>
			<span class="size-2 rounded-full shrink-0 {statusDot(status, phase)}"></span>
			<div class="min-w-0 flex-1">
				<div class="text-xs font-medium text-gray-700 dark:text-gray-200 truncate">
					{title || taskBrief || $i18n.t('Workspace run')}
				</div>
				{#if running && liveStatus}
					<div
						class="mt-0.5 flex items-center gap-1.5 text-[11px] text-blue-500/90 dark:text-blue-400/90 truncate"
					>
						<span
							class="inline-block size-1.5 rounded-full bg-blue-500 dark:bg-blue-400 animate-pulse shrink-0"
						></span>
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
		<!-- Artifacts auto-pop when they exist (invisible while there are none). -->
		<div class="shrink-0 max-h-[45%] overflow-y-auto px-3">
			<RunArtifacts {wsId} done={!running} mode={artifactsMode} />
		</div>
		<div class="flex-1 min-h-0 overflow-y-auto px-3 py-2">
			<ThoughtStream {events} {running} onRetry={retryStream} />
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
			<RunArtifacts {wsId} done={!running} mode={artifactsMode} />
		</div>
		<!-- Resizable split: drag the handle to push the thought stream up/down. -->
		<PaneGroup direction="vertical" class="flex-1 min-h-0">
			<Pane defaultSize={38} minSize={10} class="min-h-0">
				<div class="h-full overflow-y-auto px-3 py-2">
					<ThoughtStream {events} {running} onRetry={retryStream} />
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
