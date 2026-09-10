<script lang="ts">
	/*
	 * Shared frame for an Admin → Settings pane.
	 *
	 * Why this exists: every pane used to be its own
	 * `<form class="flex flex-col h-full justify-between">`. That pins the
	 * content to the top of the viewport and the Save button to the very
	 * bottom, so a pane with two switches renders as two rows, several hundred
	 * pixels of nothing, and a lone button stranded at the bottom — the
	 * "doesn't fill in" look.
	 *
	 * Here the content flows naturally and the actions row is a sticky bar that
	 * rides the bottom of the scroll container, so Save is always reachable
	 * without inventing empty space to push it down to.
	 */
	export let title = '';
	export let description = '';
</script>

<div class="flex flex-col min-h-full">
	<div class="flex-1 pb-4">
		{#if title}
			<header class="pb-3 mb-4 border-b border-gray-100 dark:border-gray-850">
				<h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{title}</h2>
				{#if description}
					<p class="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						{description}
					</p>
				{/if}
			</header>
		{/if}

		<slot />
	</div>

	<!--
	  `$$slots.actions` is compile-time: a pane whose Save button sits behind an
	  {#if} still reports the slot as filled, which would leave an empty bordered
	  strip pinned to the bottom. `hidden has-[>*]:flex` collapses the bar unless
	  the slot actually rendered an element (Svelte's {#if} anchors are comments,
	  which :has(> *) ignores).
	-->
	{#if $$slots.actions}
		<div
			class="sticky bottom-0 hidden has-[>*]:flex justify-end gap-2 py-3 border-t border-gray-100 dark:border-gray-850 bg-white/85 dark:bg-gray-900/85 backdrop-blur-sm"
		>
			<slot name="actions" />
		</div>
	{/if}
</div>
