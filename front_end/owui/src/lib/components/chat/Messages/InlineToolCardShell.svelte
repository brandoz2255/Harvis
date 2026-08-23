<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	export let status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' = 'queued';
	export let statusLabel = 'Queued';
	export let expanded = true;
	export let expandable = true;
	export let className = '';

	const dispatch = createEventDispatcher<{ toggle: { expanded: boolean } }>();

	const STATUS_CLASS = {
		queued: 'border-gray-200/90 dark:border-white/10',
		running: 'border-blue-400/40 dark:border-blue-400/30 shadow-sm shadow-blue-950/5',
		succeeded: 'border-emerald-500/25 dark:border-emerald-400/20',
		failed: 'border-red-500/30 dark:border-red-400/25',
		cancelled: 'border-amber-500/30 dark:border-amber-400/25'
	};

	const toggle = () => {
		if (!expandable) return;
		dispatch('toggle', { expanded: !expanded });
	};
</script>

<section
	class="inline-tool-card-shell not-prose w-full min-w-0 max-w-full overflow-hidden rounded-xl border bg-white/80 dark:bg-[#111318] {STATUS_CLASS[
		status
	]} {className}"
	data-status={status}
>
	<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 sm:flex-nowrap sm:px-3.5">
		<slot name="leading" />
		<div class="min-w-0 flex-1">
			<slot name="header" />
		</div>
		<div class="flex min-w-0 shrink-0 items-center gap-1">
			<slot name="actions" />
			{#if expandable}
				<button
					type="button"
					class="flex size-11 shrink-0 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-gray-100 sm:size-9"
					aria-label={expanded ? 'Collapse tool activity' : 'Expand tool activity'}
					aria-expanded={expanded}
					on:click={toggle}
				>
					<ChevronDown
						className="size-4 transition-transform duration-150 motion-reduce:transition-none {expanded
							? 'rotate-180'
							: ''}"
					/>
				</button>
			{/if}
		</div>
	</div>

	<div class="sr-only" role="status" aria-live="polite">{statusLabel}</div>

	{#if expanded}
		<div class="min-w-0 border-t border-gray-200/80 dark:border-white/10">
			<slot />
		</div>
	{/if}

	<slot name="footer" />
</section>
