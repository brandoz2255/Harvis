<script lang="ts">
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { showSidebar, WEBUI_NAME } from '$lib/stores';
	import { surfaceByKey } from '$lib/agent-studio/surfaces';

	const i18n: any = getContext('i18n');

	$: surface = surfaceByKey($page.params.surface);
</script>

<svelte:head>
	<title>{surface ? $i18n.t(surface.label) : $i18n.t('Agent Studio')} • {$WEBUI_NAME}</title>
</svelte:head>

<!-- Sit in the app shell's content column (right of the fixed sidebar), like the chat route. -->
<div class="w-full h-full {$showSidebar ? 'md:max-w-[calc(100%-var(--sidebar-width))]' : ''}">
	{#if surface}
		{#key surface.key}
			<svelte:component this={surface.component} mode="full" />
		{/key}
	{:else}
		<div class="w-full h-full flex items-center justify-center text-sm text-gray-400">
			{$i18n.t('Surface not found')}
		</div>
	{/if}
</div>
