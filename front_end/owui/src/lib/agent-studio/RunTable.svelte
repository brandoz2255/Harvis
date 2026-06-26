<script lang="ts">
	import { getContext, onDestroy, createEventDispatcher } from 'svelte';
	import { getRunTree, type RunNode } from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	// The run whose agent tree to show. `live` ⇒ poll while it's still going (token/tool
	// counts land as each sub-agent finishes). Claude-Code "Background tasks" panel:
	// a workflow header card + a per-agent table (Agent · Tokens · Tools · Time).
	export let wsId = '';
	export let live = false;

	let run: RunNode | null = null;
	let children: RunNode[] = [];
	let timer: any = null;
	let activeId = '';

	const load = async () => {
		if (!wsId) return;
		const t = await getRunTree(wsId);
		run = t.run;
		children = t.children || [];
	};
	const schedule = () => {
		clearTimeout(timer);
		if (live && wsId) timer = setTimeout(async () => { await load(); schedule(); }, 3000);
	};
	$: if (wsId !== activeId) {
		activeId = wsId;
		load().then(schedule);
	}
	$: if (!live) clearTimeout(timer);
	onDestroy(() => clearTimeout(timer));

	const fmtTokens = (n: number | null | undefined): string => {
		const v = Number(n || 0);
		if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
		if (v >= 1_000) return (v / 1_000).toFixed(1) + 'k';
		return String(v);
	};
	const fmtDur = (ms: number | null | undefined): string => {
		const s = Math.round(Number(ms || 0) / 1000);
		if (s < 60) return s + 's';
		return Math.floor(s / 60) + 'm' + String(s % 60).padStart(2, '0') + 's';
	};
	const tokensOf = (n: RunNode | null): number =>
		n ? Number(n.prompt_tokens || 0) + Number(n.completion_tokens || 0) : 0;
	const dot = (status: string): string =>
		status === 'done'
			? 'bg-blue-500'
			: status === 'error'
				? 'bg-red-500'
				: status === 'cancelled'
					? 'bg-amber-500'
					: status === 'running'
						? 'bg-blue-500 animate-pulse'
						: 'bg-gray-300 dark:bg-gray-600';
	const labelOf = (n: RunNode): string => n.role || (n.task ? n.task.slice(0, 32) : 'agent');

	$: totalTokens = children.reduce((a, c) => a + tokensOf(c), 0) + tokensOf(run);
	$: totalTools = children.reduce((a, c) => a + Number(c.tool_calls || 0), 0) + Number(run?.tool_calls || 0);
	$: totalMs = Number(run?.duration_ms || 0) || children.reduce((a, c) => Math.max(a, Number(c.duration_ms || 0)), 0);
	$: agentCount = children.length || (run ? 1 : 0);

	// ── Phase bands = a READOUT OF REAL RUNTIME SYNCHRONIZATION, never of declared
	// structure or labels. A band boundary exists ONLY where the next agent (by start
	// time) began AFTER every agent in the current band had finished — a true barrier.
	// Overlapping agents (a parallel wave) collapse into ONE band regardless of role; a
	// run that streamed without a barrier ⇒ a single band ⇒ single-group. The author
	// cannot paint waves that didn't happen, because we measure start/finish, not labels.
	const TERMINAL = new Set(['done', 'error', 'cancelled']);
	const computeBands = (rows: RunNode[]): RunNode[][] => {
		const timed = rows.map((r) => {
			const start = r.started_at ? Date.parse(r.started_at) : NaN;
			// A still-running agent has no finish yet → treat as +∞ so NOTHING can barrier
			// after it (prevents false bands mid-run). Only completed agents bound a band.
			const finish =
				Number.isFinite(start) && r.duration_ms != null && TERMINAL.has(r.status)
					? start + Number(r.duration_ms)
					: Infinity;
			return { r, start, finish };
		});
		// Missing/unparseable start times → can't measure a barrier → honest single-group.
		if (timed.some((x) => !Number.isFinite(x.start))) return [rows];
		timed.sort((a, b) => a.start - b.start);
		const bands: RunNode[][] = [];
		let cur: typeof timed = [];
		let maxFinish = -Infinity;
		for (const x of timed) {
			if (cur.length && x.start >= maxFinish) {
				// barrier: x started only after EVERY agent in the current band finished
				bands.push(cur.map((y) => y.r));
				cur = [];
				maxFinish = -Infinity;
			}
			cur.push(x);
			maxFinish = Math.max(maxFinish, x.finish);
		}
		if (cur.length) bands.push(cur.map((y) => y.r));
		return bands;
	};
	$: bands = computeBands(children);
	$: banded = bands.length > 1;
	// Phases default OPEN — opening the Background-tasks panel shows the running agents
	// straight away (no drop-down hunting). A click collapses a band. `?? true` = open
	// unless explicitly toggled shut.
	let openBands: Record<number, boolean> = {};
	const isOpen = (i: number): boolean => openBands[i] ?? true;
	const toggleBand = (i: number) => (openBands = { ...openBands, [i]: !isOpen(i) });
</script>

{#if !run && !children.length}
	<div class="text-[11px] text-gray-400 px-1 py-2">{$i18n.t('No agents yet.')}</div>
{:else}
	<!-- workflow header card: title · agent count · time · tokens · tools -->
	<div class="rounded-lg border border-gray-100 dark:border-gray-850 px-3 py-2 mb-2">
		<div class="flex items-center gap-2">
			<span class="size-2 rounded-full shrink-0 {dot(run?.status || 'running')}"></span>
			<span class="text-xs font-medium text-gray-800 dark:text-gray-100 truncate"
				>{run?.task || $i18n.t('Run')}</span
			>
		</div>
		<div class="text-[11px] text-gray-400 mt-1">
			{agentCount === 1 ? $i18n.t('1 agent') : $i18n.t('{{n}} agents', { n: agentCount })} · {fmtDur(
				totalMs
			)} · {fmtTokens(totalTokens)}
			{$i18n.t('tokens')} · {totalTools}
			{$i18n.t('tools')}
		</div>
	</div>

	<!-- Phases = a folded stack. Each band: chevron + name + agent count + dot-progress row;
	     expand → the per-agent Tokens/Tools/Time table for that band. -->
	<div class="text-[11px]">
		{#if children.length}
			{#each banded ? bands : [children] as band, bi (bi)}
				<button
					type="button"
					class="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left hover:bg-gray-50 dark:hover:bg-gray-850/60 transition"
					on:click={() => toggleBand(bi)}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2.5"
						class="size-3 text-gray-400 transition {isOpen(bi) ? 'rotate-90' : ''}"
						><path d="M9 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round" /></svg
					>
					<span class="font-medium text-gray-700 dark:text-gray-200"
						>{banded ? $i18n.t('Phase {{n}}', { n: bi + 1 }) : $i18n.t('Agents')}</span
					>
					<span class="text-[10px] text-gray-400"
						>{band.length === 1
							? $i18n.t('1 agent')
							: $i18n.t('{{n}} agents', { n: band.length })}</span
					>
					<span class="ml-auto flex items-center gap-1">
						{#each band as c}<span class="size-1.5 rounded-full shrink-0 {dot(c.status)}"></span>{/each}
					</span>
				</button>
				{#if isOpen(bi)}
					<div class="pl-3 pb-1.5">
						<div
							class="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 px-2 pb-0.5 text-[10px] text-gray-400 uppercase tracking-wide"
						>
							<span>{$i18n.t('Agent')}</span>
							<span class="text-right">{$i18n.t('Tokens')}</span>
							<span class="text-right">{$i18n.t('Tools')}</span>
							<span class="text-right">{$i18n.t('Time')}</span>
						</div>
						{#each band as c (c.id)}
							<button
								type="button"
								title={$i18n.t('Open this agent')}
								class="w-full text-left grid grid-cols-[1fr_auto_auto_auto] gap-x-3 px-2 py-1 rounded-md hover:bg-gray-50 dark:hover:bg-gray-850/60 items-center"
								on:click={() => dispatch('viewAgent', { id: c.id })}
							>
								<span class="flex items-center gap-1.5 min-w-0">
									<span class="size-1.5 rounded-full shrink-0 {dot(c.status)}"></span>
									<span class="truncate text-gray-700 dark:text-gray-200">{labelOf(c)}</span>
									{#if c.model_name}<span class="text-gray-400 truncate hidden md:inline"
											>· {c.model_name}</span
										>{/if}
								</span>
								<span class="text-right tabular-nums text-gray-600 dark:text-gray-300"
									>{tokensOf(c) ? fmtTokens(tokensOf(c)) : '—'}</span
								>
								<span class="text-right tabular-nums text-gray-600 dark:text-gray-300">{c.tool_calls ?? 0}</span>
								<span class="text-right tabular-nums text-gray-600 dark:text-gray-300">{fmtDur(c.duration_ms)}</span>
							</button>
						{/each}
					</div>
				{/if}
			{/each}
		{:else if run}
			<!-- single (non-orchestrated) run: one row, no fold. Main-run tokens may be '—'. -->
			<div
				class="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 px-2 pt-1 pb-0.5 text-[10px] text-gray-400 uppercase tracking-wide"
			>
				<span>{$i18n.t('Agent')}</span>
				<span class="text-right">{$i18n.t('Tokens')}</span>
				<span class="text-right">{$i18n.t('Tools')}</span>
				<span class="text-right">{$i18n.t('Time')}</span>
			</div>
			<div class="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 px-2 py-1 items-center">
				<span class="flex items-center gap-1.5 min-w-0">
					<span class="size-1.5 rounded-full shrink-0 {dot(run.status)}"></span>
					<span class="truncate text-gray-700 dark:text-gray-200">{run.role || $i18n.t('Agent')}</span>
					{#if run.model_name}<span class="text-gray-400 truncate hidden md:inline">· {run.model_name}</span
						>{/if}
				</span>
				<span class="text-right tabular-nums text-gray-600 dark:text-gray-300"
					>{tokensOf(run) ? fmtTokens(tokensOf(run)) : '—'}</span
				>
				<span class="text-right tabular-nums text-gray-600 dark:text-gray-300">{run.tool_calls ?? 0}</span>
				<span class="text-right tabular-nums text-gray-600 dark:text-gray-300">{fmtDur(run.duration_ms)}</span>
			</div>
		{/if}
	</div>
{/if}
