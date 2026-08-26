<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';

	import type { TerminalRun } from '$lib/agent-studio/runEventProjection';
	import Clipboard from '$lib/components/icons/Clipboard.svelte';
	import Terminal from '$lib/components/icons/Terminal.svelte';
	import { copyToClipboard } from '$lib/utils';

	import InlineToolCardShell from './InlineToolCardShell.svelte';
	import { parseAnsiSegments, stripTerminalControls } from './terminalText';

	export let run: TerminalRun;
	export let autoCompact = false;

	const STATUS = {
		queued: {
			label: 'Queued',
			dot: 'bg-gray-400',
			text: 'text-gray-500 dark:text-gray-400'
		},
		running: {
			label: 'Running',
			dot: 'bg-blue-500',
			text: 'text-blue-600 dark:text-blue-400'
		},
		succeeded: {
			label: 'Succeeded',
			dot: 'bg-emerald-500',
			text: 'text-emerald-600 dark:text-emerald-400'
		},
		failed: {
			label: 'Failed',
			dot: 'bg-red-500',
			text: 'text-red-600 dark:text-red-400'
		},
		cancelled: {
			label: 'Cancelled',
			dot: 'bg-amber-500',
			text: 'text-amber-600 dark:text-amber-400'
		}
	};

	let expanded = run.status === 'queued' || run.status === 'running';
	let userControlled = false;
	let readingOutput = false;
	let followOutput = true;
	let terminalElement: HTMLDivElement | null = null;
	let now = Date.now();
	let observedStartedAt: number | null = null;
	let observedFinishedAt: number | null = null;
	let sawActive = false;
	let compacted = false;
	let timer: ReturnType<typeof setInterval> | null = null;
	let copied = false;
	let copyReset: ReturnType<typeof setTimeout> | null = null;

	$: active = run.status === 'queued' || run.status === 'running';
	$: statusMeta = STATUS[run.status];
	$: if (active) {
		expanded = true;
		sawActive = true;
		if (observedStartedAt === null) observedStartedAt = Date.now();
	}
	$: if (!active && sawActive && observedFinishedAt === null) observedFinishedAt = Date.now();
	$: if (!autoCompact) compacted = false;
	$: if (autoCompact && !active && !compacted && !userControlled && !readingOutput) {
		expanded = false;
		compacted = true;
	}
	$: measuredDuration =
		run.durationMs ??
		(observedStartedAt !== null
			? Math.max(0, (active ? now : (observedFinishedAt ?? now)) - observedStartedAt)
			: null);
	$: elapsedLabel = measuredDuration === null ? '' : formatDuration(measuredDuration);
	$: outputText = run.chunks.map((chunk) => stripTerminalControls(chunk.text)).join('');
	$: outputSize = run.chunks.reduce((total, chunk) => total + chunk.text.length, 0);
	$: followLatest(outputSize, expanded, followOutput);
	$: completionLabel = completionText(run, elapsedLabel, outputText);

	function formatDuration(ms: number): string {
		if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
		if (ms < 10000) return `${(ms / 1000).toFixed(1)}s`;
		return `${Math.round(ms / 1000)}s`;
	}

	function completionText(value: TerminalRun, elapsed: string, output: string): string {
		if (value.status === 'queued') return 'Waiting to run';
		if (value.status === 'running') return elapsed ? `Running for ${elapsed}` : 'Running command';
		if (value.status === 'cancelled') return elapsed ? `Cancelled after ${elapsed}` : 'Cancelled';
		const prefix = value.status === 'failed' ? 'Failed' : 'Completed';
		const time = elapsed ? ` in ${elapsed}` : '';
		const exit = value.exitCode !== null ? ` · exit ${value.exitCode}` : '';
		if (value.status === 'succeeded' && !output) {
			return `Command completed with no output${time}${exit}`;
		}
		return `${prefix}${time}${exit}`;
	}

	async function followLatest(_size: number, isExpanded: boolean, shouldFollow: boolean) {
		if (!terminalElement || !isExpanded || !shouldFollow) return;
		await tick();
		if (terminalElement) terminalElement.scrollTop = terminalElement.scrollHeight;
	}

	function handleTerminalScroll() {
		if (!terminalElement) return;
		const atBottom =
			terminalElement.scrollHeight - terminalElement.scrollTop <=
			terminalElement.clientHeight + 24;
		followOutput = atBottom;
		readingOutput = !atBottom;
	}

	function resumeFollow() {
		followOutput = true;
		readingOutput = false;
		if (terminalElement) terminalElement.scrollTop = terminalElement.scrollHeight;
	}

	function handleToggle(next: boolean) {
		userControlled = true;
		// Active commands remain visible; completed commands are user-controlled.
		expanded = active ? true : next;
	}

	async function copyOutput() {
		const ok = await copyToClipboard(outputText);
		if (!ok) return;
		copied = true;
		if (copyReset) clearTimeout(copyReset);
		copyReset = setTimeout(() => (copied = false), 1600);
	}

	onMount(() => {
		timer = setInterval(() => {
			if (active) now = Date.now();
		}, 250);
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
		if (copyReset) clearTimeout(copyReset);
	});
</script>

<InlineToolCardShell
	status={run.status}
	statusLabel={`${statusMeta.label}: ${run.command || 'command'}`}
	{expanded}
	on:toggle={(event) => handleToggle(event.detail.expanded)}
	className="my-2"
>
	<div
		slot="leading"
		class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-300"
	>
		<Terminal className="size-4" strokeWidth="1.8" />
	</div>

	<div slot="header" class="min-w-0">
		<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 sm:flex-nowrap">
			<span class="min-w-0 flex-1 break-all font-mono text-xs font-medium text-gray-800 line-clamp-2 dark:text-gray-100 sm:truncate">
				{run.command || 'Terminal command'}
			</span>
			<span class="inline-flex shrink-0 items-center gap-1.5 text-[11px] font-medium {statusMeta.text}">
				<span
					class="size-1.5 rounded-full {statusMeta.dot} {active
						? 'animate-pulse motion-reduce:animate-none'
						: ''}"
				></span>
				{statusMeta.label}
			</span>
			{#if elapsedLabel}
				<span class="shrink-0 text-[11px] tabular-nums text-gray-400">{elapsedLabel}</span>
			{/if}
			{#if run.exitCode !== null}
				<span class="shrink-0 text-[11px] tabular-nums text-gray-500 dark:text-gray-400">
					exit {run.exitCode}
				</span>
			{/if}
		</div>
		{#if run.cwd}
			<div class="mt-0.5 hidden truncate font-mono text-[10px] text-gray-400 sm:block" title={run.cwd}>
				{run.cwd}
			</div>
		{/if}
	</div>

	<button
		slot="actions"
		type="button"
		class="flex size-11 shrink-0 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-40 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-gray-100 sm:size-9"
		aria-label={copied ? 'Output copied' : 'Copy command output'}
		title={copied ? 'Copied' : 'Copy output'}
		disabled={!outputText}
		on:click={copyOutput}
	>
		{#if copied}
			<span class="text-xs font-semibold text-emerald-500" aria-hidden="true">✓</span>
		{:else}
			<Clipboard className="size-4" />
		{/if}
	</button>

	<div class="dark-surface min-w-0 bg-[#0b0d10]">
		<div
			bind:this={terminalElement}
			class="terminal-output relative max-h-[260px] min-h-[96px] overflow-y-auto overflow-x-hidden px-3.5 py-3 font-mono text-[12px] leading-5 text-gray-200 selection:bg-blue-500/35 sm:max-h-[380px] sm:px-4 sm:text-[13px]"
			on:scroll={handleTerminalScroll}
			tabindex="0"
			aria-label={`Terminal output for ${run.command || 'command'}`}
		>
			<div class="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
				<span class="select-none text-blue-300">$ </span><span class="text-gray-100">{run.command || 'command'}</span>
			</div>
			{#if run.chunks.length}
				<div class="mt-2 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
					{#each run.chunks as chunk, index (`${run.id}:${index}`)}
						{#each parseAnsiSegments(chunk.text, chunk.stream === 'stderr' ? 'text-red-300' : 'text-gray-200') as segment, segmentIndex (`${run.id}:${index}:${segmentIndex}`)}
							<span class={segment.className}>{segment.text}</span>
						{/each}
					{/each}
				</div>
			{:else if active}
				<div class="mt-2 text-gray-500">Running…</div>
			{:else if run.status === 'succeeded'}
				<div class="mt-2 italic text-gray-500">Command completed with no output.</div>
			{:else}
				<div class="mt-2 italic text-gray-500">No command output was received.</div>
			{/if}

			{#if !followOutput && active}
				<div class="sticky bottom-2 mt-2 flex justify-center">
					<button
						type="button"
						class="rounded-full border border-white/10 bg-[#181b21] px-3 py-1.5 text-[11px] font-sans text-gray-200 shadow-lg hover:bg-[#20242c] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
						on:click={resumeFollow}
					>
						Resume follow
					</button>
				</div>
			{/if}
		</div>
	</div>

	<div
		class="dark-surface flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 border-t border-gray-800 bg-[#0f1115] px-3.5 py-2 text-[11px] text-gray-400"
	>
		<span class="font-medium {statusMeta.text}">{completionLabel}</span>
		{#if run.truncated}
			<span>· Output was truncated by the execution service</span>
		{/if}
	</div>
</InlineToolCardShell>
