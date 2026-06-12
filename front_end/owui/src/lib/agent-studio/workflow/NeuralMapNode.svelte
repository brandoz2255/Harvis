<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';

	export let data: any;

	$: r = data?.r ?? 6;
	$: kind = data?.kind ?? 'run';
	$: color =
		kind === 'session'
			? 'bg-gray-400 dark:bg-gray-500'
			: data?.status === 'error'
				? 'bg-red-500'
				: data?.status === 'cancelled'
					? 'bg-amber-500'
					: 'bg-blue-500';
	$: running = kind === 'run' && data?.status === 'running';

	// Hidden 1px handles centered on the dot → straight edges run center-to-center
	// (the Obsidian look). Edges hard-require a source+target Handle to render.
	const handleStyle =
		'left: 50%; top: 50%; right: auto; bottom: auto; transform: translate(-50%, -50%); ' +
		'opacity: 0; width: 1px; height: 1px; min-width: 0; min-height: 0; border: 0; pointer-events: none;';
</script>

<!-- The measured node box is exactly the dot (r*2 square); the label hangs below
     via absolute positioning so it never grows the box (keeps edge anchors true). -->
<div class="group relative cursor-pointer" style="width: {r * 2}px; height: {r * 2}px;">
	<Handle type="target" position={Position.Top} style={handleStyle} />
	<Handle type="source" position={Position.Bottom} style={handleStyle} />

	<div
		class="absolute inset-0 rounded-full {color} {kind === 'session'
			? 'ring-2 ring-gray-300/50 dark:ring-gray-600/50'
			: ''} transition-transform duration-150 group-hover:scale-125"
	></div>
	{#if running}
		<div class="absolute inset-0 rounded-full bg-blue-500 animate-ping opacity-60"></div>
	{/if}

	<!-- truncated label under the dot; swaps for the full pill on hover -->
	<div
		class="absolute top-full left-1/2 -translate-x-1/2 mt-1 max-w-[88px] truncate text-[9px] leading-tight text-gray-500 dark:text-gray-400 text-center pointer-events-none group-hover:opacity-0"
	>
		{data?.label ?? ''}
	</div>
	<div
		class="absolute top-full left-1/2 -translate-x-1/2 mt-1 hidden group-hover:block z-10 px-2 py-1 rounded-lg bg-gray-900/95 text-gray-100 text-[10px] whitespace-nowrap max-w-[260px] truncate pointer-events-none shadow-lg"
	>
		{data?.label ?? ''}{#if kind === 'session' && data?.count}&nbsp;· {data.count}{/if}
	</div>
</div>
