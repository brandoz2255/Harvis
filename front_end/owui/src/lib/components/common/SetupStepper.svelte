<script lang="ts">
	export let steps: string[] = [];
	export let current = 0;
</script>

<div class="flex flex-wrap gap-2 mb-6" role="list" aria-label="Setup steps">
	{#each steps as label, i}
		<div
			role="listitem"
			class="px-2.5 py-1 rounded-full text-xs font-medium border transition
				{i === current
				? 'border-gray-900 dark:border-white bg-gray-900 text-white dark:bg-white dark:text-black'
				: i < current
					? 'border-emerald-600/40 text-emerald-700 dark:text-emerald-400'
					: 'border-gray-200 dark:border-gray-700 text-gray-500'}"
		>
			<span class="opacity-70 mr-1">{i + 1}.</span>{label}
		</div>
	{/each}
</div>
