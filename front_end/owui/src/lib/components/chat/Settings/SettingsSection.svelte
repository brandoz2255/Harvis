<script lang="ts">
	// Shared presentational heading for a settings section: 18px semibold with
	// generous top margin and no divider above. Content (SettingRow list) goes
	// in the default slot; may also be used self-closing as a heading only.
	export let title = '';
	export let className = '';
</script>

<section class="pt-7 first:pt-1 {className}">
	{#if title}
		<h3 class="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h3>
	{/if}
	{#if $$slots.description}
		<div class="mt-0.5 text-sm text-gray-500 dark:text-gray-400"><slot name="description" /></div>
	{/if}
	{#if $$slots.default}
		<div class="mt-1"><slot /></div>
	{/if}
</section>
