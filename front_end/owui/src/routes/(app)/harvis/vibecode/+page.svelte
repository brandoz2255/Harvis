<script lang="ts">
	import { getContext } from 'svelte';
	import { WEBUI_NAME } from '$lib/stores';

	const i18n: any = getContext('i18n');
</script>

<svelte:head>
	<title>{$i18n.t('Vibe Code')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full flex flex-col items-center justify-center text-center px-4">
	<h1 class="text-xl font-medium text-gray-800 dark:text-gray-100 mb-2">{$i18n.t('Vibe Code')}</h1>
	<p class="text-sm text-gray-500 max-w-md">
		{$i18n.t(
			'The Harvis coding IDE is coming here. For now, ask Harvis to write or edit code in chat.'
		)}
	</p>
</div>
