<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { chatId } from '$lib/stores';
	import NeuralGraph from './workflow/NeuralGraph.svelte';
	import type { RunRow } from './workflow/runsToGraph';

	const i18n: any = getContext('i18n');

	// Dock-ready: a later dock-router phase mounts this with mode='dock'.
	export let mode: 'full' | 'dock' = 'full';
	// Embedded (e.g. the Brain "Neural Map" card): no header, fixed-height canvas.
	export let embedded = false;

	let runs: RunRow[] = [];
	let loading = true;
	let scope: 'all' | 'session' = 'all';

	const load = async () => {
		loading = true;
		try {
			const res = await fetch(`${WEBUI_BASE_URL}/api/workspace/history`, {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
			if (res.ok) {
				const data = await res.json();
				runs = data?.runs ?? [];
			}
		} catch (e) {
			console.error('global map history', e);
		}
		loading = false;
	};

	$: filtered =
		scope === 'session' && $chatId ? runs.filter((r) => r.session_id === $chatId) : runs;

	onMount(load);
</script>

<div class="w-full {embedded ? 'h-72' : 'h-full'} flex flex-col">
	{#if !embedded}
	<div
		class="flex items-center gap-3 px-4 py-2.5 border-b border-gray-100 dark:border-gray-850 shrink-0"
	>
		<span class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Neural Map')}</span>
		<div class="flex items-center gap-1 text-xs">
			<button
				class="px-2 py-1 rounded-lg {scope === 'all'
					? 'bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100'
					: 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}"
				on:click={() => (scope = 'all')}>{$i18n.t('All runs')}</button
			>
			<button
				class="px-2 py-1 rounded-lg {scope === 'session'
					? 'bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100'
					: 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}"
				on:click={() => (scope = 'session')}>{$i18n.t('This session')}</button
			>
		</div>
		<button
			class="ml-auto text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
			on:click={load}>{$i18n.t('Refresh')}</button
		>
	</div>
	{/if}

	<div class="flex-1 min-h-0 min-w-0">
		{#if loading}
			<div class="w-full h-full flex items-center justify-center text-xs text-gray-400">
				{$i18n.t('Loading…')}
			</div>
		{:else if filtered.length === 0}
			<div class="w-full h-full flex items-center justify-center text-xs text-gray-400">
				{$i18n.t('No runs yet.')}
			</div>
		{:else}
			{#key scope}
				<NeuralGraph runs={filtered} />
			{/key}
		{/if}
	</div>
</div>
