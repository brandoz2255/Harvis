<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_BASE_URL } from '$lib/constants';

	const i18n: any = getContext('i18n');

	type Run = {
		id: string;
		task_brief?: string;
		status?: string;
		duration_ms?: number;
		tool_calls?: number;
		final_summary?: string;
		error_message?: string;
	};

	// Additive embed props — defaults preserve the original standalone behavior
	// (self-fetching panel with header, mounted by Agent Studio + the right rail).
	export let embed = false; // hide header + outer chrome (parent provides the card)
	export let statuses: string[] | null = null; // filter to these status values
	export let onOpenRun: ((id: string) => void) | null = null; // override goto(run page)
	export let runsOverride: Run[] | null = null; // parent-supplied runs; skips self-fetch
	export let emptyText: string | null = null;

	let runs: Run[] = [];
	let loading = true;
	let error = '';
	let expandedId: string | null = null;

	const load = async () => {
		loading = true;
		error = '';
		try {
			const res = await fetch(`${WEBUI_BASE_URL}/api/workspace/history`, {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			runs = data?.runs ?? [];
		} catch (e: any) {
			error = String(e?.message ?? e);
		} finally {
			loading = false;
		}
	};

	$: sourceRuns = runsOverride ?? runs;
	$: shownRuns = statuses ? sourceRuns.filter((r) => statuses.includes(r.status ?? '')) : sourceRuns;
	$: isLoading = runsOverride !== null ? false : loading;

	const dot = (s?: string) =>
		s === 'done'
			? 'bg-blue-500'
			: s === 'error'
				? 'bg-red-500'
				: s === 'cancelled'
					? 'bg-amber-500'
					: 'bg-blue-500 animate-pulse';

	const fmtDur = (ms?: number) =>
		ms ? (ms < 60000 ? `${Math.round(ms / 1000)}s` : `${Math.round(ms / 60000)}m`) : '';

	const openRun = (id: string) => {
		if (onOpenRun) {
			onOpenRun(id);
		} else {
			goto(`/harvis/agent-studio/run/${id}`);
		}
	};

	onMount(() => {
		if (runsOverride === null) load();
	});
</script>

<div class={embed ? 'text-sm' : 'h-full overflow-y-auto px-3 pt-1 pb-4 text-sm'}>
	{#if !embed}
		<div class="flex items-center justify-between mb-2">
			<div class="font-medium text-gray-700 dark:text-gray-200">{$i18n.t('Artifacts')}</div>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
				on:click={load}>{$i18n.t('Refresh')}</button
			>
		</div>
	{/if}

	{#if isLoading}
		<div class="text-gray-400 text-xs py-4">{$i18n.t('Loading…')}</div>
	{:else if error}
		<div class="text-red-500 text-xs py-2">{error}</div>
	{:else if shownRuns.length === 0}
		<div class="text-gray-400 text-xs py-2">{emptyText ?? $i18n.t('No workspace runs yet.')}</div>
	{:else}
		<div class="space-y-1.5">
			{#each shownRuns as r (r.id)}
				<button
					class="w-full text-left rounded-xl border border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-850 transition px-3 py-2"
					on:click={() => (expandedId = expandedId === r.id ? null : r.id)}
				>
					<div class="flex items-center gap-2">
						<span class="size-2 rounded-full shrink-0 {dot(r.status)}"></span>
						<span class="truncate text-gray-700 dark:text-gray-200"
							>{r.task_brief || $i18n.t('Workspace run')}</span
						>
						<span class="ml-auto text-[11px] text-gray-400 tabular-nums shrink-0">
							{#if r.tool_calls}{r.tool_calls} 🔧 {/if}{fmtDur(r.duration_ms)}
						</span>
					</div>
					{#if expandedId === r.id}
						<div class="mt-2 text-xs text-gray-500 whitespace-pre-wrap">
							{r.final_summary || r.error_message || $i18n.t('No summary.')}
						</div>
						<button
							class="mt-2 text-[11px] px-2 py-0.5 rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition"
							on:click|stopPropagation={() => openRun(r.id)}
							>{$i18n.t('Open run')}</button
						>
					{/if}
				</button>
			{/each}
		</div>
	{/if}
</div>
