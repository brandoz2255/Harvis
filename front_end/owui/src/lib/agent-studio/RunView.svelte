<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { chatId } from '$lib/stores';
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

	const i18n: any = getContext('i18n');

	// Background-tasks panel: the per-agent table is the default body; the SvelteFlow
	// graph is one toggle away.
	let view: 'table' | 'graph' = 'table';

	// One component, two mounts: 'full' = the run page (side-by-side), 'dock' = a
	// compact, stacked version that lives in the chat right-rail pane (half-screen).
	export let wsId: string = '';
	export let mode: 'full' | 'dock' = 'full';

	let events: WorkspaceEvent[] = [];
	let phase: 'connecting' | 'running' | 'done' | 'error' | 'cancelled' = 'connecting';
	let taskBrief = '';
	let status = '';
	let controller: AbortController | null = null;
	let activeId = '';

	$: running = phase === 'connecting' || phase === 'running';

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
	const openFull = () => goto(`/harvis/agent-studio/run/${wsId}`);

	const statusDot = (s: string, p: string) => {
		if (p === 'done' || s === 'done') return 'bg-blue-500';
		if (p === 'error' || s === 'error') return 'bg-red-500';
		if (p === 'cancelled' || s === 'cancelled') return 'bg-amber-500';
		return 'bg-blue-500 animate-pulse';
	};
</script>

<div class="w-full h-full flex flex-col">
	{#if mode === 'full'}
		<!-- full-page header (breadcrumb) -->
		<div
			class="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100 dark:border-gray-850 shrink-0"
		>
			<nav class="flex items-center gap-1 text-xs text-gray-400 shrink-0">
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
			<span class="size-2 rounded-full shrink-0 {statusDot(status, phase)}"></span>
			<span class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
				{taskBrief || $i18n.t('Workspace run')}
			</span>
			<span class="ml-auto text-[11px] text-gray-400 tabular-nums shrink-0">{wsId}</span>
		</div>
		<div class="flex-1 min-h-0 flex flex-col lg:flex-row">
			<div
				class="lg:w-96 max-h-56 lg:max-h-none lg:h-full overflow-y-auto border-b lg:border-b-0 lg:border-r border-gray-100 dark:border-gray-850 px-4 py-3 shrink-0"
			>
				<RunArtifacts {wsId} done={!running} />
				<ThoughtStream {events} {running} />
			</div>
			<div class="flex-1 min-h-0 min-w-0 flex flex-col">
				<div
					class="flex items-center justify-end gap-2 px-3 py-1.5 border-b border-gray-100 dark:border-gray-850 shrink-0"
				>
					<div
						class="inline-flex items-center gap-0.5 text-[11px] rounded-md bg-gray-100 dark:bg-gray-850 p-0.5"
					>
						<button
							type="button"
							class="px-2 py-0.5 rounded transition {view === 'table'
								? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
								: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
							on:click={() => (view = 'table')}>{$i18n.t('Table')}</button
						>
						<button
							type="button"
							class="px-2 py-0.5 rounded transition {view === 'graph'
								? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
								: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
							on:click={() => (view = 'graph')}>{$i18n.t('Graph')}</button
						>
					</div>
				</div>
				{#if view === 'table'}
					<div class="flex-1 min-h-0 overflow-y-auto px-4 py-3">
						<RunTable {wsId} live={running} />
					</div>
				{:else}
					<div class="flex-1 min-h-0 min-w-0">
						<WorkflowCanvas {events} />
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
			<span class="text-xs font-medium text-gray-700 dark:text-gray-200 truncate">
				{taskBrief || $i18n.t('Workspace run')}
			</span>
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
