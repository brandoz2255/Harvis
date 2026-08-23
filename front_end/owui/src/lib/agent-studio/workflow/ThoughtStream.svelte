<script lang="ts">
	import { getContext, afterUpdate, onDestroy } from 'svelte';
	import { stepLabel } from './humanizeTool';
	import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';

	const i18n: any = getContext('i18n');

	export let events: WorkspaceEvent[] = [];
	export let running = false;
	/** Optional: reconnect when Connecting… stalls with no events. */
	export let onRetry: (() => void) | undefined = undefined;

	const STALL_MS = 20_000;
	let stalled = false;
	let stallTimer: ReturnType<typeof setTimeout> | null = null;

	$: {
		if (stallTimer) {
			clearTimeout(stallTimer);
			stallTimer = null;
		}
		stalled = false;
		if (running && events.length === 0 && onRetry) {
			stallTimer = setTimeout(() => {
				stalled = true;
			}, STALL_MS);
		}
	}

	onDestroy(() => {
		if (stallTimer) clearTimeout(stallTimer);
	});

	type Line = {
		kind: string;
		text: string;
		ok?: boolean;
		status?: 'running' | 'done';
		role?: string;
		label?: string;
		prUrl?: string;
		verdict?: 'approved' | 'changes' | 'comment';
		streaming?: boolean;
	};

	const _VERDICT_RE = /\n*VERDICT\s*[:\-]\s*(APPROVED|CHANGES[_ ]REQUESTED|COMMENT)\s*\.?\s*$/i;

	$: lines = foldLines(events);

	function foldLines(evts: WorkspaceEvent[]): Line[] {
		const out: Line[] = [];
		let lastTool = -1;
		for (const e of evts) {
			switch (e.type) {
				case 'agent_start':
					out.push({
						kind: 'agent',
						text: e.agent_label ? String(e.agent_label) : $i18n.t('Planning the task…')
					});
					lastTool = -1;
					break;
				case 'token': {
					const c = e.content ?? (e as any).delta ?? '';
					if (!c) break;
					const last = out[out.length - 1];
					if (last && last.kind === 'think') {
						last.text += String(c);
					} else {
						out.push({ kind: 'think', text: String(c), streaming: true });
					}
					break;
				}
				case 'log':
					if (e.message) out.push({ kind: 'log', text: String(e.message) });
					break;
				case 'agent_message': {
					const raw = String(e.content ?? '');
					if (raw.trim()) {
						const vm = raw.match(_VERDICT_RE);
						const _vt = vm ? vm[1].toUpperCase() : '';
						const verdict: 'approved' | 'changes' | 'comment' | undefined = !vm
							? undefined
							: _vt.startsWith('APPROVED')
								? 'approved'
								: _vt.startsWith('COMMENT')
									? 'comment'
									: 'changes';
						out.push({
							kind: 'agent_msg',
							text: verdict ? raw.replace(_VERDICT_RE, '').trim() : raw,
							role:
								e.role === 'reviewer'
									? 'reviewer'
									: e.role === 'coder'
										? 'coder'
										: String((e as any).role ?? 'agent'),
							label: String(e.label || e.agent_label || (e as any).role || 'Agent'),
							verdict,
							...(typeof (e as any).pr_url === 'string' && (e as any).pr_url
								? { prUrl: (e as any).pr_url }
								: {})
						});
					}
					break;
				}
				case 'tool_call':
					out.push({
						kind: 'tool',
						text: stepLabel(e.tool as string, (e as any).args),
						status: 'running'
					});
					lastTool = out.length - 1;
					break;
				case 'tool_result':
					if (lastTool >= 0 && out[lastTool]) {
						out[lastTool].status = 'done';
						out[lastTool].ok = e.success !== false;
						lastTool = -1;
					}
					break;
				case 'done':
					out.push({ kind: 'done', text: (e.summary as string) || $i18n.t('Done.') });
					break;
				case 'error':
					out.push({ kind: 'error', text: (e.message as string) || $i18n.t('Error'), ok: false });
					break;
				case 'cancelled':
					out.push({ kind: 'cancelled', text: $i18n.t('Cancelled.') });
					break;
			}
		}
		return out;
	}

	let scroller: HTMLDivElement;
	afterUpdate(() => {
		if (running && scroller) scroller.scrollTop = scroller.scrollHeight;
	});
</script>

<div bind:this={scroller} class="h-full overflow-y-auto text-xs space-y-1.5 pr-1">
	{#if lines.length === 0}
		<div class="text-gray-400 py-2 flex items-center gap-2 flex-wrap">
			<span>{stalled ? $i18n.t('Still connecting…') : $i18n.t('Connecting…')}</span>
			{#if stalled && onRetry}
				<button
					type="button"
					class="underline text-blue-500 hover:no-underline"
					on:click={() => onRetry?.()}>{$i18n.t('Retry')}</button
				>
			{/if}
		</div>
	{/if}
	{#each lines as l, i}
		{#if l.kind === 'think'}
			<div
				class="rounded-lg border border-gray-200/80 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.03] px-2.5 py-1.5 text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-words leading-relaxed"
			>
				{l.text}{#if running && l.streaming}<span class="opacity-40">▍</span>{/if}
			</div>
		{:else if l.kind === 'tool'}
			<div class="flex items-center gap-1.5">
				{#if l.status === 'running'}
					<span class="text-blue-500 animate-pulse shrink-0">●</span>
				{:else if l.ok}
					<span class="text-blue-500 shrink-0">✓</span>
				{:else}
					<span class="text-red-500 shrink-0">✗</span>
				{/if}
				<span class="text-gray-600 dark:text-gray-300 truncate">{l.text}</span>
			</div>
		{:else if l.kind === 'agent'}
			<div class="text-gray-500 font-medium">{l.text}</div>
		{:else if l.kind === 'done'}
			<div
				class="mt-1 rounded-lg bg-blue-50 dark:bg-blue-950/40 text-blue-800 dark:text-blue-200 px-2 py-1.5 whitespace-pre-wrap break-words"
			>
				{l.text}
			</div>
		{:else if l.kind === 'error'}
			<div class="text-red-500 whitespace-pre-wrap break-words">{l.text}</div>
		{:else if l.kind === 'cancelled'}
			<div class="text-gray-500">{l.text}</div>
		{:else if l.kind === 'agent_msg'}
			<div
				class="rounded-xl border px-3 py-2 break-words {l.role === 'reviewer'
					? 'border-amber-500/25 bg-amber-500/[0.06]'
					: l.role === 'coder'
						? 'border-sky-500/20 bg-sky-500/[0.05]'
						: 'border-white/10 bg-white/5'}"
			>
				<div class="flex items-center gap-1.5 mb-1.5">
					<span
						class="shrink-0 {l.role === 'reviewer'
							? 'text-amber-500'
							: l.role === 'coder'
								? 'text-sky-400'
								: 'text-gray-400'}"
					>
						{#if l.role === 'reviewer'}
							<svg viewBox="0 0 20 20" fill="currentColor" class="size-3.5"
								><path
									fill-rule="evenodd"
									d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z"
									clip-rule="evenodd"
								/></svg
							>
						{:else if l.role === 'coder'}
							<svg viewBox="0 0 20 20" fill="currentColor" class="size-3.5"
								><path
									fill-rule="evenodd"
									d="M6.28 5.22a.75.75 0 0 1 0 1.06L2.56 10l3.72 3.72a.75.75 0 0 1-1.06 1.06L.97 10.53a.75.75 0 0 1 0-1.06l4.25-4.25a.75.75 0 0 1 1.06 0Zm7.44 0a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 1 1-1.06-1.06L17.44 10l-3.72-3.72a.75.75 0 0 1 0-1.06ZM11.377 2.011a.75.75 0 0 1 .612.867l-2 11.5a.75.75 0 0 1-1.478-.257l2-11.5a.75.75 0 0 1 .867-.61Z"
									clip-rule="evenodd"
								/></svg
							>
						{/if}
					</span>
					<span
						class="text-[10px] uppercase tracking-wider font-semibold {l.role === 'reviewer'
							? 'text-amber-500/90'
							: l.role === 'coder'
								? 'text-sky-400/90'
								: 'text-gray-400'}">{l.label}</span
					>
					{#if l.verdict}
						<span
							class="text-[9px] uppercase tracking-wide font-bold px-1.5 py-0.5 rounded-md {l.verdict ===
							'approved'
								? 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400'
								: l.verdict === 'comment'
									? 'bg-sky-500/15 text-sky-600 dark:text-sky-400'
									: 'bg-amber-500/15 text-amber-600 dark:text-amber-400'}"
							>{l.verdict === 'approved'
								? '✓ ' + $i18n.t('Approved')
								: l.verdict === 'comment'
									? '💬 ' + $i18n.t('Comment')
									: '✎ ' + $i18n.t('Changes requested')}</span
						>
					{/if}
					{#if l.prUrl}
						<a
							href={l.prUrl}
							target="_blank"
							rel="noopener"
							class="text-[10px] text-blue-500 hover:underline ml-auto">{$i18n.t('on GitHub PR')} ↗</a
						>
					{/if}
				</div>
				<div class="markdown-prose markdown-prose-sm text-xs leading-relaxed text-gray-600 dark:text-gray-300">
					<Markdown id={`am-${i}`} content={l.text} />
				</div>
			</div>
		{:else}
			<div class="text-gray-500 dark:text-gray-400 whitespace-pre-wrap break-words">{l.text}</div>
		{/if}
	{/each}
</div>
