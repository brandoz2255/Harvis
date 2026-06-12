<script lang="ts">
	import { getContext, afterUpdate } from 'svelte';
	import { phrase } from './humanizeTool';
	import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';

	const i18n: any = getContext('i18n');

	export let events: WorkspaceEvent[] = [];
	export let running = false;

	type Line = { kind: string; text: string; ok?: boolean; status?: 'running' | 'done' };

	// Fold events into readable lines; pair each tool_call with its next tool_result.
	$: lines = foldLines(events);

	function foldLines(evts: WorkspaceEvent[]): Line[] {
		const out: Line[] = [];
		let lastTool = -1; // index in `out` of the tool line awaiting its result
		for (const e of evts) {
			switch (e.type) {
				case 'agent_start':
					out.push({
						kind: 'agent',
						text: e.agent_label ? String(e.agent_label) : $i18n.t('Planning the task…')
					});
					lastTool = -1;
					break;
				case 'log':
					if (e.message) out.push({ kind: 'log', text: String(e.message) });
					break;
				case 'tool_call':
					out.push({ kind: 'tool', text: phrase(e.tool as string), status: 'running' });
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
		<div class="text-gray-400 py-2">{$i18n.t('Connecting…')}</div>
	{/if}
	{#each lines as l}
		{#if l.kind === 'tool'}
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
		{:else}
			<div class="text-gray-500 dark:text-gray-400 whitespace-pre-wrap break-words">{l.text}</div>
		{/if}
	{/each}
</div>
