<script lang="ts">
	import { createEventDispatcher, getContext, onDestroy } from 'svelte';
	import RunTable from '$lib/agent-studio/RunTable.svelte';
	import {
		statusDot,
		statusLabel,
		humanizeRunTitle,
		runTypeLabel,
		agentCountOf,
		fmtDuration
	} from '$lib/agent-studio/runFormat';

	const dispatch = createEventDispatcher();
	const i18n: any = getContext('i18n');

	// A single background task. Compact by default (status · title · elapsed · Stop;
	// type · N agents · phase — NO token counts); expands to the full agent metrics
	// table (reused RunTable) + Open run / View logs / Stop. `run` = a vibecode turn or
	// a workspace-history run. `live` polls the agents table while running.
	export let run: any;
	export let expanded = false;
	export let live = false;
	// Seed expanded=true ONCE when the run becomes multi-agent (so a fan-out auto-opens
	// its live agent table the moment it spawns) — then the user controls it freely.
	export let autoExpand = false;
	let _seeded = false;
	$: if (autoExpand && !_seeded) {
		expanded = true;
		_seeded = true;
	}

	$: status = run?.status;
	$: isRunning = status === 'running';
	$: agentCount = agentCountOf(run);
	$: prompt = (run?.task_brief || run?.task || '').toString().trim();

	// Live elapsed ticker for running tasks; finished tasks use the stored duration.
	let nowTick = Date.now();
	let timer: any = null;
	$: {
		if (isRunning && run?.started_at && !timer) {
			timer = setInterval(() => (nowTick = Date.now()), 1000);
		} else if (!isRunning && timer) {
			clearInterval(timer);
			timer = null;
		}
	}
	onDestroy(() => timer && clearInterval(timer));
	$: elapsedMs =
		!isRunning && run?.duration_ms != null
			? run.duration_ms
			: run?.started_at
				? nowTick - new Date(run.started_at).getTime()
				: run?.duration_ms || 0;
	$: elapsed = fmtDuration(elapsedMs);

	const toggle = () => (expanded = !expanded);
</script>

<div class="rounded-xl border border-white/8 bg-[#121a2e] overflow-hidden">
	<!-- Compact head (always) -->
	<div
		class="w-full text-left px-3 py-2.5 hover:bg-white/4 transition cursor-pointer"
		role="button"
		tabindex="0"
		on:click={toggle}
		on:keydown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), toggle())}
	>
		<div class="flex items-center gap-2">
			<span class="size-2 rounded-full shrink-0 {statusDot(status)}"></span>
			<span class="flex-1 truncate text-xs font-medium text-gray-100"
				>{humanizeRunTitle(run)}</span
			>
			{#if elapsed}<span class="text-[11px] text-gray-500 tabular-nums shrink-0">{elapsed}</span>{/if}
			{#if isRunning}
				<button
					class="shrink-0 text-gray-500 hover:text-red-400 transition"
					aria-label={$i18n.t('Stop')}
					title={$i18n.t('Stop')}
					on:click|stopPropagation={() => dispatch('stop', { id: run.id })}
				>
					<svg viewBox="0 0 20 20" fill="currentColor" class="size-3.5"
						><rect x="5" y="5" width="10" height="10" rx="1.5" /></svg
					>
				</button>
			{/if}
		</div>
		<div class="mt-0.5 pl-4 flex items-center gap-1.5 text-[11px] text-gray-500 truncate">
			<span>{$i18n.t(runTypeLabel(run, agentCount))}</span>
			{#if agentCount}
				<span>· {agentCount} {agentCount === 1 ? $i18n.t('agent') : $i18n.t('agents')}</span>
			{/if}
			{#if isRunning && agentCount > 1}
				<span>· {run?.done_count ?? ''}{run?.done_count != null ? '/' : ''}{agentCount} {$i18n.t('agents')}</span>
			{:else if !isRunning}
				<span>· {$i18n.t(statusLabel(status))}</span>
			{/if}
		</div>
	</div>

	<!-- Expanded body (technical metrics one click away) -->
	{#if expanded}
		<div class="border-t border-white/8 px-3 py-2.5 space-y-2 bg-[#0d1320]">
			{#if prompt}
				<p class="text-[11px] leading-snug text-gray-400 whitespace-pre-wrap">
					{prompt}
				</p>
			{/if}
			<!-- Agents + tokens/tools/time (reused RunTable; folds phases internally).
			     Clicking an agent row opens the inspector focused on THAT agent's tab. -->
			<RunTable
				wsId={run.id}
				live={isRunning && live}
				on:viewAgent={(e) => dispatch('viewLogs', { id: run.id, agentTab: e.detail.id })}
			/>
			<div class="flex items-center gap-1.5 pt-0.5">
				<button
					class="text-[11px] px-2 py-1 text-blue-400 hover:bg-white/4 transition"
					on:click={() => dispatch('openRun', { id: run.id })}>{$i18n.t('Open run')}</button
				>
				<button
					class="text-[11px] px-2 py-1 text-gray-300 hover:bg-white/4 transition"
					on:click={() => dispatch('viewLogs', { id: run.id })}>{$i18n.t('View logs')}</button
				>
				{#if isRunning}
					<button
						class="text-[11px] px-2 py-1 text-red-400 hover:bg-white/4 transition"
						on:click={() => dispatch('stop', { id: run.id })}>{$i18n.t('Stop')}</button
					>
				{/if}
				<button
					class="ml-auto text-[11px] px-2 py-1 text-gray-500 hover:text-gray-200 transition"
					on:click={toggle}>{$i18n.t('Hide details')}</button
				>
			</div>
		</div>
	{/if}
</div>
