<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { toolLabel } from './humanizeTool';
	import type { WfNodeData } from './eventsToGraph';

	const i18n: any = getContext('i18n');

	// xyflow passes the node's `data` (our WfNodeData) through.
	export let data: any;
	$: d = data as any;

	// Global Map run-node helpers.
	const runDot = (s?: string) =>
		s === 'done'
			? 'bg-blue-500'
			: s === 'error'
				? 'bg-red-500'
				: s === 'cancelled'
					? 'bg-amber-500'
					: 'bg-blue-500';
	const fmtDur = (ms?: number) =>
		ms ? (ms < 60000 ? `${Math.round(ms / 1000)}s` : `${Math.round(ms / 60000)}m`) : '';
</script>

<div
	class="rounded-xl shadow-md border bg-white dark:bg-gray-900 border-gray-100 dark:border-gray-800 w-56 px-3 py-2 text-xs"
>
	{#if d.kind === 'agent'}
		<div class="flex items-center gap-1.5">
			<span class="size-2 rounded-full shrink-0 {d.isRoot ? 'bg-blue-500' : 'bg-indigo-400'}"></span>
			<span class="font-medium text-gray-800 dark:text-gray-100 truncate">{d.label}</span>
		</div>
		<div class="mt-1 flex items-center gap-1 text-[10px] text-gray-400">
			<span>{d.isRoot ? $i18n.t('root') : $i18n.t('sub-agent')}</span>
			{#if d.model}<span class="truncate">· {d.model}</span>{/if}
		</div>
	{:else if d.kind === 'tool'}
		<Tooltip content={d.output || ''} class="w-full">
			<div class="flex items-center gap-1.5">
				{#if d.status === 'running'}
					<span class="relative flex size-2 shrink-0">
						<span
							class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-60"
						></span>
						<span class="relative inline-flex rounded-full size-2 bg-blue-500"></span>
					</span>
				{:else if d.ok}
					<span class="text-blue-500 shrink-0">✓</span>
				{:else}
					<span class="text-red-500 shrink-0">✗</span>
				{/if}
				<span class="font-medium text-gray-700 dark:text-gray-200 truncate">{toolLabel(d.tool)}</span>
			</div>
			{#if d.output}
				<div class="mt-1 text-[10px] text-gray-400 line-clamp-2 break-words">{d.output}</div>
			{/if}
		</Tooltip>
	{:else if d.kind === 'summary'}
		{#if d.cancelled}
			<div class="flex items-center gap-1.5">
				<span class="text-amber-500">■</span>
				<span class="font-medium text-gray-700 dark:text-gray-200">{$i18n.t('Cancelled')}</span>
			</div>
		{:else}
			<div class="flex items-center gap-1.5">
				<span class="text-blue-500">✓</span>
				<span class="font-medium text-gray-700 dark:text-gray-200">{$i18n.t('Done')}</span>
			</div>
			{#if d.summary}
				<div class="mt-1 text-[10px] text-gray-500 line-clamp-3 break-words">{d.summary}</div>
			{/if}
		{/if}
	{:else if d.kind === 'run'}
		<div class="cursor-pointer">
			<div class="flex items-center gap-1.5">
				<span class="size-2 rounded-full shrink-0 {runDot(d.status)}"></span>
				<span class="font-medium text-gray-800 dark:text-gray-100 truncate">{d.label}</span>
			</div>
			<div class="mt-1 flex items-center gap-2 text-[10px] text-gray-400">
				{#if d.status}<span>{d.status}</span>{/if}
				{#if d.toolCalls}<span>· {d.toolCalls} 🔧</span>{/if}
				{#if d.durationMs}<span>· {fmtDur(d.durationMs)}</span>{/if}
			</div>
		</div>
	{:else if d.kind === 'decision'}
		<!-- lane/risk gate badge: allow ✓ / deny ✗ / gate ⛨ -->
		<div class="flex items-center gap-1.5">
			<span
				class="shrink-0 {d.policy === 'allow'
					? 'text-emerald-500'
					: d.policy === 'deny'
						? 'text-red-500'
						: 'text-amber-500'}">{d.policy === 'allow' ? '✓' : d.policy === 'deny' ? '✗' : '⛨'}</span
			>
			<span class="font-medium text-gray-700 dark:text-gray-200 truncate">
				{d.tool ? toolLabel(d.tool) : $i18n.t('Policy')} · {d.policy || 'gate'}
			</span>
		</div>
		{#if d.reason}
			<div class="mt-1 text-[10px] text-gray-400 line-clamp-2 break-words">{d.reason}</div>
		{/if}
	{:else if d.kind === 'artifact'}
		<div class="flex items-center gap-1.5">
			<span class="text-indigo-400 shrink-0">◆</span>
			<span class="font-medium text-gray-700 dark:text-gray-200 truncate">{d.label || $i18n.t('Artifact')}</span>
		</div>
		{#if d.path}
			<div class="mt-1 font-mono text-[10px] text-gray-400 truncate">{d.path}</div>
		{/if}
	{:else if d.kind === 'error'}
		<div class="flex items-center gap-1.5">
			<span class="text-red-500">!</span>
			<span class="font-medium text-red-600 dark:text-red-400">{$i18n.t('Error')}</span>
		</div>
		<div class="mt-1 text-[10px] text-red-500 line-clamp-3 break-words">{d.message}</div>
		{#if d.fixHint}<div class="mt-0.5 text-[10px] text-gray-400 line-clamp-2">{d.fixHint}</div>{/if}
	{/if}

	{#if d.kind !== 'run'}
		<!-- Global Map run nodes have no edges → no handles (avoids dangling stubs). -->
		<Handle
			type="target"
			position={Position.Top}
			class="!w-1.5 !h-1.5 !min-w-0 !min-h-0 rounded-full !bg-gray-300 dark:!bg-gray-700 !border-0"
		/>
		<Handle
			type="source"
			position={Position.Bottom}
			class="!w-1.5 !h-1.5 !min-w-0 !min-h-0 rounded-full !bg-gray-300 dark:!bg-gray-700 !border-0"
		/>
	{/if}
</div>
