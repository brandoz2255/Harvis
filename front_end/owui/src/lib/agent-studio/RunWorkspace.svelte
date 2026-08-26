<script lang="ts">
	import { onDestroy, getContext } from 'svelte';
	import { type WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';
	import { subscribeRun } from '$lib/apis/streaming/runStream';
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
	let _sub: ReturnType<typeof subscribeRun> | null = null;
	let _unsubStore: (() => void) | null = null;
	let activeId = '';
	$: running = phase === 'connecting' || phase === 'running';

	// (Re)start whenever the docked run changes — via the SHARED, throttled per-run stream store
	// so this dock shares one connection + one batched pipeline with every other view of the run.
	const start = (id: string) => {
		_unsubStore?.();
		_unsubStore = null;
		_sub?.unsubscribe();
		_sub = null;
		events = [];
		phase = 'connecting';
		activeId = id;
		if (id) {
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
	onDestroy(() => {
		_unsubStore?.();
		_sub?.unsubscribe();
	});

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
					class="text-[11px] px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-700 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
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
