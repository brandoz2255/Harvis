<script lang="ts">
	import { createEventDispatcher, getContext, onDestroy } from 'svelte';
	import RunTable from '$lib/agent-studio/RunTable.svelte';
	import { retryWorkspaceJob } from '$lib/apis/agent-runs';
	import { createWorkspaceStream } from '$lib/apis/streaming/workspace-stream';
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

	// ── Phase 5: persisted background-job fields (workspace_jobs) — all optional.
	// The record may carry command/exit_code/timeout_secs/log_tail directly; when it
	// doesn't, exit_code + log tail are ROLLED UP once from the run's stored
	// terminal_output SSE events (replay-only — finished runs end the stream at the
	// terminal event, so this is a bounded fetch, done lazily on expand). ──
	$: jobCommand = (run?.command || '').toString().trim();
	$: timeoutSecs = run?.timeout_secs != null ? Number(run.timeout_secs) : null;

	let rolledExit: number | null = null;
	let rolledTail: string[] = [];
	let _rolledFor = ''; // run id the rollup ran for (once per run)
	let _rollCtrl: AbortController | null = null;
	$: exitCode = run?.exit_code != null ? Number(run.exit_code) : rolledExit;
	$: tailLines = (() => {
		const t = run?.log_tail;
		if (Array.isArray(t)) return t.slice(-40);
		if (typeof t === 'string' && t) return t.split('\n').slice(-40);
		return rolledTail;
	})();

	$: if (
		expanded &&
		!isRunning &&
		run?.id &&
		_rolledFor !== run.id &&
		(run?.exit_code == null || run?.log_tail == null)
	) {
		_rolledFor = run.id;
		rollUpFromEvents(run.id);
	}
	async function rollUpFromEvents(runId: string) {
		if (_rollCtrl) {
			try { _rollCtrl.abort(); } catch (_) {}
		}
		const ctrl = new AbortController();
		_rollCtrl = ctrl;
		const lines: string[] = [];
		let exit: number | null = null;
		try {
			for await (const ev of createWorkspaceStream(runId, localStorage.token, ctrl.signal)) {
				if (ctrl.signal.aborted || runId !== run?.id) return;
				if (ev.type === 'terminal_output') {
					// harvis_exec emits output lines under `text`; the vibecode runner under `content`.
					const line = ev.content ?? (ev as any).text;
					if (line) lines.push(...String(line).replace(/\n$/, '').split('\n'));
					if (ev.exit_code != null) exit = Number(ev.exit_code);
				} else if (ev.type === 'tool_result') {
					// exit codes are persisted on tool_result under output.exit_code (not terminal_output).
					const ec = (ev as any).output?.exit_code ?? (ev as any).exit_code;
					if (ec != null) exit = Number(ec);
				} else {
					continue;
				}
			}
		} catch (_) {
			/* best-effort — card just omits the tail */
		}
		if (ctrl.signal.aborted || runId !== run?.id) return;
		rolledTail = lines.slice(-40);
		rolledExit = exit;
	}
	onDestroy(() => {
		if (_rollCtrl) {
			try { _rollCtrl.abort(); } catch (_) {}
		}
	});

	// A test-style job gets a pass/fail summary line (exit 0 = passed).
	$: isTestJob =
		/(^|\s|&&|;)\s*(pytest|jest|vitest|go\s+test|cargo\s+test|(npm|pnpm|yarn|bun)\s+(run\s+)?test|make\s+test|run_tests)\b/i.test(
			jobCommand
		) || run?.tool === 'run_tests';

	let showTail = false; // log tail collapsed by default
	let retrying = false;
	// harvis_jobs statuses: 'exited' (nonzero exit), 'reaped' (timed out), 'killed' (stopped) —
	// plus the run-style done/error/failed/cancelled. Retry any non-running terminal state.
	const canRetry = (s: string) =>
		['done', 'error', 'failed', 'cancelled', 'exited', 'reaped', 'killed'].includes(s);
	async function retry() {
		if (retrying || !run?.id) return;
		retrying = true;
		try {
			const res = await retryWorkspaceJob(run.id);
			if (res?.job_id) dispatch('retried', { id: run.id, job_id: res.job_id });
		} finally {
			retrying = false;
		}
	}

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
	$: elapsedMs = jobCommand && typeof run?.started_at === 'number'
		? // job records (/api/harvis/jobs) carry unix-SECOND timestamps
			((run?.finished_at ?? nowTick / 1000) - run.started_at) * 1000
		: !isRunning && run?.duration_ms != null
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
			{#if !isRunning && exitCode != null}
				<span
					class="shrink-0 text-[10px] px-1.5 py-0.5 rounded tabular-nums {exitCode === 0
						? 'text-emerald-400 bg-emerald-500/10'
						: 'text-red-400 bg-red-500/10'}">exit {exitCode}</span
				>
			{/if}
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
			{#if jobCommand}
				<!-- Persisted background-job surface: command · timeout · pass/fail -->
				<div class="flex items-center gap-1.5 min-w-0">
					<code
						class="flex-1 truncate font-mono text-[11px] text-gray-300 bg-white/4 rounded px-1.5 py-1"
						title={jobCommand}>{jobCommand}</code
					>
					{#if timeoutSecs != null}
						<span class="shrink-0 text-[10px] text-gray-500 tabular-nums"
							>{$i18n.t('timeout')} {timeoutSecs}s</span
						>
					{/if}
				</div>
			{/if}
			{#if isTestJob && !isRunning && exitCode != null}
				<div class="text-[11px] font-medium {exitCode === 0 ? 'text-emerald-400' : 'text-red-400'}">
					{exitCode === 0
						? `✓ ${$i18n.t('Tests passed')}`
						: `✗ ${$i18n.t('Tests failed')} (exit ${exitCode})`}
				</div>
			{/if}
			{#if tailLines.length}
				<div>
					<button
						class="text-[11px] text-gray-500 hover:text-gray-200 transition"
						on:click={() => (showTail = !showTail)}
						>{showTail ? $i18n.t('Hide log tail') : $i18n.t('Show log tail')} ({tailLines.length})</button
					>
					{#if showTail}
						<pre
							class="mt-1 max-h-48 overflow-auto rounded bg-black/30 px-2 py-1.5 font-mono text-[10.5px] leading-snug text-gray-400 whitespace-pre-wrap break-all">{tailLines.join(
								'\n'
							)}</pre>
					{/if}
				</div>
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
				{#if !isRunning && canRetry(status) && jobCommand}
					<button
						class="text-[11px] px-2 py-1 text-gray-300 hover:bg-white/4 transition disabled:opacity-50"
						disabled={retrying}
						on:click={retry}>{retrying ? $i18n.t('Retrying…') : $i18n.t('Retry')}</button
					>
				{/if}
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
