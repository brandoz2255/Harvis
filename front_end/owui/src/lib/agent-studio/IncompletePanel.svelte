<script lang="ts">
	import { getContext } from 'svelte';

	const i18n: any = getContext('i18n');

	export let title = 'Work in progress';
	export let message = 'This panel is being reworked.';
</script>

<div class="flex flex-col items-center justify-center h-full px-6 py-10 text-center gap-1.5">
	<span class="text-sm font-medium text-gray-500 dark:text-gray-400">{$i18n.t(title)}</span>
	<span class="text-xs text-gray-400 max-w-xs">{$i18n.t(message)}</span>
</div>
