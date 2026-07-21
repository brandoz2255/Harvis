<script lang="ts">
	import { getContext } from 'svelte';
	import RunWorkspace from '$lib/agent-studio/RunWorkspace.svelte';
	// Shared status palette — the single source of truth (cancelled=gray, NOT amber:
	// amber is reserved for "needs YOU", i.e. awaiting approval).
	import { statusDot as dot } from '$lib/agent-studio/runFormat';

	const i18n: any = getContext('i18n');

	// A compact background-task row (Claude-Code density): line 1 = title + elapsed;
	// line 2 = Type · Status + a status dot. Expands IN PLACE to the run's detail
	// (folded phases → per-agent table, Table⇄Graph) — no separate page, stays in the chat.
	export let run: any;
	export let expanded = false;
	export let onToggle: (id: string) => void = () => {};
	export let onStop: ((id: string) => void) | null = null;

	const fmtDur = (ms?: number): string =>
		!ms
			? ''
			: ms < 60000
				? `${Math.round(ms / 1000)}s`
				: `${Math.floor(ms / 60000)}m${String(Math.round((ms % 60000) / 1000)).padStart(2, '0')}s`;
	const statusLabel = (s?: string): string =>
		s === 'running'
			? $i18n.t('Running')
			: s === 'done'
				? $i18n.t('Completed')
				: s === 'error'
					? $i18n.t('Failed')
					: s === 'cancelled'
						? $i18n.t('Cancelled')
						: $i18n.t('Pending');
	$: isWorkflow = (run?.child_count ?? 0) > 0;
	$: typeLabel = isWorkflow ? $i18n.t('Workflow') : $i18n.t('Task');
	$: running = run?.status === 'running';
</script>

<div class="rounded-lg border border-gray-100 dark:border-gray-850 overflow-hidden">
	<button
		type="button"
		class="w-full text-left px-2.5 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-850/60 transition"
		on:click={() => onToggle(run.id)}
	>
		<div class="flex items-center gap-2">
			<span class="truncate text-xs text-gray-700 dark:text-gray-200"
				>{run.task_brief || $i18n.t('Workspace run')}</span
			>
			<span class="ml-auto text-[10px] text-gray-400 tabular-nums shrink-0">{fmtDur(run.duration_ms)}</span>
		</div>
		<div class="flex items-center gap-1.5 mt-0.5">
			<span class="size-1.5 rounded-full shrink-0 {dot(run.status)}"></span>
			<span class="text-[11px] text-gray-400">{typeLabel} · {statusLabel(run.status)}</span>
			{#if onStop && running}
				<button
					type="button"
					class="ml-auto text-[10px] text-red-500 hover:text-red-400 transition"
					on:click|stopPropagation={() => onStop && onStop(run.id)}>{$i18n.t('Stop')}</button
				>
			{/if}
		</div>
	</button>
	{#if expanded}
		<div class="border-t border-gray-100 dark:border-gray-850 px-1.5 py-1.5">
			{#key run.id}<RunWorkspace wsId={run.id} />{/key}
		</div>
	{/if}
</div>
