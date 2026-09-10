<script lang="ts">
	/*
	 * One setting: label and explanation on the left, its control on the right.
	 *
	 * The control is `shrink-0` and vertically centred so a switch stays level
	 * with its label instead of drifting against a two-line description.
	 *
	 * The left column needs `flex-1` and not just `min-w-0`: without a flex
	 * basis it sizes to its content, so a `w-full` input dropped into the
	 * `detail` slot resolves its percentage against an auto width and collapses
	 * to the browser's default field size. Prose fills the column either way,
	 * which is why this only shows up on panes with inputs.
	 */
	export let label = '';
	export let description = '';
</script>

<div class="flex items-start justify-between gap-6 py-3">
	<div class="flex-1 min-w-0">
		{#if label}
			<div class="text-xs font-medium text-gray-800 dark:text-gray-100 break-words">{label}</div>
		{/if}
		{#if description}
			<p class="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">{description}</p>
		{/if}
		<slot name="detail" />
	</div>
	{#if $$slots.default}
		<div class="shrink-0 self-center"><slot /></div>
	{/if}
</div>
