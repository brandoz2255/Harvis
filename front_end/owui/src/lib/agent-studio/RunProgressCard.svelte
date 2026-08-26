<script lang="ts">
	// A digestible, live progress timeline for a workspace/artifact run.
	//
	// Pure over the event array (reload/replay reconstructs the same final state).
	// Compact by default: one summary line + a 9-segment progress bar; click to
	// expand the full stage checklist. Surfaces a "Retry stream" affordance when the
	// connection goes quiet, and an "Open output" link when artifacts are ready — so
	// the user is never stuck on a frozen-looking card.
	import { getContext } from 'svelte';
	import { computeStages, activeStage, type RunEventLike, type StageStatus } from '$lib/agent-studio/runStages';

	const i18n: any = getContext('i18n');
	const t = (s: string) => (i18n && typeof i18n.t === 'function' ? i18n.t(s) : s);

	export let events: RunEventLike[] = [];
	export let phase = 'connecting';
	export let engineLabel = '';
	export let modelLabel = ''; // the model doing the work — woven into the stage text
	export let elapsedMs = 0; // run wall-clock — drives the cold-load hint
	export let errorMessage = '';
	export let artifactCount: number | null = null;
	export let stalled = false;
	// Compact (chat card) starts collapsed + expandable; full (run page) is always open.
	export let compact = true;
	// Fallback affordances (optional): wired by the host.
	export let onRetry: (() => void) | null = null;
	export let onOpenArtifacts: (() => void) | null = null;

	let expanded = false;
	$: if (!compact) expanded = true;

	$: stages = computeStages(events || [], { phase, engineLabel, modelLabel, errorMessage, artifactCount, elapsedMs });
	// Same cloud test as runStages: a provider-prefixed model id ("anthropic/…") or a
	// cloud engine label. A stalled Opus/Kimi run must not blame "local models".
	$: cloudRun =
		/\//.test((modelLabel || '').trim()) || /^(claude|kimi|codex|gpt|openai)/i.test((engineLabel || '').trim());
	$: cur = activeStage(stages);
	$: last = stages[stages.length - 1];
	$: terminal = phase === 'done' || phase === 'error' || phase === 'cancelled';
	$: doneCount = stages.filter((s) => s.status === 'done').length;
	// Append "…" to an active headline only when its label doesn't already end with
	// punctuation (tool phrases like "Writing a file…" already carry one).
	$: _ellipsis = !terminal && cur.status === 'active' && !/[….!?:]$/.test(cur.label);
	$: headline = terminal
		? `${last.label}${last.detail ? ' · ' + last.detail : ''}`
		: `${cur.label}${_ellipsis ? '…' : ''}${cur.detail ? ' · ' + cur.detail : ''}`;

	const DOT: Record<StageStatus, string> = {
		done: 'bg-emerald-500',
		active: 'bg-blue-500 animate-pulse',
		pending: 'bg-gray-200 dark:bg-gray-800',
		error: 'bg-red-500',
		skipped: 'bg-gray-200/70 dark:bg-gray-800/60'
	};
	const TEXT: Record<StageStatus, string> = {
		done: 'text-emerald-600 dark:text-emerald-400',
		active: 'text-blue-600 dark:text-blue-400',
		pending: 'text-gray-400 dark:text-gray-500',
		error: 'text-red-600 dark:text-red-400',
		skipped: 'text-gray-400 dark:text-gray-600'
	};
	const GLYPH: Record<StageStatus, string> = { done: '✓', active: '', pending: '', error: '✕', skipped: '–' };
</script>

<div class="rounded-lg border border-gray-100 dark:border-gray-850 bg-gray-50/70 dark:bg-gray-900/40 px-3 py-2 text-xs">
	<!-- Summary line — always visible -->
	<button
		type="button"
		class="w-full flex items-center gap-2 text-left {compact ? 'cursor-pointer' : 'cursor-default'}"
		on:click={() => compact && (expanded = !expanded)}
	>
		<span class="size-2 rounded-full shrink-0 {DOT[cur.status]}"></span>
		<span
			class="font-medium truncate {terminal ? TEXT[last.status] : 'text-gray-700 dark:text-gray-200'}"
			title={headline}>{headline}</span
		>
		{#if !terminal}
			<span class="ml-auto text-[10px] tabular-nums text-gray-400 dark:text-gray-500 shrink-0">{doneCount}/{stages.length}</span>
		{/if}
		{#if compact}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2.5"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="size-3 text-gray-400 transition-transform shrink-0 {expanded ? 'rotate-180' : ''} {terminal ? 'ml-auto' : ''}"
				><path d="m6 9 6 6 6-6" /></svg
			>
		{/if}
	</button>

	{#if !expanded}
		<!-- Collapsed: a 9-segment progress bar (each stage = one segment) -->
		<div class="mt-1.5 flex items-center gap-1">
			{#each stages as s}
				<span class="h-1 flex-1 rounded-full {DOT[s.status]}" title="{s.label}{s.detail ? ' · ' + s.detail : ''}"></span>
			{/each}
		</div>
	{:else}
		<!-- Expanded: the full stage checklist -->
		<ul class="mt-2 space-y-1">
			{#each stages as s}
				<li class="flex items-start gap-2">
					{#if s.status === 'active'}
						<span class="mt-px size-3.5 shrink-0 rounded-full border-2 border-blue-500/40 border-t-blue-500 animate-spin"></span>
					{:else}
						<span
							class="mt-px size-3.5 shrink-0 flex items-center justify-center rounded-full text-[9px] leading-none {s.status ===
							'done'
								? 'bg-emerald-500 text-white'
								: s.status === 'error'
									? 'bg-red-500 text-white'
									: s.status === 'skipped'
										? 'bg-gray-200 dark:bg-gray-800 text-gray-400 dark:text-gray-600'
										: 'border border-gray-300 dark:border-gray-700 text-transparent'}">{GLYPH[s.status]}</span
						>
					{/if}
					<span class="leading-relaxed {TEXT[s.status]} {s.status === 'skipped' ? 'line-through opacity-70' : ''}">
						{s.label}{#if s.detail}<span class="text-gray-400 dark:text-gray-500"> · {s.detail}</span>{/if}
					</span>
				</li>
			{/each}
		</ul>
	{/if}

	<!-- Stalled affordance: the stream went quiet but the run is still going. Reassure +
	     offer a manual reconnect that replays from the persisted run state. -->
	{#if stalled && !terminal}
		<div class="mt-2 flex items-center gap-2 text-amber-600 dark:text-amber-400">
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-3.5 shrink-0"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
			<span
				>{cloudRun
					? t('Still working — the model is thinking; long tasks can take a while.')
					: t('Still working — this can take a minute on local models.')}</span
			>
			{#if onRetry}
				<button type="button" class="underline hover:no-underline" on:click={onRetry}>{t('Reconnect')}</button>
			{/if}
		</div>
	{/if}

	<!-- Output-ready affordance (fallback when auto-pop didn't fire) -->
	{#if phase === 'done' && (artifactCount ?? 0) > 0 && onOpenArtifacts}
		<div class="mt-2">
			<button type="button" class="text-blue-600 dark:text-blue-400 font-medium hover:underline" on:click={onOpenArtifacts}
				>{t('Open output')} →</button
			>
		</div>
	{/if}
</div>
