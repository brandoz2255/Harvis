<script lang="ts">
	import type { RunActivity } from '$lib/agent-studio/runEventProjection';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ListBullet from '$lib/components/icons/ListBullet.svelte';

	export let activity: RunActivity;
	export let phase = 'connecting';
	export let stalled = false;
	export let onRetry: (() => void) | null = null;

	let expanded = false;

	$: terminal = phase === 'done' || phase === 'error' || phase === 'cancelled';
	$: statusLabel =
		phase === 'error'
			? 'Run failed'
			: phase === 'cancelled'
				? 'Run cancelled'
				: terminal
					? 'Activity complete'
					: 'Activity in progress';
	$: dotClass =
		phase === 'error'
			? 'bg-red-500'
			: phase === 'cancelled'
				? 'bg-amber-500'
				: terminal
					? 'bg-emerald-500'
					: 'bg-blue-500 animate-pulse motion-reduce:animate-none';

	const itemGlyph = (status: string) =>
		status === 'succeeded'
			? '✓'
			: status === 'failed'
				? '×'
				: status === 'cancelled'
					? '–'
					: '•';

	const itemClass = (status: string) =>
		status === 'succeeded'
			? 'text-emerald-600 dark:text-emerald-400'
			: status === 'failed'
				? 'text-red-600 dark:text-red-400'
				: status === 'cancelled'
					? 'text-amber-600 dark:text-amber-400'
					: 'text-blue-600 dark:text-blue-400';
</script>

<section
	class="not-prose my-2 w-full min-w-0 max-w-full overflow-hidden rounded-xl border border-gray-200/90 bg-gray-50/70 dark:border-white/10 dark:bg-white/[0.025]"
>
	<button
		type="button"
		class="flex min-h-11 w-full min-w-0 items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-gray-100/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 dark:hover:bg-white/[0.035]"
		aria-expanded={expanded}
		on:click={() => (expanded = !expanded)}
	>
		<span class="flex size-7 shrink-0 items-center justify-center rounded-md bg-white text-gray-500 shadow-xs dark:bg-white/[0.055] dark:text-gray-300">
			<ListBullet className="size-3.5" />
		</span>
		<span class="relative flex size-2 shrink-0">
			<span class="size-2 rounded-full {dotClass}"></span>
		</span>
		<span class="min-w-0 flex-1 overflow-hidden text-sm font-medium text-gray-700 dark:text-gray-200">
			{#key activity.headline}
				<span class="activity-headline block truncate">{activity.headline}</span>
			{/key}
		</span>
		<span class="hidden shrink-0 text-[11px] text-gray-400 sm:inline">{statusLabel}</span>
		<ChevronDown
			className="size-4 shrink-0 text-gray-400 transition-transform duration-150 motion-reduce:transition-none {expanded
				? 'rotate-180'
				: ''}"
		/>
	</button>

	<div class="sr-only" role="status" aria-live="polite">{statusLabel}: {activity.headline}</div>

	{#if stalled && !terminal}
		<div class="flex flex-wrap items-center gap-2 border-t border-amber-500/15 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
			<span>The activity stream is quiet. The run may still be working.</span>
			{#if onRetry}
				<button
					type="button"
					class="font-medium underline decoration-amber-500/40 underline-offset-2 hover:decoration-current focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
					on:click={onRetry}
				>
					Reconnect
				</button>
			{/if}
		</div>
	{/if}

	{#if expanded}
		<div class="border-t border-gray-200/80 px-3 py-2.5 dark:border-white/10">
			{#if activity.items.length}
				<ul class="space-y-1.5" aria-label="Run activity">
					{#each activity.items as item (item.id)}
						<li class="flex min-w-0 items-start gap-2 text-xs leading-5">
							<span class="mt-px w-3 shrink-0 text-center font-semibold {itemClass(item.status)}">
								{itemGlyph(item.status)}
							</span>
							<span class="shrink-0 font-medium text-gray-700 dark:text-gray-200">{item.label}</span>
							{#if item.detail}
								<span class="min-w-0 break-all font-mono text-[11px] text-gray-500 dark:text-gray-400">
									{item.detail}
								</span>
							{/if}
						</li>
					{/each}
				</ul>
			{:else}
				<div class="text-xs text-gray-500 dark:text-gray-400">
					No tool activity has been recorded yet.
				</div>
			{/if}
		</div>
	{/if}
</section>

<style>
	.activity-headline {
		animation: activity-slide 160ms ease-out;
	}

	@keyframes activity-slide {
		from {
			opacity: 0;
			transform: translateY(5px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.activity-headline {
			animation: none;
		}
	}
</style>
