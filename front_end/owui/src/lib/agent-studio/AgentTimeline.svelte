<script lang="ts">
	import { getContext, tick } from 'svelte';
	import { toolLabel } from './workflow/humanizeTool';
	import Collapsible from '$lib/components/common/Collapsible.svelte';
	import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';

	const i18n: any = getContext('i18n');

	// The chat-like timeline for ONE sub-agent: its messages (each `token` event is a
	// full step message, NOT a delta — see orchestration/runner.py), interleaved with its
	// tool calls (+ results), logs, and the terminal result/error/cancel. `events` is
	// already this agent's slice. Degrades gracefully: a terse agent that only emits tool
	// calls just shows tool rows + result.
	export let events: WorkspaceEvent[] = [];
	export let running = false;

	type Block =
		| { kind: 'msg'; text: string }
		| { kind: 'tool'; label: string; status: 'running' | 'done' | 'error'; output?: string }
		| { kind: 'log'; text: string }
		| { kind: 'result'; text: string }
		| { kind: 'error'; text: string }
		| { kind: 'cancelled' }
		| { kind: 'term'; text: string; stream: 'stdout' | 'stderr' }
		| { kind: 'decision'; policy: 'allow' | 'deny' | 'gate'; tool: string; reason: string }
		| { kind: 'artifact'; label: string; path: string }
		| {
				kind: 'search';
				query: string;
				provider: string;
				count: number;
				results: { title: string; domain: string; url: string }[];
		  };

	const build = (evs: WorkspaceEvent[]): Block[] => {
		const out: Block[] = [];
		let lastTool = -1;
		for (const e of evs) {
			switch (e.type) {
				case 'token':
					if (e.content && String(e.content).trim())
						out.push({ kind: 'msg', text: String(e.content) });
					break;
				case 'tool_call':
					out.push({ kind: 'tool', label: toolLabel(e.tool), status: 'running' });
					lastTool = out.length - 1;
					break;
				case 'tool_result':
					if (lastTool >= 0 && out[lastTool]?.kind === 'tool') {
						const t = out[lastTool] as Extract<Block, { kind: 'tool' }>;
						t.status = e.success === false ? 'error' : 'done';
						const o = String(e.output ?? '').trim();
						if (o) t.output = o.slice(0, 400);
					}
					break;
				case 'log':
					if (e.message) out.push({ kind: 'log', text: String(e.message) });
					break;
				case 'terminal_output':
					if (e.content && String(e.content).trim())
						out.push({
							kind: 'term',
							text: String(e.content).slice(0, 2000),
							stream: e.stream === 'stderr' ? 'stderr' : 'stdout'
						});
					break;
				case 'decision':
					out.push({
						kind: 'decision',
						policy: e.policy === 'allow' || e.policy === 'deny' ? e.policy : 'gate',
						tool: String(e.tool ?? ''),
						reason: String(e.reason ?? '')
					});
					break;
				case 'artifact':
					out.push({
						kind: 'artifact',
						label: String(e.label || e.path || 'Artifact'),
						path: String(e.path ?? '')
					});
					break;
				case 'search_trace': {
					const results = (Array.isArray(e.results) ? e.results : []).map((r) => ({
						title: String(r?.title || r?.url || ''),
						domain: String(r?.domain ?? ''),
						url: String(r?.url ?? '')
					}));
					out.push({
						kind: 'search',
						query: String(e.query ?? ''),
						provider: String(e.provider ?? ''),
						count: Number(e.result_count ?? results.length) || results.length,
						results
					});
					break;
				}
				// 'final_message' is a protocol event for non-UI consumers (Discord/CLI) —
				// the 'done' case below already renders the answer, so we don't add a row.
				case 'done':
					if (e.summary) out.push({ kind: 'result', text: String(e.summary) });
					break;
				case 'error':
					out.push({ kind: 'error', text: String(e.message || e.summary || 'Error') });
					break;
				case 'cancelled':
					out.push({ kind: 'cancelled' });
					break;
				// agent_start / plan / approval_* → not shown (the session header + task bubble cover them).
			}
		}
		return out;
	};

	$: blocks = build(events);

	// Auto-scroll to the latest while the agent is working.
	let scroller: HTMLDivElement;
	$: if (blocks.length && running && scroller) {
		tick().then(() => scroller && (scroller.scrollTop = scroller.scrollHeight));
	}
</script>

<div bind:this={scroller} class="space-y-2.5 text-sm overflow-y-auto">
	{#if !blocks.length}
		<div class="text-xs text-gray-500 py-2">
			{running ? $i18n.t('Working…') : $i18n.t('No activity recorded for this agent.')}
		</div>
	{/if}
	{#each blocks as b, i (i)}
		{#if b.kind === 'msg'}
			<!-- the agent "talking" -->
			<div class="text-gray-200 leading-relaxed whitespace-pre-wrap break-words">{b.text}</div>
		{:else if b.kind === 'tool'}
			<div class="flex items-start gap-2 text-xs">
				{#if b.status === 'running'}
					<span class="mt-0.5 size-3 rounded-full border-2 border-blue-500/40 border-t-blue-500 animate-spin shrink-0"></span>
				{:else if b.status === 'error'}
					<span class="mt-0.5 text-red-400 shrink-0">✗</span>
				{:else}
					<span class="mt-0.5 text-emerald-400 shrink-0">✓</span>
				{/if}
				<div class="min-w-0 flex-1">
					<span class="text-gray-400">{b.label}</span>
					{#if b.output}
						<div class="mt-0.5 font-mono text-[11px] text-gray-500 whitespace-pre-wrap break-words line-clamp-4">{b.output}</div>
					{/if}
				</div>
			</div>
		{:else if b.kind === 'log'}
			<div class="text-xs text-gray-500 whitespace-pre-wrap break-words">{b.text}</div>
		{:else if b.kind === 'result'}
			<div class="flex items-start gap-2 border-l-2 border-emerald-500/40 pl-2.5 text-gray-200 leading-relaxed whitespace-pre-wrap break-words">
				<span class="text-emerald-400 shrink-0">✓</span><span>{b.text}</span>
			</div>
		{:else if b.kind === 'error'}
			<div class="text-red-400 leading-relaxed whitespace-pre-wrap break-words">{b.text}</div>
		{:else if b.kind === 'cancelled'}
			<div class="text-amber-400 text-xs">{$i18n.t('Cancelled.')}</div>
		{:else if b.kind === 'term'}
			<!-- sandbox/terminal output row -->
			<div
				class="rounded-md bg-black/30 px-2 py-1.5 font-mono text-[11px] whitespace-pre-wrap break-words {b.stream ===
				'stderr'
					? 'text-red-300'
					: 'text-gray-300'}"
			>{b.text}</div>
		{:else if b.kind === 'decision'}
			<div class="flex items-start gap-2 text-xs">
				<span
					class="mt-0.5 shrink-0 {b.policy === 'allow'
						? 'text-emerald-400'
						: b.policy === 'deny'
							? 'text-red-400'
							: 'text-amber-400'}">⛨</span
				>
				<div class="min-w-0 flex-1 text-gray-400">
					<span class="uppercase tracking-wide">{b.policy}</span>
					{#if b.tool}<span> · {toolLabel(b.tool)}</span>{/if}
					{#if b.reason}
						<div class="mt-0.5 text-[11px] text-gray-500 break-words line-clamp-2">{b.reason}</div>
					{/if}
				</div>
			</div>
		{:else if b.kind === 'artifact'}
			<div class="inline-flex max-w-full items-center gap-1.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-xs text-indigo-300">
				<span class="shrink-0">◆</span>
				<span class="truncate" title={b.path}>{b.label}</span>
			</div>
		{:else if b.kind === 'search'}
			<!-- web-search trace: collapsible "Searched: …" row with the hit list -->
			<Collapsible
				buttonClassName="w-full text-gray-400 hover:text-gray-300 transition"
				chevron
			>
				<div class="flex min-w-0 flex-1 items-center gap-2 text-xs">
					<span class="shrink-0">⌕</span>
					<span class="truncate" title={b.query}>{$i18n.t('Searched')}: {b.query}</span>
					<span
						class="shrink-0 rounded-full bg-gray-500/20 px-1.5 py-0.5 text-[10px] text-gray-400"
						title={b.provider}>{b.count}</span
					>
				</div>
				<div slot="content" class="mt-1 space-y-1 pl-5">
					{#each b.results as r, ri (ri)}
						<div class="min-w-0 text-[11px]">
							<a
								href={r.url}
								target="_blank"
								rel="noopener noreferrer"
								class="text-blue-400 hover:underline break-all">{r.title || r.url}</a
							>
							{#if r.domain}<span class="text-gray-500"> · {r.domain}</span>{/if}
						</div>
					{/each}
				</div>
			</Collapsible>
		{/if}
	{/each}
</div>
