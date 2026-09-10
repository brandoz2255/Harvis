<script lang="ts">
	/*
	 * A titled card grouping related settings inside a Pane.
	 *
	 * Grouping is what makes a short pane read as deliberate rather than empty:
	 * two switches inside a titled card say "this is the whole section", where
	 * two bare rows on a blank page say "the rest failed to load".
	 */
	export let title = '';
	export let description = '';
</script>

<section
	class="mb-3 rounded-xl border border-gray-100 dark:border-gray-850 bg-gray-50/60 dark:bg-gray-900/40"
>
	{#if title}
		<div class="px-4 pt-3">
			<div class="flex items-start justify-between gap-3">
				<h3 class="text-xs font-semibold text-gray-700 dark:text-gray-200">{title}</h3>
				<!-- Header-level action, e.g. a "rescan" link that belongs to the whole section. -->
				<slot name="action" />
			</div>
			{#if description}
				<p class="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">{description}</p>
			{/if}
		</div>
	{/if}
	<div class="px-4 divide-y divide-gray-100 dark:divide-gray-850/70">
		<slot />
	</div>
</section>
