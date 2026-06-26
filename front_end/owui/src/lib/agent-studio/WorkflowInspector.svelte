<script lang="ts">
	import { getContext, onDestroy, createEventDispatcher } from 'svelte';
	import {
		createWorkspaceStream,
		WORKSPACE_TERMINAL,
		type WorkspaceEvent
	} from '$lib/apis/streaming/workspace-stream';
	import { getRunTree, type RunNode } from '$lib/apis/agent-runs';
	import { statusDot } from './runFormat';
	import AgentSession from './AgentSession.svelte';
	import RunTable from './RunTable.svelte';
	import RunArtifacts from './RunArtifacts.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	// Workflow Inspector: enter a run and inspect its sub-agents. Multi-agent → a left rail
	// (Overview + one entry per sub-agent); click one → its chat-like session. Single-agent
	// → render that session directly. ONE shared stream (the parent carries every agent's
	// events tagged with run_id); getRunTree gives the agent list + metadata.
	export let wsId = '';
	export let initialTab: string = 'overview'; // 'overview' | a child run_id

	let events: WorkspaceEvent[] = [];
	let phase: 'connecting' | 'running' | 'done' | 'error' | 'cancelled' = 'connecting';
	let run: RunNode | null = null;
	let children: RunNode[] = [];
	let activeTab = initialTab;
	let controller: AbortController | null = null;
	let treeTimer: any = null;
	let activeId = '';

	$: running = phase === 'connecting' || phase === 'running';
	$: isMulti = children.length > 0;

	// Group events by emitting agent once (orchestrator + single-agent → run_id === wsId).
	$: byRun = (() => {
		const m = new Map<string, WorkspaceEvent[]>();
		for (const e of events) {
			const k = (e.run_id as string) || run?.id || wsId;
			if (!m.has(k)) m.set(k, []);
			m.get(k)!.push(e);
		}
		return m;
	})();
	const eventsFor = (id: string): WorkspaceEvent[] => byRun.get(id) || [];
	const railLabel = (c: RunNode): string =>
		eventsFor(c.id).find((e) => e.agent_label)?.agent_label ||
		c.role ||
		(c.task ? c.task.slice(0, 24) : 'Agent');
	const childFor = (id: string): RunNode | null => children.find((c) => c.id === id) || null;

	// ── shared stream (lifted from RunView.consume: resume-on-drop, replay-rebuilds) ──
	const consume = async (id: string) => {
		controller = new AbortController();
		let failed = 0;
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
			events = []; // reconnect → replay rebuilds, so clear to avoid dupes
			phase = 'connecting';
			await new Promise((r) => setTimeout(r, 1500));
		}
	};

	// ── agent tree (lifted from RunTable: poll every 3s while running) ──
	const loadTree = async () => {
		if (!wsId) return;
		const t = await getRunTree(wsId);
		run = t.run;
		children = t.children || [];
	};
	const scheduleTree = () => {
		clearTimeout(treeTimer);
		if (running && wsId) treeTimer = setTimeout(async () => { await loadTree(); scheduleTree(); }, 3000);
	};
	// one final refresh when the run finishes (final tokens / summary / diffs)
	let lastRunning = false;
	$: {
		if (lastRunning && !running) loadTree();
		lastRunning = running;
	}

	const start = (id: string) => {
		controller?.abort();
		clearTimeout(treeTimer);
		events = [];
		phase = 'connecting';
		run = null;
		children = [];
		activeTab = initialTab;
		activeId = id;
		if (id) {
			loadTree().then(scheduleTree);
			consume(id);
		}
	};
	$: if (wsId !== activeId) start(wsId);
	onDestroy(() => {
		controller?.abort();
		clearTimeout(treeTimer);
	});
</script>

<div class="h-full flex flex-col min-h-0">
	<!-- top tab bar: Overview + one tab per sub-agent (sift through every agent's result);
	     ✕ closes the inspector and brings the workspace dock back. -->
	<div class="shrink-0 flex items-center gap-1 border-b border-white/8 bg-[#080c16] px-2 py-1.5 overflow-x-auto">
		{#if isMulti}
			<button
				class="shrink-0 px-2.5 py-1 rounded-md text-xs whitespace-nowrap transition {activeTab === 'overview'
					? 'bg-white/10 text-gray-100'
					: 'text-gray-400 hover:bg-white/5'}"
				on:click={() => (activeTab = 'overview')}
			>
				{$i18n.t('Overview')}
			</button>
			{#each children as c (c.id)}
				<button
					class="shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs whitespace-nowrap transition {activeTab ===
					c.id
						? 'bg-white/10 text-gray-100'
						: 'text-gray-400 hover:bg-white/5'}"
					title={railLabel(c)}
					on:click={() => (activeTab = c.id)}
				>
					<span class="size-2 rounded-full shrink-0 {statusDot(c.status)}"></span>
					<span class="truncate max-w-[10rem]">{railLabel(c)}</span>
				</button>
			{/each}
		{:else if run}
			<span class="flex items-center gap-1.5 px-2 text-xs text-gray-300 min-w-0">
				<span class="size-2 rounded-full shrink-0 {statusDot(run.status)}"></span>
				<span class="truncate">{railLabel(run)}</span>
			</span>
		{/if}
		<button
			class="ml-auto shrink-0 p-1.5 text-gray-400 hover:text-gray-100 hover:bg-white/5 rounded transition"
			title={$i18n.t('Close')}
			aria-label={$i18n.t('Close')}
			on:click={() => dispatch('close')}
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4"
				><path d="M6 6l12 12M18 6 6 18" stroke-linecap="round" /></svg
			>
		</button>
	</div>

	<!-- body: the selected agent's session, or the Overview -->
	<div class="flex-1 min-h-0">
		{#if isMulti}
			{#if activeTab === 'overview'}
				<div class="h-full overflow-y-auto p-3 space-y-3">
					{#if run?.error}
						<div class="text-sm text-red-400 whitespace-pre-wrap break-words">{run.error}</div>
					{:else if run?.summary}
						<div class="text-sm text-gray-200 whitespace-pre-wrap break-words">{run.summary}</div>
					{/if}
					<RunTable {wsId} live={running} on:viewAgent={(e) => (activeTab = e.detail.id)} />
					<RunArtifacts {wsId} mode="all" done={!running} />
				</div>
			{:else}
				<div class="h-full p-3">
					{#key activeTab}
						<AgentSession agent={childFor(activeTab)} events={byRun.get(activeTab) ?? []} {running} parentId={wsId} />
					{/key}
				</div>
			{/if}
		{:else if run}
			<!-- single-agent run: no tabs, the session directly -->
			<div class="h-full p-3">
				<AgentSession agent={run} events={byRun.get(run.id) ?? []} {running} parentId={wsId} />
			</div>
		{:else}
			<div class="h-full flex items-center justify-center text-xs text-gray-500">
				{$i18n.t('Loading run…')}
			</div>
		{/if}
	</div>
</div>
