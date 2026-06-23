<script lang="ts">
	import { onDestroy, getContext } from 'svelte';
	import {
		createWorkspaceStream,
		WORKSPACE_TERMINAL,
		type WorkspaceEvent
	} from '$lib/apis/streaming/workspace-stream';
	import WorkflowCanvas from './workflow/WorkflowCanvas.svelte';
	import ThoughtStream from './workflow/ThoughtStream.svelte';
	import RunArtifacts from './RunArtifacts.svelte';
	import RunTable from './RunTable.svelte';
	import RailCard from '$lib/components/common/RailCard.svelte';
	import Bolt from '$lib/components/icons/Bolt.svelte';

	const i18n: any = getContext('i18n');

	// The docked run whose live workspace to show (Processes + Map + Changes).
	export let wsId = '';

	let events: WorkspaceEvent[] = [];
	let phase: 'connecting' | 'running' | 'done' | 'error' | 'cancelled' = 'connecting';
	let controller: AbortController | null = null;
	let activeId = '';
	$: running = phase === 'connecting' || phase === 'running';

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

	// (Re)start whenever the docked run changes — same instance switches runs.
	const start = (id: string) => {
		controller?.abort();
		events = [];
		phase = 'connecting';
		activeId = id;
		if (id) consume(id);
		else phase = 'error';
	};
	$: if (wsId !== activeId) start(wsId);
	onDestroy(() => controller?.abort());

	// Dismissible cards — the Overview "pick & choose" set, persisted per user.
	// Order leads with Agents (the folded-phases table) since this mounts inside an
	// already-expanded run row; Processes + Changes default collapsed (detail one click in).
	const CARDS = [
		{ key: 'map', label: 'Agents' },
		{ key: 'processes', label: 'Processes' },
		{ key: 'changes', label: 'Changes' }
	];
	const HIDE_KEY = 'harvis-overview-cards-hidden';
	let hidden: Record<string, boolean> = {};
	try {
		hidden = JSON.parse(localStorage.getItem(HIDE_KEY) || '{}') || {};
	} catch (_) {
		hidden = {};
	}
	const persist = () => {
		try {
			localStorage.setItem(HIDE_KEY, JSON.stringify(hidden));
		} catch (_) {}
	};
	const hide = (k: string) => {
		hidden = { ...hidden, [k]: true };
		persist();
	};
	const show = (k: string) => {
		const next = { ...hidden };
		delete next[k];
		hidden = next;
		persist();
	};

	let hasChanges = false;
	// The "Agents" card defaults to the Background-tasks TABLE (per-agent Tokens/Tools/Time);
	// the SvelteFlow graph stays one toggle away.
	let agentsView: 'table' | 'graph' = 'table';
	$: hiddenCards = CARDS.filter((c) => hidden[c.key]);
</script>

<div class="space-y-2 pb-2">
	{#if hiddenCards.length}
		<div class="flex flex-wrap items-center gap-1.5 px-0.5">
			<span class="text-[11px] text-gray-400">{$i18n.t('Hidden')}:</span>
			{#each hiddenCards as c (c.key)}
				<button
					type="button"
					class="text-[11px] px-2 py-0.5 rounded-full border border-gray-200 dark:border-gray-700 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
					on:click={() => show(c.key)}>+ {$i18n.t(c.label)}</button
				>
			{/each}
		</div>
	{/if}

	{#if !hidden['map']}
		<RailCard
			title={$i18n.t('Agents')}
			dismissible
			on:dismiss={() => hide('map')}
			bodyClassName="px-2 pb-2"
		>
			<svelte:fragment slot="actions">
				<div
					class="inline-flex items-center gap-0.5 text-[11px] rounded-md bg-gray-100 dark:bg-gray-850 p-0.5"
				>
					<button
						type="button"
						class="px-1.5 py-0.5 rounded transition {agentsView === 'table'
							? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
							: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
						on:click|stopPropagation={() => (agentsView = 'table')}>{$i18n.t('Table')}</button
					>
					<button
						type="button"
						class="px-1.5 py-0.5 rounded transition {agentsView === 'graph'
							? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
							: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
						on:click|stopPropagation={() => (agentsView = 'graph')}>{$i18n.t('Graph')}</button
					>
				</div>
			</svelte:fragment>
			{#if agentsView === 'table'}
				<RunTable {wsId} live={running} />
			{:else}
				<div class="h-72 rounded-lg overflow-hidden border border-gray-100 dark:border-gray-850">
					<WorkflowCanvas {events} followLatest={running} />
				</div>
			{/if}
		</RailCard>
	{/if}

	{#if !hidden['processes']}
		<RailCard
			title={$i18n.t('Processes')}
			icon={Bolt}
			open={false}
			dismissible
			on:dismiss={() => hide('processes')}
			bodyClassName="px-3 pb-3"
		>
			<div class="max-h-72 overflow-y-auto">
				<ThoughtStream {events} {running} />
			</div>
		</RailCard>
	{/if}

	{#if !hidden['changes']}
		<RailCard
			title={$i18n.t('Changes')}
			open={false}
			dismissible
			on:dismiss={() => hide('changes')}
			bodyClassName="px-3 pb-3"
		>
			<RunArtifacts
				{wsId}
				mode="changes"
				bare
				done={!running}
				on:loaded={(e) => (hasChanges = e.detail.hasChanges)}
			/>
			{#if !hasChanges}
				<div class="text-[11px] text-gray-400">{$i18n.t('No file changes yet.')}</div>
			{/if}
		</RailCard>
	{/if}
</div>
