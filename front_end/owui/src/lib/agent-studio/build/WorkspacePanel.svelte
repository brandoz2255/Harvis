<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';

	const dispatch = createEventDispatcher();
	const i18n: any = getContext('i18n');

	// One quadrant of the Build panel grid: a thin header (title · actions · dismiss-X)
	// over a scrollable body slot. Pure chrome — the dismiss X just emits `dismiss`;
	// the page collapses the matching PaneForge pane.
	export let title = '';
	export let dismissible = true;
	// When the body slot hosts a component that manages its own scroll (FileRail,
	// MainPanel), set scroll=false so we don't double-scroll/clip it.
	export let scroll = true;
</script>

<div
	class="flex flex-col min-h-0 h-full bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-white/10 shadow-lg shadow-black/30 overflow-hidden text-gray-700 dark:text-gray-200"
>
	<div class="shrink-0 flex items-center gap-2 px-3 h-8 border-b border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05]">
		{#if title}
			<span class="text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-400 truncate"
				>{title}</span
			>
		{/if}
		<div class="ml-auto flex items-center gap-1 shrink-0">
			<slot name="actions" />
			{#if dismissible}
				<button
					class="text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 transition"
					aria-label={$i18n.t('Hide panel')}
					title={$i18n.t('Hide panel')}
					on:click={() => dispatch('dismiss')}
				>
					<svg viewBox="0 0 20 20" fill="currentColor" class="size-3.5">
						<path
							d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"
						/>
					</svg>
				</button>
			{/if}
		</div>
	</div>
	<div class="flex-1 min-h-0 {scroll ? 'overflow-auto' : ''}">
		<slot />
	</div>
</div>
